"""El SQL de `goals.goals` y `goals.goal_contributions` (spec 005, RF-1 a RF-10).

La base aplica las reglas: la moneda activa, los decimales del objetivo y de
cada aporte, el límite de metas del plan y la meta cumplida al llegar al
objetivo (migración 0007). `current_amount` lo mantiene el trigger de los
aportes: la API nunca lo escribe.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.goals.domain.models import ContributionRecord, GoalChanges, GoalRecord, NewContribution, NewGoal

_INSERT_GOAL = text(
    """
    INSERT INTO goals.goals (user_id, name, target_amount, currency, target_date, priority)
    VALUES (:user_id, :name, :target_amount, :currency, :target_date, :priority)
    RETURNING id
    """
)

# Las cumplidas y las archivadas también: la app decide cómo mostrarlas.
# RF-10: lo que falta entre el aporte mensual promedio, contando solo los meses
# con aporte, desde hoy en la zona del usuario. Solo las activas que avanzan;
# más de 100 años es no estimar.
_SELECT_GOALS = text(
    """
    SELECT goals.id, goals.name, goals.target_amount, goals.current_amount, goals.currency,
           goals.target_date, goals.priority, goals.status, currencies.decimals,
           CASE WHEN goals.status = 'active' AND pace.months_left <= 1200
                THEN ((now() AT TIME ZONE users.timezone)::date
                      + make_interval(months => pace.months_left::int))::date
           END AS estimated_completion,
           (now() AT TIME ZONE users.timezone)::date AS today,
           coalesce(settings.period_type::text, 'monthly') AS period_type
    FROM goals.goals AS goals
    JOIN catalog.currencies AS currencies ON currencies.code = goals.currency
    JOIN iam.users AS users ON users.id = goals.user_id
    LEFT JOIN finance.user_settings AS settings ON settings.user_id = goals.user_id
    LEFT JOIN LATERAL (
        SELECT ceil((goals.target_amount - goals.current_amount)
                    / nullif(sum(contributions.amount)
                             / count(DISTINCT date_trunc('month', contributions.contributed_on)), 0)) AS months_left
        FROM goals.goal_contributions AS contributions
        WHERE contributions.user_id = goals.user_id AND contributions.goal_id = goals.id
        HAVING sum(contributions.amount) > 0
    ) AS pace ON true
    WHERE goals.user_id = :user_id AND goals.deleted_at IS NULL
      AND (CAST(:goal_id AS uuid) IS NULL OR goals.id = :goal_id)
    ORDER BY goals.priority, goals.created_at, goals.id
    """
)

_UPDATE_GOAL = text(
    """
    UPDATE goals.goals AS goals
    SET name = coalesce(:name, goals.name),
        target_amount = coalesce(:target_amount, goals.target_amount),
        target_date = coalesce(:target_date, goals.target_date),
        priority = coalesce(:priority, goals.priority)
    WHERE goals.user_id = :user_id AND goals.id = :goal_id AND goals.deleted_at IS NULL
    RETURNING id
    """
)

_DELETE_GOAL = text(
    """
    UPDATE goals.goals SET deleted_at = now()
    WHERE user_id = :user_id AND id = :goal_id AND deleted_at IS NULL
    RETURNING id
    """
)

# Solo a una meta viva del usuario: si no, no inserta nada y la API responde 404.
_INSERT_CONTRIBUTION = text(
    """
    INSERT INTO goals.goal_contributions (user_id, goal_id, amount, account_id, contributed_on)
    SELECT goals.user_id, goals.id, :amount, :account_id,
           coalesce(CAST(:contributed_on AS date), (now() AT TIME ZONE users.timezone)::date)
    FROM goals.goals AS goals
    JOIN iam.users AS users ON users.id = goals.user_id
    WHERE goals.user_id = :user_id AND goals.id = :goal_id AND goals.deleted_at IS NULL
    RETURNING id, amount, contributed_on
    """
)


class SqlGoalRepository:
    """Implementa `GoalRepository` sobre la sesión del usuario (con RLS, RF-18)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, goal: NewGoal) -> GoalRecord:
        params = {
            "user_id": user_id,
            "name": goal.name,
            "target_amount": goal.target_amount,
            "currency": goal.currency,
            "target_date": goal.target_date,
            "priority": goal.priority,
        }
        created = (await self._session.execute(_INSERT_GOAL, params)).mappings().one()
        # Se relee como sale en la lista: trae el aporte sugerido por periodo.
        return await self._get(user_id, created["id"])

    async def list(self, user_id: UUID) -> Sequence[GoalRecord]:
        rows = await self._session.execute(_SELECT_GOALS, {"user_id": user_id, "goal_id": None})
        return [_to_goal(row) for row in rows.mappings()]

    async def update(self, user_id: UUID, goal_id: UUID, changes: GoalChanges) -> GoalRecord | None:
        params = {
            "user_id": user_id,
            "goal_id": goal_id,
            "name": changes.name,
            "target_amount": changes.target_amount,
            "target_date": changes.target_date,
            "priority": changes.priority,
        }
        if (await self._session.execute(_UPDATE_GOAL, params)).first() is None:
            return None
        # El objetivo nuevo cambia la fecha estimada: se relee como sale en la lista.
        return await self._get(user_id, goal_id)

    async def soft_delete(self, user_id: UUID, goal_id: UUID) -> bool:
        result = await self._session.execute(_DELETE_GOAL, {"user_id": user_id, "goal_id": goal_id})
        return result.first() is not None

    async def add_contribution(
        self, user_id: UUID, goal_id: UUID, contribution: NewContribution
    ) -> ContributionRecord | None:
        params = {
            "user_id": user_id,
            "goal_id": goal_id,
            "amount": contribution.amount,
            "contributed_on": contribution.contributed_on,
            "account_id": contribution.account_id,
        }
        created = (await self._session.execute(_INSERT_CONTRIBUTION, params)).mappings().one_or_none()
        if created is None:
            return None
        # Otra sentencia: el trigger AFTER ya actualizó la meta y esta la ve como quedó.
        goal = await self._get(user_id, goal_id)
        return ContributionRecord(
            id=created["id"],
            amount=Money(created["amount"], goal.target_amount.currency, goal.target_amount.decimals),
            contributed_on=created["contributed_on"],
            goal=goal,
        )

    async def _get(self, user_id: UUID, goal_id: UUID) -> GoalRecord:
        rows = await self._session.execute(_SELECT_GOALS, {"user_id": user_id, "goal_id": goal_id})
        return _to_goal(rows.mappings().one())


def _to_goal(row: Mapping[Any, Any]) -> GoalRecord:
    currency: str = row["currency"]
    decimals: int = row["decimals"]
    return GoalRecord(
        id=row["id"],
        name=row["name"],
        target_amount=Money(row["target_amount"], currency, decimals),
        current_amount=Money(row["current_amount"], currency, decimals),
        target_date=row["target_date"],
        priority=row["priority"],
        status=row["status"],
        estimated_completion=row["estimated_completion"],
        today=row["today"],
        period_type=row["period_type"],
    )
