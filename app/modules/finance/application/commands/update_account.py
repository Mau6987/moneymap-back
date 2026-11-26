"""Caso de uso de escritura: corregir una cuenta (RF-14)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import AccountChanges, AccountRecord
from app.modules.finance.domain.ports import AccountRepository


async def update_account(
    changes: AccountChanges,
    account_id: UUID,
    user_id: UUID,
    accounts: AccountRepository,
) -> AccountRecord:
    """Corrige el nombre o la moneda de una cuenta, o la archiva y la desarchiva.

    Archivar la oculta, libera su cupo del plan y la saca de los totales; su
    historial queda. Desarchivar vuelve a contar para los límites (409 `plan_limit`).

    La moneda solo se puede corregir mientras la cuenta no se haya usado: si
    tiene movimientos o recurrentes, la base responde 409
    `account_currency_locked` y `core/errors.py` lo traduce.
    """
    updated = await accounts.update(user_id, account_id, changes)
    if updated is None:
        raise NotFound("La cuenta no existe")
    return updated
