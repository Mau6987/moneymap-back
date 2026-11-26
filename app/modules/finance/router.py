"""Finanzas (spec 002 y 007): solo HTTP.

Valida con el esquema, llama al caso de uso y devuelve el esquema. Sin SQL y sin
reglas. Las cuentas están en `accounts_router.py` y los movimientos y
recurrentes en `transactions_router.py`; aquí, la configuración, las monedas,
los catálogos, las categorías y el onboarding.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_current_user_id
from app.core.validation import CurrencyCode
from app.modules.finance.accounts_router import router as accounts_router
from app.modules.finance.application.commands.add_currency import add_currency
from app.modules.finance.application.commands.complete_onboarding import complete_onboarding
from app.modules.finance.application.commands.create_category import create_category
from app.modules.finance.application.commands.delete_category import delete_category
from app.modules.finance.application.commands.remove_currency import remove_currency
from app.modules.finance.application.commands.update_category import update_category
from app.modules.finance.application.commands.update_settings import update_settings
from app.modules.finance.application.queries.get_catalog import get_countries, get_institutions
from app.modules.finance.application.queries.get_categories import get_categories
from app.modules.finance.application.queries.get_currencies import get_currencies
from app.modules.finance.application.queries.get_onboarding_status import get_onboarding_status
from app.modules.finance.application.queries.get_safe_to_spend import get_safe_to_spend
from app.modules.finance.application.queries.get_settings import get_settings
from app.modules.finance.deps import (
    get_catalog_reader,
    get_category_repository,
    get_currencies_repository,
    get_onboarding_repository,
    get_safe_to_spend_reader,
    get_settings_repository,
)
from app.modules.finance.domain.ports import (
    CatalogReader,
    CategoryRepository,
    CurrenciesRepository,
    OnboardingRepository,
    SafeToSpendReader,
    SettingsRepository,
)
from app.modules.finance.receipts_router import router as receipts_router
from app.modules.finance.recurring_receipts_router import router as recurring_receipts_router
from app.modules.finance.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryType,
    CategoryUpdate,
    CountryRead,
    CurrencyRead,
    InstitutionRead,
    OnboardingStatusRead,
    OnboardingSummaryRead,
    SafeToSpendRead,
    SettingsRead,
    SettingsUpdate,
)
from app.modules.finance.transactions_router import router as transactions_router

router = APIRouter(tags=["finance"])
router.include_router(accounts_router)
router.include_router(transactions_router)
router.include_router(receipts_router)
router.include_router(recurring_receipts_router)

User = Annotated[UUID, Depends(get_current_user_id)]


@router.get(
    "/me/settings",
    response_model=SettingsRead,
    summary="La moneda principal, el periodo y el ahorro planificado",
)
async def get_settings_route(
    user_id: User,
    settings: Annotated[SettingsRepository, Depends(get_settings_repository)],
) -> SettingsRead:
    """RF-1 y spec 003, RF-7: sin moneda principal todavía, 422 `onboarding_incomplete`."""
    return SettingsRead.from_record(await get_settings(user_id, settings))


@router.put(
    "/me/settings",
    response_model=SettingsRead,
    summary="Guarda la moneda principal, el periodo y el ahorro planificado",
)
async def update_settings_route(
    payload: SettingsUpdate,
    user_id: User,
    settings: Annotated[SettingsRepository, Depends(get_settings_repository)],
) -> SettingsRead:
    """RF-1 y spec 003, RF-7 a RF-9: la primera vez siembra las categorías iniciales."""
    stored = await update_settings(payload.to_changes(), user_id, settings)
    return SettingsRead.from_record(stored)


@router.get(
    "/safe-to-spend",
    response_model=SafeToSpendRead,
    summary="Cuánto queda libre en el periodo",
)
async def get_safe_to_spend_route(
    user_id: User,
    reader: Annotated[SafeToSpendReader, Depends(get_safe_to_spend_reader)],
    currency: Annotated[CurrencyCode | None, Query(examples=["BOB"])] = None,
) -> SafeToSpendRead:
    """Spec 003, RF-1 a RF-6: saldo − recurrentes pendientes − ahorro planificado − aportes a metas."""
    return SafeToSpendRead.from_record(await get_safe_to_spend(user_id, currency, reader))


@router.get(
    "/currencies",
    response_model=list[CurrencyRead],
    summary="Monedas disponibles: Mis monedas primero",
)
async def get_currencies_route(
    user_id: User,
    currencies: Annotated[CurrenciesRepository, Depends(get_currencies_repository)],
) -> list[CurrencyRead]:
    """RF-2 y RF-20: Mis monedas primero y después las demás activas."""
    options = await get_currencies(user_id, currencies)
    return [CurrencyRead.from_record(option) for option in options]


@router.put(
    "/me/currencies/{code}",
    response_model=CurrencyRead,
    summary="Suma una moneda a Mis monedas",
)
async def add_currency_route(
    code: CurrencyCode,
    user_id: User,
    currencies: Annotated[CurrenciesRepository, Depends(get_currencies_repository)],
) -> CurrencyRead:
    """RF-28: idempotente; una moneda desactivada o que no existe, 422 `currency_unavailable`."""
    return CurrencyRead.from_record(await add_currency(code, user_id, currencies))


@router.delete(
    "/me/currencies/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quita una moneda de Mis monedas",
)
async def remove_currency_route(
    code: CurrencyCode,
    user_id: User,
    currencies: Annotated[CurrenciesRepository, Depends(get_currencies_repository)],
) -> Response:
    """RF-19: la principal o una con cuentas activas responde 409 `currency_in_use`."""
    await remove_currency(code, user_id, currencies)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/countries", response_model=list[CountryRead], summary="Países con su moneda local")
async def get_countries_route(
    _: User,
    catalog: Annotated[CatalogReader, Depends(get_catalog_reader)],
) -> list[CountryRead]:
    """Spec 007: el país sugiere la moneda principal y los bancos del onboarding."""
    return [CountryRead.from_record(country) for country in await get_countries(catalog)]


@router.get("/institutions", response_model=list[InstitutionRead], summary="Bancos y billeteras de un país")
async def get_institutions_route(
    _: User,
    catalog: Annotated[CatalogReader, Depends(get_catalog_reader)],
    country: Annotated[str, Query(pattern=r"^[A-Z]{2}$", examples=["BO"])],
) -> list[InstitutionRead]:
    """Spec 002, RF-3: el banco de una tarjeta se elige de este catálogo."""
    return [InstitutionRead.from_record(item) for item in await get_institutions(country, catalog)]


@router.get("/categories", response_model=list[CategoryRead], summary="Las categorías del usuario")
async def get_categories_route(
    user_id: User,
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    category_type: Annotated[CategoryType | None, Query(alias="type")] = None,
) -> list[CategoryRead]:
    """Spec 007, RF-6: con su grupo del Money Flow, su ícono y su color."""
    records = await get_categories(user_id, category_type, categories)
    return [CategoryRead.from_record(record) for record in records]


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crea una categoría",
)
async def create_category_route(
    payload: CategoryCreate,
    user_id: User,
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> CategoryRead:
    """Spec 007, RF-7 a RF-9: el nombre repetido en el mismo tipo responde 409."""
    return CategoryRead.from_record(await create_category(payload.to_new_category(), user_id, categories))


@router.patch("/categories/{category_id}", response_model=CategoryRead, summary="Corrige una categoría")
async def update_category_route(
    category_id: UUID,
    payload: CategoryUpdate,
    user_id: User,
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> CategoryRead:
    """Spec 007, RF-10 y RF-11: con movimientos o recurrentes, el tipo no cambia (409)."""
    return CategoryRead.from_record(await update_category(payload.to_changes(), category_id, user_id, categories))


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra una categoría",
)
async def delete_category_route(
    category_id: UUID,
    user_id: User,
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> Response:
    """Spec 007, RF-12: sus movimientos quedan como `sin_categoria` en los reportes."""
    await delete_category(category_id, user_id, categories)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/onboarding", response_model=OnboardingStatusRead, summary="Hasta dónde llegó el onboarding")
async def get_onboarding_route(
    user_id: User,
    onboarding: Annotated[OnboardingRepository, Depends(get_onboarding_repository)],
) -> OnboardingStatusRead:
    """Spec 007, RF-3: la app lo lee al iniciar sesión para retomar donde quedó."""
    return OnboardingStatusRead.from_record(await get_onboarding_status(user_id, onboarding))


@router.post(
    "/onboarding/complete",
    response_model=OnboardingSummaryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cierra el onboarding con el resumen del periodo",
)
async def complete_onboarding_route(
    user_id: User,
    onboarding: Annotated[OnboardingRepository, Depends(get_onboarding_repository)],
) -> OnboardingSummaryRead:
    """Spec 007, RF-4 y RF-5: idempotente; sin cuentas, 422 `onboarding_incomplete`."""
    return OnboardingSummaryRead.from_record(await complete_onboarding(user_id, onboarding))
