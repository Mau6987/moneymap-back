"""Caso de uso de escritura: borrar una meta (spec 005, RF-5)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.goals.domain.ports import GoalRepository


async def delete_goal(goal_id: UUID, user_id: UUID, goals: GoalRepository) -> None:
    """Borrado lógico: la meta y sus aportes dejan de contar. Ninguna cuenta cambia."""
    if not await goals.soft_delete(user_id, goal_id):
        raise NotFound("La meta no existe")
