"""Caso de uso de escritura: quitar una moneda de Mis monedas (RF-19)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.ports import CurrenciesRepository


async def remove_currency(currency: str, user_id: UUID, currencies: CurrenciesRepository) -> None:
    """Deja de ofrecer esa moneda en el selector.

    No toca ninguna cuenta. La base impide quitar la moneda principal o una con
    cuentas activas: responde 409 `currency_in_use` y `core/errors.py` lo traduce.
    """
    if not await currencies.remove_from_mine(user_id, currency):
        raise NotFound(f"La moneda {currency} no está en tus monedas")
