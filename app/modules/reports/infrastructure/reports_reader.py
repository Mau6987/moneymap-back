"""El SQL de Map y Money Flow (spec 004).

Se apoya en `reports.category_totals` de la base, que ya deja afuera las
transferencias y los movimientos borrados (RF-9). Todo se filtra por una sola
moneda (RF-11 y RF-13): nunca se suman monedas distintas.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.reports.domain.models import CategoryTotal, FlowCategories, FlowGroup, MoneyFlow, ReportScope

# RF-4, igual que en Safe to Spend: con cuentas en una moneda desactivada, el
# reporte sigue funcionando; sin ellas, la moneda tiene que estar activa.
_ASSERT_CURRENCY = text(
    """
    SELECT catalog.assert_currency_active(:currency)
    WHERE NOT EXISTS (
        SELECT 1 FROM finance.accounts AS accounts
        WHERE accounts.user_id = :user_id AND accounts.currency = :currency AND accounts.deleted_at IS NULL)
    """
)

# RF-2 y RF-3: sin `month`, el periodo financiero que contiene `on` o, sin él,
# el "hoy" de su zona horaria (RF-17); sin `currency`, la principal.
_SELECT_SCOPE = text(
    """
    SELECT currencies.code AS currency, currencies.decimals,
           coalesce(CAST(:month AS date), period.starts_on) AS starts_on,
           coalesce((CAST(:month AS date) + INTERVAL '1 month')::date - 1, period.ends_on) AS ends_on
    FROM iam.users AS users
    LEFT JOIN finance.user_settings AS settings ON settings.user_id = users.id
    CROSS JOIN LATERAL finance.current_period(
        users.id, coalesce(CAST(:on AS date), (now() AT TIME ZONE users.timezone)::date)
    ) AS period
    JOIN catalog.currencies AS currencies
      ON currencies.code = coalesce(CAST(:currency AS char(3)), settings.main_currency)
    WHERE users.id = :user_id
    """
)

# El grupo sale del tipo de la categoría: la FK de finance.transactions obliga a
# que coincida con el del movimiento. Metas: los aportes del rango en esa moneda.
_SELECT_FLOW = text(
    """
    WITH totals AS (
        SELECT coalesce(totals.flow_group::text, 'income') AS node, sum(totals.total) AS total
        FROM reports.category_totals(:user_id, :starts_on, :ends_on) AS totals
        WHERE totals.currency = :currency
        GROUP BY 1
    )
    SELECT coalesce((SELECT total FROM totals WHERE node = 'income'), 0) AS income,
           coalesce((SELECT total FROM totals WHERE node = 'needs'), 0) AS needs,
           coalesce((SELECT total FROM totals WHERE node = 'lifestyle'), 0) AS lifestyle,
           coalesce((SELECT sum(contributions.amount)
                       FROM goals.goal_contributions AS contributions
                       JOIN goals.goals AS goals
                         ON goals.user_id = contributions.user_id AND goals.id = contributions.goal_id
                      WHERE contributions.user_id = :user_id AND goals.currency = :currency
                        AND goals.deleted_at IS NULL
                        AND contributions.contributed_on BETWEEN :starts_on AND :ends_on), 0) AS goals,
           coalesce((SELECT balances.total FROM finance.balance_totals AS balances
                      WHERE balances.user_id = :user_id AND balances.currency = :currency), 0) AS current_balance
    """
)

# RF-10: las categorías borradas se juntan en una sola fila sin id ni nombre.
_SELECT_CATEGORIES = text(
    """
    SELECT CASE WHEN categories.deleted_at IS NULL THEN categories.id END AS category_id,
           CASE WHEN categories.deleted_at IS NULL THEN categories.name END AS name,
           sum(totals.total) AS total
    FROM reports.category_totals(:user_id, :starts_on, :ends_on) AS totals
    JOIN finance.categories AS categories
      ON categories.user_id = :user_id AND categories.id = totals.category_id
    WHERE totals.currency = :currency AND coalesce(totals.flow_group::text, 'income') = :group
    GROUP BY 1, 2
    ORDER BY total DESC, name
    """
)


class SqlReportsReader:
    """Implementa `ReportsReader` sobre la sesión del usuario (con RLS, RF-15)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def money_flow(
        self, user_id: UUID, currency: str | None, month: date | None, on: date | None = None
    ) -> MoneyFlow | None:
        scope = await self._scope(user_id, currency, month, on)
        if scope is None:
            return None
        row = (await self._session.execute(_SELECT_FLOW, _params(user_id, scope))).mappings().one()

        def money(column: str) -> Money:
            return Money(row[column], scope.currency, scope.decimals)

        return MoneyFlow(
            scope=scope,
            current_balance=money("current_balance"),
            income=money("income"),
            needs=money("needs"),
            lifestyle=money("lifestyle"),
            goals=money("goals"),
        )

    async def flow_categories(
        self, user_id: UUID, currency: str | None, month: date | None, group: FlowGroup, on: date | None = None
    ) -> FlowCategories | None:
        scope = await self._scope(user_id, currency, month, on)
        if scope is None:
            return None
        params = {**_params(user_id, scope), "group": group}
        rows = (await self._session.execute(_SELECT_CATEGORIES, params)).mappings().all()
        items = tuple(
            CategoryTotal(row["category_id"], row["name"], Money(row["total"], scope.currency, scope.decimals))
            for row in rows
        )
        return FlowCategories(scope=scope, group=group, items=items)

    async def _scope(
        self, user_id: UUID, currency: str | None, month: date | None, on: date | None
    ) -> ReportScope | None:
        if currency is not None:
            await self._session.execute(_ASSERT_CURRENCY, {"user_id": user_id, "currency": currency})
        params = {"user_id": user_id, "currency": currency, "month": month, "on": on}
        row = (await self._session.execute(_SELECT_SCOPE, params)).mappings().one_or_none()
        if row is None:
            return None
        return ReportScope(row["currency"], row["decimals"], row["starts_on"], row["ends_on"])


def _params(user_id: UUID, scope: ReportScope) -> dict[str, object]:
    return {"user_id": user_id, "currency": scope.currency, "starts_on": scope.starts_on, "ends_on": scope.ends_on}
