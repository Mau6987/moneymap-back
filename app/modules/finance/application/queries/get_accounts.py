"""Caso de uso de lectura: las cuentas del usuario (RF-23)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.finance.domain.models import AccountRecord
from app.modules.finance.domain.ports import AccountRepository


async def get_accounts(user_id: UUID, archived: bool, accounts: AccountRepository) -> Sequence[AccountRecord]:
    """Las activas, la de por defecto primero, o solo las archivadas; las tarjetas con banco y últimos 4."""
    return await accounts.list(user_id, archived)
