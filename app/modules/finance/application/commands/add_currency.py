"""Caso de uso de escritura: sumar una moneda a Mis monedas (RF-28)."""

from uuid import UUID

from app.core.errors import PlanLimitReached
from app.modules.finance.domain.models import CurrencyOption
from app.modules.finance.domain.ports import CurrenciesRepository


async def add_currency(currency: str, user_id: UUID, currencies: CurrenciesRepository) -> CurrencyOption:
    """La ofrece primero en el selector, sin crear ninguna cuenta.

    Repetirlo no cambia nada. Una moneda desactivada o que no existe la rechaza la
    base con 422 `currency_unavailable`. Desde MM-186 respeta el límite de monedas
    del plan: con el gratuito, Mis monedas tiene una sola (409 `plan_limit`).
    """
    if await currencies.over_plan_limit(user_id, currency):
        raise PlanLimitReached("finance.currencies", "Tu plan no permite sumar más monedas")
    return await currencies.add_to_mine(user_id, currency)
