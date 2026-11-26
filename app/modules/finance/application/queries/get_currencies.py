"""Caso de uso de lectura: el selector de monedas (RF-2, RF-20)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.finance.domain.models import CurrencyOption
from app.modules.finance.domain.ports import CurrenciesRepository


async def get_currencies(user_id: UUID, currencies: CurrenciesRepository) -> Sequence[CurrencyOption]:
    """Mis monedas primero y después las demás activas.

    Una moneda desactivada en el catálogo deja de ofrecerse para datos nuevos,
    pero sale igual si el usuario ya tiene cuentas en ella: esas cuentas siguen
    registrando movimientos (RF-20).
    """
    return await currencies.options(user_id)
