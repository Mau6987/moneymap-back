"""Caso de uso de lectura: los totales por moneda (RF-15)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.finance.domain.models import BalanceTotal
from app.modules.finance.domain.ports import BalancesReader


async def get_balances(user_id: UUID, reader: BalancesReader) -> Sequence[BalanceTotal]:
    """Los totales por moneda, con la principal primero y sin sumar monedas distintas."""
    return await reader.totals(user_id)
