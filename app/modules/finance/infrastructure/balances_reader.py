"""El SQL de los totales por moneda (RF-15).

Lee la vista `finance.balance_totals`, que agrupa por moneda y nunca suma
monedas distintas. La principal va primero.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import BalanceTotal

_SELECT_TOTALS = text(
    """
    SELECT balances.currency,
           currencies.decimals,
           balances.is_main_currency,
           balances.total,
           balances.cash_total,
           balances.card_total,
           balances.accounts
    FROM finance.balance_totals AS balances
    JOIN catalog.currencies AS currencies ON currencies.code = balances.currency
    WHERE balances.user_id = :user_id
    ORDER BY balances.is_main_currency DESC, balances.currency
    """
)


class SqlBalancesReader:
    """Implementa `BalancesReader` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def totals(self, user_id: UUID) -> list[BalanceTotal]:
        rows = (await self._session.execute(_SELECT_TOTALS, {"user_id": user_id})).mappings().all()
        return [_to_balance_total(row) for row in rows]


def _to_balance_total(row: RowMapping) -> BalanceTotal:
    currency: str = row["currency"]
    decimals: int = row["decimals"]
    return BalanceTotal(
        currency=currency,
        is_main_currency=row["is_main_currency"],
        total=Money(row["total"], currency, decimals),
        cash_total=Money(row["cash_total"], currency, decimals),
        card_total=Money(row["card_total"], currency, decimals),
        accounts=row["accounts"],
    )
