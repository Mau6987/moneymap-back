"""Caso de uso de lectura: las metas del usuario (spec 005, RF-9)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.goals.domain.models import GoalRecord
from app.modules.goals.domain.ports import GoalRepository


async def get_goals(user_id: UUID, goals: GoalRepository) -> Sequence[GoalRecord]:
    """Todas, cada una en su moneda: nunca se suman entre sí."""
    return await goals.list(user_id)
