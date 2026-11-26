"""El SQL de Can I Afford It? (spec 005, RF-11 a RF-19). Solo lee (RF-15)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.planning.domain.models import GoalPace, GoalPaces

_IS_EXPENSE_CATEGORY = text(
    """
    SELECT 1 FROM finance.categories
    WHERE user_id = :user_id AND id = :category_id AND kind = 'expense' AND deleted_at IS NULL
    """
)

# La misma regla de los movimientos y las metas (migraciones 0003 y 0007).
_ASSERT_AMOUNT = text("SELECT finance.assert_amount_decimals(:amount, :currency)")

# Las metas que Safe to Spend descuenta (las mismas condiciones que su SQL), la
# que se recorta primero arriba: la de menor prioridad y, entre iguales, la más
# nueva. El promedio es el de la fecha estimada de goals (RF-10): solo los meses
# con aporte.
_SELECT_PACES = text(
    """
    SELECT (now() AT TIME ZONE users.timezone)::date AS today,
           goals.id, goals.name,
           goals.target_amount - goals.current_amount AS remaining,
           coalesce(pace.in_period, 0) AS contributed_in_period,
           pace.monthly_average
    FROM iam.users AS users
    LEFT JOIN goals.goals AS goals
      ON goals.user_id = users.id AND goals.currency = :currency
     AND goals.deleted_at IS NULL AND goals.status NOT IN ('achieved', 'archived')
    LEFT JOIN LATERAL (
        SELECT sum(contributions.amount)
                   FILTER (WHERE contributions.contributed_on BETWEEN :starts_on AND :ends_on) AS in_period,
               sum(contributions.amount)
                   / nullif(count(DISTINCT date_trunc('month', contributions.contributed_on)), 0) AS monthly_average
        FROM goals.goal_contributions AS contributions
        WHERE contributions.user_id = goals.user_id AND contributions.goal_id = goals.id
    ) AS pace ON true
    WHERE users.id = :user_id
    ORDER BY goals.priority DESC, goals.created_at DESC, goals.id
    """
)


# MM-186: la consulta cuenta contra `planning.affordability_checks` del plan.
_CONSUME_CHECK = text("SELECT billing.try_consume(:user_id, 'planning.affordability_checks')")


class SqlPlanningReader:
    """Implementa `PlanningReader` sobre la sesión del usuario (con RLS, RF-18)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_expense_category(self, user_id: UUID, category_id: UUID) -> bool:
        params = {"user_id": user_id, "category_id": category_id}
        return (await self._session.execute(_IS_EXPENSE_CATEGORY, params)).first() is not None

    async def assert_amount(self, amount: Decimal, currency: str) -> None:
        await self._session.execute(_ASSERT_AMOUNT, {"amount": amount, "currency": currency})

    async def consume_check(self, user_id: UUID) -> bool:
        return bool((await self._session.execute(_CONSUME_CHECK, {"user_id": user_id})).scalar_one())

    async def goal_paces(self, user_id: UUID, currency: str, starts_on: date, ends_on: date) -> GoalPaces:
        params = {"user_id": user_id, "currency": currency, "starts_on": starts_on, "ends_on": ends_on}
        rows = (await self._session.execute(_SELECT_PACES, params)).mappings().all()
        goals = [
            GoalPace(row["id"], row["name"], row["remaining"], row["contributed_in_period"], row["monthly_average"])
            for row in rows
            if row["id"] is not None
        ]
        return GoalPaces(today=rows[0]["today"], goals=goals)
