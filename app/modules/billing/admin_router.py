"""Panel de administrador de los planes (MM-189, spec 013): solo HTTP.

Se entra con el mismo login: el usuario del token tiene que ser el
administrador (`iam.users.is_admin`). Para cualquier otro, estas rutas no
existen (404), así no se revela que hay un panel. La base vuelve a mirar el rol
en cada escritura y audita los cambios.
"""

from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.errors import NotFound
from app.core.validation import CurrencyCode
from app.modules.billing.application.commands.admin_plans import set_plan_feature, set_plan_price, update_plan
from app.modules.billing.application.queries.get_admin_plans import get_admin_changes, get_admin_plans
from app.modules.billing.deps import get_admin_plans as admin_plans_dep
from app.modules.billing.domain.ports import AdminPlans
from app.modules.billing.schemas import (
    AdminChangeRead,
    AdminFeatureUpdate,
    AdminPlanRead,
    AdminPlanUpdate,
    AdminPriceUpdate,
)


async def require_admin(admin: Annotated[AdminPlans, Depends(admin_plans_dep)]) -> AdminPlans:
    """El panel solo existe para el administrador; para el resto, 404."""
    if not await admin.is_admin():
        raise NotFound()
    return admin


Admin = Annotated[AdminPlans, Depends(require_admin)]

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/plans", response_model=list[AdminPlanRead], summary="Los cuatro planes con todo lo editable")
async def list_plans_route(admin: Admin) -> Sequence[AdminPlanRead]:
    """Datos, precios activos, cada funcionalidad del catálogo y cuántos usuarios tiene cada plan."""
    return [AdminPlanRead.from_record(plan) for plan in await get_admin_plans(admin)]


@router.patch("/plans/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="Nombre, descripción y visibilidad")
async def update_plan_route(code: str, payload: AdminPlanUpdate, admin: Admin) -> Response:
    """409 `free_plan_required` si se intenta ocultar el gratuito."""
    await update_plan(code, payload.name, payload.description, payload.is_public, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/plans/{code}/features/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Si el plan tiene una funcionalidad y con qué límite",
)
async def set_feature_route(code: str, key: str, payload: AdminFeatureUpdate, admin: Admin) -> Response:
    """`limit` null = ilimitado. Bajarlo no borra nada: solo impide crear más."""
    await set_plan_feature(code, key, payload.enabled, payload.limit, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/plans/{code}/prices/{period}/{currency}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="El precio mensual o anual de un plan en una moneda",
)
async def set_price_route(
    code: str,
    period: Literal["month", "year"],
    currency: CurrencyCode,
    payload: AdminPriceUpdate,
    admin: Admin,
) -> Response:
    """El precio anterior se cierra y se abre otro: quien ya pagó sigue con el suyo."""
    await set_plan_price(code, period, currency, payload.amount, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/plan-changes", response_model=list[AdminChangeRead], summary="Historial de cambios a los planes")
async def list_changes_route(
    admin: Admin, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> Sequence[AdminChangeRead]:
    """El más nuevo primero."""
    return [AdminChangeRead.from_record(change) for change in await get_admin_changes(admin, limit)]
