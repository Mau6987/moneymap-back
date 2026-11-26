"""El SQL del Financial Forecast (spec 010, RF-2 y RF-3). Solo lee.

El saldo sale de Safe to Spend y el ritmo de las metas de `PlanningReader`; acá
están los recurrentes vigentes y el gasto variable promedio, en una sola moneda.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.planning.domain.forecast import RecurringFlow

_SELECT_RECURRING = text(
    """
    SELECT categories.kind, rules.amount, rules.frequency, rules.start_date, rules.next_due_on, rules.end_date
    FROM finance.recurring_rules AS rules
    JOIN finance.categories AS categories ON categories.user_id = rules.user_id AND categories.id = rules.category_id
    WHERE rules.user_id = :user_id AND rules.currency = :currency AND rules.is_active AND rules.deleted_at IS NULL
      AND (rules.end_date IS NULL OR rules.next_due_on <= rules.end_date)
    ORDER BY rules.next_due_on, rules.id
    """
)

# RF-3: los gastos que no salen de un recurrente, de los últimos 3 meses completos
# que tengan movimientos. Sin ninguno, lo que va del mes llevado a 30 días.
_SELECT_VARIABLE = text(
    """
    WITH bounds AS (
        SELECT (now() AT TIME ZONE users.timezone)::date AS today,
               date_trunc('month', now() AT TIME ZONE users.timezone)::date AS month_start
        FROM iam.users AS users WHERE users.id = :user_id
    ), spending AS (
        SELECT date_trunc('month', transactions.occurred_on)::date AS month, sum(transactions.amount) AS total
        FROM finance.transactions AS transactions CROSS JOIN bounds
        WHERE transactions.user_id = :user_id AND transactions.currency = :currency
          AND transactions.kind = 'expense' AND transactions.deleted_at IS NULL
          AND transactions.recurring_rule_id IS NULL
          AND transactions.occurred_on >= bounds.month_start - INTERVAL '3 months'
          AND transactions.occurred_on <= bounds.today
        GROUP BY 1
    )
    SELECT bounds.today,
           (SELECT count(*) FROM spending WHERE month < bounds.month_start) AS history_months,
           coalesce((SELECT avg(total) FROM spending WHERE month < bounds.month_start),
                    (SELECT total FROM spending WHERE month = bounds.month_start)
                        / (bounds.today - bounds.month_start + 1) * 30,
                    0) AS variable_monthly
    FROM bounds
    """
)


class SqlForecastReader:
    """Implementa `ForecastReader` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recurring(self, user_id: UUID, currency: str) -> list[RecurringFlow]:
        rows = await self._session.execute(_SELECT_RECURRING, {"user_id": user_id, "currency": currency})
        return [
            RecurringFlow(
                row["kind"], row["amount"], row["frequency"], row["start_date"], row["next_due_on"], row["end_date"]
            )
            for row in rows.mappings()
        ]

    async def variable_spending(self, user_id: UUID, currency: str) -> tuple[date, Decimal, int]:
        """El hoy del usuario, el gasto variable por mes y cuántos meses completos entraron."""
        row = (await self._session.execute(_SELECT_VARIABLE, {"user_id": user_id, "currency": currency})).one()
        return row.today, Decimal(row.variable_monthly), int(row.history_months)
