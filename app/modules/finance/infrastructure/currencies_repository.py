"""El SQL del selector de monedas (RF-2, RF-19, RF-20, RF-28).

Mis monedas primero. Una moneda desactivada en el catálogo se deja de ofrecer,
salvo que el usuario ya la tenga entre las suyas: sus cuentas siguen existiendo
y tienen que poder registrar movimientos (RF-20).
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.domain.models import CurrencyOption

# COALESCE en is_main_currency: sin configuración todavía, la comparación es NULL.
_SELECT_OPTIONS = text(
    """
    SELECT currencies.code,
           currencies.name,
           currencies.symbol,
           currencies.decimals,
           currencies.is_active,
           (mine.currency IS NOT NULL) AS is_mine,
           coalesce(settings.main_currency = currencies.code, false) AS is_main_currency
    FROM catalog.currencies AS currencies
    LEFT JOIN finance.user_currencies AS mine
           ON mine.currency = currencies.code AND mine.user_id = :user_id
    LEFT JOIN finance.user_settings AS settings ON settings.user_id = :user_id
    WHERE (currencies.is_active OR mine.currency IS NOT NULL)
      AND (CAST(:code AS char(3)) IS NULL OR currencies.code = CAST(:code AS char(3)))
    ORDER BY (mine.currency IS NOT NULL) DESC, mine.sort_order, currencies.sort_order, currencies.code
    """
)

# El guard de la base rechaza una moneda desactivada o que no existe (RF-4).
_ADD_TO_MINE = text("SELECT finance.remember_currency(:user_id, :currency)")

# MM-186: Mis monedas respeta `finance.currencies` del plan. Una que ya está no
# cuenta (sumarla otra vez no cambia nada); sin límite (null), siempre entra.
_OVER_PLAN_LIMIT = text(
    """
    SELECT entitlements.limit_value IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM finance.user_currencies AS mine
               WHERE mine.user_id = :user_id AND mine.currency = :currency
           )
           AND (SELECT count(*) FROM finance.user_currencies AS mine WHERE mine.user_id = :user_id)
               >= entitlements.limit_value
    FROM billing.user_entitlements AS entitlements
    WHERE entitlements.user_id = :user_id AND entitlements.feature_key = 'finance.currencies'
    """
)

# El guard de la base impide quitar la principal o una con cuentas activas.
_DELETE_FROM_MINE = text(
    """
    DELETE FROM finance.user_currencies
    WHERE user_id = :user_id AND currency = :currency
    RETURNING currency
    """
)


class SqlCurrenciesRepository:
    """Implementa `CurrenciesRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def options(self, user_id: UUID) -> list[CurrencyOption]:
        rows = (await self._session.execute(_SELECT_OPTIONS, {"user_id": user_id, "code": None})).mappings().all()
        return [_to_currency_option(row) for row in rows]

    async def add_to_mine(self, user_id: UUID, currency: str) -> CurrencyOption:
        await self._session.execute(_ADD_TO_MINE, {"user_id": user_id, "currency": currency})
        params = {"user_id": user_id, "code": currency}
        return _to_currency_option((await self._session.execute(_SELECT_OPTIONS, params)).mappings().one())

    async def over_plan_limit(self, user_id: UUID, currency: str) -> bool:
        params = {"user_id": user_id, "currency": currency}
        return bool((await self._session.execute(_OVER_PLAN_LIMIT, params)).scalar_one_or_none())

    async def remove_from_mine(self, user_id: UUID, currency: str) -> bool:
        removed = (
            await self._session.execute(_DELETE_FROM_MINE, {"user_id": user_id, "currency": currency})
        ).scalar_one_or_none()
        return removed is not None


def _to_currency_option(row: RowMapping) -> CurrencyOption:
    return CurrencyOption(
        code=row["code"],
        name=row["name"],
        symbol=row["symbol"],
        decimals=row["decimals"],
        is_active=row["is_active"],
        is_mine=row["is_mine"],
        is_main_currency=row["is_main_currency"],
    )
