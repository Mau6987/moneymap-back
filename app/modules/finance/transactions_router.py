"""Movimientos y recurrentes (spec 002 y 007): solo HTTP, sin SQL ni reglas."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_current_user_id
from app.core.idempotency import IdempotentRequest, get_idempotent_request
from app.core.validation import CurrencyCode
from app.modules.finance.application.commands.create_recurring_rule import create_recurring_rule
from app.modules.finance.application.commands.delete_recurring_rule import delete_recurring_rule
from app.modules.finance.application.commands.delete_transaction import delete_transaction
from app.modules.finance.application.commands.register_recurring_payment import register_recurring_payment
from app.modules.finance.application.commands.register_transaction import register_transaction
from app.modules.finance.application.commands.skip_recurring_occurrence import skip_recurring_occurrence
from app.modules.finance.application.commands.update_recurring_rule import update_recurring_rule
from app.modules.finance.application.commands.update_transaction import update_transaction
from app.modules.finance.application.queries.get_category_suggestion import get_category_suggestion
from app.modules.finance.application.queries.get_recurring_rules import get_recurring_rules
from app.modules.finance.application.queries.get_transactions import get_transactions
from app.modules.finance.deps import (
    get_category_repository,
    get_recurring_rule_repository,
    get_transaction_history_reader,
    get_transaction_repository,
)
from app.modules.finance.domain.models import TransactionFilters
from app.modules.finance.domain.ports import (
    CategoryRepository,
    RecurringRuleRepository,
    TransactionHistoryReader,
    TransactionRepository,
)
from app.modules.finance.schemas import (
    TRANSACTION_DESCRIPTION_MAX_LENGTH,
    TRANSACTION_PAGE_DEFAULT_SIZE,
    TRANSACTION_PAGE_MAX_SIZE,
    CategoryRead,
    CategoryType,
    RecurringPaymentCreate,
    RecurringPaymentRead,
    RecurringRuleCreate,
    RecurringRuleRead,
    RecurringRuleUpdate,
    TransactionCreate,
    TransactionPageRead,
    TransactionRead,
    TransactionUpdate,
    decode_cursor,
)

router = APIRouter()

User = Annotated[UUID, Depends(get_current_user_id)]


@router.get(
    "/transactions",
    response_model=TransactionPageRead,
    summary="El historial de movimientos",
)
async def get_transactions_route(
    user_id: User,
    history: Annotated[TransactionHistoryReader, Depends(get_transaction_history_reader)],
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    currency: Annotated[CurrencyCode | None, Query(examples=["BOB"])] = None,
    from_date: Annotated[date | None, Query(alias="from", description="Desde ese día, incluido")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Hasta ese día, incluido")] = None,
    q: Annotated[
        str | None, Query(max_length=TRANSACTION_DESCRIPTION_MAX_LENGTH, description="Texto de la descripción")
    ] = None,
    cursor: Annotated[str | None, Query(description="El `next_cursor` de la página anterior")] = None,
    limit: Annotated[int, Query(ge=1, le=TRANSACTION_PAGE_MAX_SIZE)] = TRANSACTION_PAGE_DEFAULT_SIZE,
) -> TransactionPageRead:
    """RF-26 y RF-32: del más reciente al más viejo, con los filtros que lleguen.

    El `next_cursor` sirve con los mismos filtros: si cambian, se pide desde la primera página.
    """
    filters = TransactionFilters(account_id, category_id, from_date, to_date, q, currency)
    after = None if cursor is None else decode_cursor(cursor)
    return TransactionPageRead.from_record(await get_transactions(user_id, filters, after, limit, history))


@router.post(
    "/transactions",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Registra un movimiento",
)
async def register_transaction_route(
    payload: TransactionCreate,
    user_id: User,
    repository: Annotated[TransactionRepository, Depends(get_transaction_repository)],
    idempotency: Annotated[IdempotentRequest, Depends(get_idempotent_request)],
) -> TransactionRead:
    """RF-6 a RF-8 y RF-10 a RF-12: un gasto, un ingreso o una transferencia.

    Con `Idempotency-Key`, un reintento devuelve la misma respuesta sin crear un
    segundo movimiento (requisito no funcional de la spec 002).
    """
    stored = await idempotency.replay()
    if stored is not None:
        return TransactionRead.model_validate_json(stored)
    record = await register_transaction(payload.to_new_transaction(), user_id, repository)
    response = TransactionRead.from_record(record)
    await idempotency.remember(response.model_dump_json())
    return response


@router.patch(
    "/transactions/{transaction_id}",
    response_model=TransactionRead,
    summary="Corrige un movimiento",
)
async def update_transaction_route(
    transaction_id: UUID,
    payload: TransactionUpdate,
    user_id: User,
    repository: Annotated[TransactionRepository, Depends(get_transaction_repository)],
) -> TransactionRead:
    """RF-13: la moneda no se cambia; si la cuenta nueva es de otra, 422."""
    record = await update_transaction(payload.to_changes(), transaction_id, user_id, repository)
    return TransactionRead.from_record(record)


@router.delete(
    "/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra un movimiento",
)
async def delete_transaction_route(
    transaction_id: UUID,
    user_id: User,
    repository: Annotated[TransactionRepository, Depends(get_transaction_repository)],
) -> Response:
    """RF-27: el saldo vuelve a sus cuentas; el que no existe o no es del usuario, 404."""
    await delete_transaction(transaction_id, user_id, repository)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/transactions/category-suggestion",
    response_model=CategoryRead,
    responses={204: {"description": "No hay un movimiento anterior con esa descripción"}},
    summary="Sugiere la categoría de la última vez",
)
async def get_category_suggestion_route(
    user_id: User,
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    description: Annotated[
        str, Query(max_length=TRANSACTION_DESCRIPTION_MAX_LENGTH, pattern=r"\S", examples=["Netflix"])
    ],
    category_type: Annotated[CategoryType, Query(alias="type")],
) -> CategoryRead | Response:
    """Spec 007, RF-13 y RF-14: sin IA, sin mayúsculas ni tildes; si no hay, 204."""
    suggestion = await get_category_suggestion(user_id, description, category_type, categories)
    if suggestion is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return CategoryRead.from_record(suggestion)


@router.post(
    "/recurring-rules",
    response_model=RecurringRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un ingreso o gasto recurrente",
)
async def create_recurring_rule_route(
    payload: RecurringRuleCreate,
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
) -> RecurringRuleRead:
    """Spec 007, pasos 3 y 4; spec 002, RF-21: en la moneda de su cuenta."""
    record = await create_recurring_rule(payload.to_new_rule(), user_id, repository)
    return RecurringRuleRead.from_record(record)


@router.get(
    "/recurring-rules",
    response_model=list[RecurringRuleRead],
    summary="Los ingresos y gastos recurrentes",
)
async def get_recurring_rules_route(
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
) -> list[RecurringRuleRead]:
    """RF-29: los vigentes, el que vence primero arriba."""
    return [RecurringRuleRead.from_record(rule) for rule in await get_recurring_rules(user_id, repository)]


@router.patch(
    "/recurring-rules/{rule_id}",
    response_model=RecurringRuleRead,
    summary="Corrige un recurrente",
)
async def update_recurring_rule_route(
    rule_id: UUID,
    payload: RecurringRuleUpdate,
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
) -> RecurringRuleRead:
    """RF-30 y spec 002, RF-21: una cuenta de otra moneda, 422 `currency_mismatch`."""
    record = await update_recurring_rule(payload.to_changes(), rule_id, user_id, repository)
    return RecurringRuleRead.from_record(record)


@router.delete(
    "/recurring-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Da de baja un recurrente",
)
async def delete_recurring_rule_route(
    rule_id: UUID,
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
) -> Response:
    """RF-31: deja de vencer; los movimientos que ya registró se quedan."""
    await delete_recurring_rule(rule_id, user_id, repository)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/recurring-rules/{rule_id}/payments",
    response_model=RecurringPaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Marca un recurrente como pagado",
)
async def register_recurring_payment_route(
    rule_id: UUID,
    payload: RecurringPaymentCreate,
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
    idempotency: Annotated[IdempotentRequest, Depends(get_idempotent_request)],
) -> RecurringPaymentRead:
    """Spec 003, RF-17 a RF-19: registra el movimiento y avanza el vencimiento.

    Con `Idempotency-Key`, un reintento devuelve el mismo pago sin registrar otro.
    """
    stored = await idempotency.replay()
    if stored is not None:
        return RecurringPaymentRead.model_validate_json(stored)
    record = await register_recurring_payment(payload.to_payment(), rule_id, user_id, repository)
    response = RecurringPaymentRead.from_record(record)
    await idempotency.remember(response.model_dump_json())
    return response


@router.post(
    "/recurring-rules/{rule_id}/skip",
    response_model=RecurringRuleRead,
    summary="Omite una vez de un recurrente",
)
async def skip_recurring_occurrence_route(
    rule_id: UUID,
    user_id: User,
    repository: Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)],
) -> RecurringRuleRead:
    """Spec 003, RF-22: pasa al vencimiento siguiente sin registrar un movimiento."""
    record = await skip_recurring_occurrence(user_id, rule_id, repository)
    return RecurringRuleRead.from_record(record)
