"""Caso de uso de escritura: corregir una meta (spec 005, RF-4)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.goals.domain.models import GoalChanges, GoalRecord
from app.modules.goals.domain.ports import GoalRepository


async def update_goal(changes: GoalChanges, goal_id: UUID, user_id: UUID, goals: GoalRepository) -> GoalRecord:
    """Solo lo enviado. Bajar el objetivo hasta lo ahorrado la deja cumplida (lo hace la base)."""
    updated = await goals.update(user_id, goal_id, changes)
    if updated is None:
        raise NotFound("La meta no existe")
    return updated
