"""El SQL de los aportes y retiros de las metas para Movimientos (REQ-056).

Pagina por cursor sobre `(contributed_on, id)`, como el historial de
movimientos. Entran también los de una meta borrada: el dinero salió o volvió
a la cuenta igual.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.goals.domain.models import GoalMovement, GoalMovementCursor, GoalMovementFilters

_SELECT_PAGE = text(
    """
    SELECT contributions.id, contributions.goal_id, goals.name AS goal_name, contributions.account_id,
           contributions.amount, contributions.contributed_on, contributions.created_at,
           goals.currency, currencies.decimals
    FROM goals.goal_contributions AS contributions
    JOIN goals.goals AS goals ON goals.user_id = contributions.user_id AND goals.id = contributions.goal_id
    JOIN catalog.currencies AS currencies ON currencies.code = goals.currency
    WHERE contributions.user_id = :user_id
      AND (CAST(:currency AS text) IS NULL OR goals.currency = CAST(:currency AS text))
      AND (CAST(:account_id AS uuid) IS NULL OR contributions.account_id = CAST(:account_id AS uuid))
      AND (CAST(:from_date AS date) IS NULL OR contributions.contributed_on >= CAST(:from_date AS date))
      AND (CAST(:to_date AS date) IS NULL OR contributions.contributed_on <= CAST(:to_date AS date))
      AND (CAST(:after_date AS date) IS NULL
           OR (contributions.contributed_on, contributions.id)
              < (CAST(:after_date AS date), CAST(:after_id AS uuid)))
    ORDER BY contributions.contributed_on DESC, contributions.id DESC
    LIMIT :limit
    """
)


class SqlGoalMovementReader:
    """Implementa `GoalMovementReader` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(
        self,
        user_id: UUID,
        filters: GoalMovementFilters,
        after: GoalMovementCursor | None,
        limit: int,
    ) -> Sequence[GoalMovement]:
        params = {
            "user_id": user_id,
            "currency": filters.currency,
            "account_id": filters.account_id,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "after_date": None if after is None else after.occurred_on,
            "after_id": None if after is None else after.id,
            "limit": limit,
        }
        rows = (await self._session.execute(_SELECT_PAGE, params)).mappings().all()
        return [_to_movement(row) for row in rows]


def _to_movement(row: Mapping[Any, Any]) -> GoalMovement:
    """Negativo en la base es un retiro; acá el monto va siempre positivo."""
    amount = row["amount"]
    return GoalMovement(
        id=row["id"],
        kind="contribution" if amount > 0 else "withdrawal",
        goal_id=row["goal_id"],
        goal_name=row["goal_name"],
        account_id=row["account_id"],
        amount=Money(abs(amount), row["currency"], row["decimals"]),
        occurred_on=row["contributed_on"],
        created_at=row["created_at"],
    )
