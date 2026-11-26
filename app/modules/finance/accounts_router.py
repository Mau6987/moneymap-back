"""Cuentas y saldos por moneda (spec 002): solo HTTP, sin SQL ni reglas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_user_id
from app.modules.finance.application.commands.create_account import create_account
from app.modules.finance.application.commands.update_account import update_account
from app.modules.finance.application.queries.get_accounts import get_accounts
from app.modules.finance.application.queries.get_balances import get_balances
from app.modules.finance.deps import (
    get_account_repository,
    get_balances_reader,
)
from app.modules.finance.domain.ports import (
    AccountRepository,
    BalancesReader,
)
from app.modules.finance.schemas import (
    AccountCreate,
    AccountListItemRead,
    AccountRead,
    AccountUpdate,
    BalanceTotalRead,
)

router = APIRouter()

User = Annotated[UUID, Depends(get_current_user_id)]


@router.post(
    "/accounts",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crea una cuenta",
)
async def create_account_route(
    payload: AccountCreate,
    user_id: User,
    repository: Annotated[AccountRepository, Depends(get_account_repository)],
) -> AccountRead:
    """RF-3 a RF-5 y RF-9: el tipo, la moneda y los límites del plan los aplica la base."""
    record = await create_account(payload.to_new_account(), user_id, repository)
    return AccountRead.from_record(record)


@router.get(
    "/accounts",
    response_model=list[AccountListItemRead],
    summary="Las cuentas del usuario",
)
async def get_accounts_route(
    user_id: User,
    repository: Annotated[AccountRepository, Depends(get_account_repository)],
    archived: Annotated[bool, Query(description="true: solo las archivadas")] = False,
) -> list[AccountListItemRead]:
    """RF-23: las activas, la de por defecto primero; con `archived=true`, las archivadas."""
    records = await get_accounts(user_id, archived, repository)
    return [AccountListItemRead.from_record(record) for record in records]


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountRead,
    summary="Corrige una cuenta",
)
async def update_account_route(
    account_id: UUID,
    payload: AccountUpdate,
    user_id: User,
    repository: Annotated[AccountRepository, Depends(get_account_repository)],
) -> AccountRead:
    """RF-14: la moneda solo mientras la cuenta no se haya usado, o 409. `archived` la archiva o la desarchiva."""
    record = await update_account(payload.to_changes(), account_id, user_id, repository)
    return AccountRead.from_record(record)


@router.get(
    "/balances",
    response_model=list[BalanceTotalRead],
    summary="Totales por moneda",
)
async def get_balances_route(
    user_id: User,
    reader: Annotated[BalancesReader, Depends(get_balances_reader)],
) -> list[BalanceTotalRead]:
    """RF-15: una fila por moneda, la principal primero."""
    totals = await get_balances(user_id, reader)
    return [BalanceTotalRead.from_record(total) for total in totals]
