"""Caso de uso de escritura: crear una cuenta (RF-3)."""

from uuid import UUID

from app.modules.finance.domain.models import AccountRecord, NewAccount
from app.modules.finance.domain.ports import AccountRepository

# Espeja el CHECK de finance.cards.account_type: los datos de tarjeta (banco y
# últimos 4 dígitos) solo existen para ese tipo. Qué tipos son tarjeta lo
# responde catalog.account_types.is_card.
CARD_ACCOUNT_TYPE = "card"


async def create_account(account: NewAccount, user_id: UUID, repository: AccountRepository) -> AccountRecord:
    """Crea la cuenta y, si es una tarjeta, su banco y sus últimos 4 dígitos.

    No valida la moneda, el tipo ni los límites del plan: los aplica la base de
    datos (constitución §3) y `core/errors.py` traduce lo que devuelva.
    """
    created = await repository.insert(user_id, account)
    if account.type == CARD_ACCOUNT_TYPE:
        await repository.append_card(user_id, created.id, account.institution_code, account.last4)
    return created
