"""El SQL de la base del simulador de What If? (spec 009, RF-20 a RF-23). Solo lee.

Una sola moneda por consulta: nunca se suman monedas distintas. Los totales
siguen la regla de `reports.category_totals` (sin transferencias ni borrados),
con el filtro de cuenta que esa función no tiene.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.planning.domain.what_if_base import BaseCategory, BaseGoal, BaseScope, PeriodType, WhatIfBase

# Igual que los reportes: con cuentas en una moneda desactivada, sigue funcionando.
_ASSERT_CURRENCY = text(
    """
    SELECT catalog.assert_currency_active(:currency)
    WHERE NOT EXISTS (
        SELECT 1 FROM finance.accounts AS accounts
        WHERE accounts.user_id = :user_id AND accounts.currency = :currency AND accounts.deleted_at IS NULL)
    """
)

# RF-20: el periodo de `period_type` que contiene `on` (o el hoy del usuario). Si
# es el tipo que configuró, con su día de inicio; si no, desde el 1 (o el lunes).
_SELECT_SCOPE = text(
    """
    WITH cfg AS (
        SELECT users.id, users.timezone, settings.main_currency,
               coalesce(CAST(:period_type AS text), settings.period_type::text, 'monthly') AS period_type,
               settings.period_type::text AS own_type, settings.period_start_day AS own_day
        FROM iam.users AS users
        LEFT JOIN finance.user_settings AS settings ON settings.user_id = users.id
        WHERE users.id = :user_id
    )
    SELECT currencies.code AS currency, currencies.decimals, cfg.period_type,
           bounds.starts_on, bounds.ends_on
    FROM cfg
    CROSS JOIN LATERAL finance.period_bounds(
        CAST(cfg.period_type AS finance.period_type),
        CAST(CASE WHEN cfg.own_type = cfg.period_type THEN cfg.own_day ELSE 1 END AS smallint),
        coalesce(CAST(:on AS date), (now() AT TIME ZONE cfg.timezone)::date)
    ) AS bounds
    JOIN catalog.currencies AS currencies
      ON currencies.code = coalesce(CAST(:currency AS char(3)), cfg.main_currency)
    """
)

_ACCOUNT_IN_CURRENCY = text(
    """
    SELECT 1 FROM finance.accounts
    WHERE user_id = :user_id AND id = :account_id AND currency = :currency AND deleted_at IS NULL
    """
)

# RF-21: por categoría, de mayor a menor; las borradas juntas sin id (como RF-10 de la spec 004).
_SELECT_CATEGORIES = text(
    """
    SELECT CASE WHEN categories.deleted_at IS NULL THEN categories.id END AS category_id,
           CASE WHEN categories.deleted_at IS NULL THEN categories.name END AS name,
           coalesce(categories.flow_group::text, 'income') AS flow_group,
           sum(transactions.amount) AS total
    FROM finance.transactions AS transactions
    JOIN finance.categories AS categories
      ON categories.user_id = transactions.user_id AND categories.id = transactions.category_id
    WHERE transactions.user_id = :user_id AND transactions.currency = :currency
      AND transactions.occurred_on BETWEEN :starts_on AND :ends_on
      AND transactions.kind IN ('income', 'expense')
      AND transactions.deleted_at IS NULL
      AND (CAST(:account_id AS uuid) IS NULL OR transactions.account_id = :account_id)
    GROUP BY 1, 2, 3
    ORDER BY total DESC, name
    """
)

# RF-22: las metas activas de la moneda, por prioridad. El ritmo es el de la
# fecha estimada de goals: el promedio de los meses con aporte.
_SELECT_GOALS = text(
    """
    SELECT goals.id, goals.name, goals.target_amount, goals.current_amount,
           (SELECT sum(contributions.amount)
                   / nullif(count(DISTINCT date_trunc('month', contributions.contributed_on)), 0)
              FROM goals.goal_contributions AS contributions
             WHERE contributions.user_id = goals.user_id AND contributions.goal_id = goals.id
            HAVING sum(contributions.amount) > 0) AS monthly_average
    FROM goals.goals AS goals
    WHERE goals.user_id = :user_id AND goals.currency = :currency
      AND goals.deleted_at IS NULL AND goals.status = 'active'
    ORDER BY goals.priority, goals.created_at, goals.id
    """
)


class SqlWhatIfBaseReader:
    """Implementa `WhatIfBaseReader` sobre la sesión del usuario (con RLS, RF-16)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def scope(
        self, user_id: UUID, currency: str | None, period_type: PeriodType | None, on: date | None
    ) -> BaseScope | None:
        if currency is not None:
            await self._session.execute(_ASSERT_CURRENCY, {"user_id": user_id, "currency": currency})
        params = {"user_id": user_id, "currency": currency, "period_type": period_type, "on": on}
        row = (await self._session.execute(_SELECT_SCOPE, params)).mappings().one_or_none()
        if row is None:
            return None
        return BaseScope(row["currency"], row["decimals"], row["period_type"], row["starts_on"], row["ends_on"])

    async def has_account(self, user_id: UUID, account_id: UUID, currency: str) -> bool:
        params = {"user_id": user_id, "account_id": account_id, "currency": currency}
        return (await self._session.execute(_ACCOUNT_IN_CURRENCY, params)).first() is not None

    async def base(self, user_id: UUID, scope: BaseScope, account_id: UUID | None) -> WhatIfBase:
        params = {
            "user_id": user_id,
            "currency": scope.currency,
            "starts_on": scope.starts_on,
            "ends_on": scope.ends_on,
            "account_id": account_id,
        }
        rows = (await self._session.execute(_SELECT_CATEGORIES, params)).mappings().all()
        categories = [
            BaseCategory(
                row["category_id"], row["name"], row["flow_group"], Money(row["total"], scope.currency, scope.decimals)
            )
            for row in rows
        ]
        goal_params = {"user_id": user_id, "currency": scope.currency}
        goal_rows = (await self._session.execute(_SELECT_GOALS, goal_params)).mappings().all()
        goals = tuple(
            BaseGoal(
                row["id"],
                row["name"],
                Money(row["target_amount"], scope.currency, scope.decimals),
                Money(row["current_amount"], scope.currency, scope.decimals),
                row["monthly_average"],
            )
            for row in goal_rows
        )
        return WhatIfBase(
            scope=scope,
            account_id=account_id,
            income=tuple(c for c in categories if c.group == "income"),
            expenses=tuple(c for c in categories if c.group != "income"),
            goals=goals,
        )
