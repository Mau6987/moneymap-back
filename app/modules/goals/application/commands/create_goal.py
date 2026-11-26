"""Caso de uso de escritura: crear una meta (spec 005, RF-1 a RF-3)."""

from uuid import UUID

from app.modules.goals.domain.models import GoalRecord, NewGoal
from app.modules.goals.domain.ports import GoalRepository


async def create_goal(goal: NewGoal, user_id: UUID, goals: GoalRepository) -> GoalRecord:
    """La moneda desactivada, el monto no positivo o con decimales de más y el
    límite de metas del plan los rechaza la base (422 y 409 `plan_limit`)."""
    return await goals.create(user_id, goal)
