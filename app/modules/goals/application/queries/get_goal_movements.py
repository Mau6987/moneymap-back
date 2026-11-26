"""Caso de uso de lectura: los aportes y retiros de las metas (REQ-056)."""

from uuid import UUID

from app.modules.goals.domain.errors import InvalidGoalMovementRange
from app.modules.goals.domain.models import GoalMovementCursor, GoalMovementFilters, GoalMovementPage
from app.modules.goals.domain.ports import GoalMovementReader


async def get_goal_movements(
    user_id: UUID,
    filters: GoalMovementFilters,
    after: GoalMovementCursor | None,
    limit: int,
    reader: GoalMovementReader,
) -> GoalMovementPage:
    """Una página, del más reciente al más viejo.

    Pide uno de más: si llega, hay otra página, que empieza después del último
    que se devuelve.
    """
    if filters.from_date and filters.to_date and filters.from_date > filters.to_date:
        raise InvalidGoalMovementRange()
    rows = await reader.page(user_id, filters, after, limit + 1)
    items = rows[:limit]
    if len(rows) <= limit:
        return GoalMovementPage(items=items, next_cursor=None)
    last = items[-1]
    return GoalMovementPage(items=items, next_cursor=GoalMovementCursor(occurred_on=last.occurred_on, id=last.id))
