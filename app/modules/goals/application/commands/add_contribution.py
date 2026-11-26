"""Caso de uso de escritura: aportar a una meta (spec 005, RF-6 a RF-8)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.goals.domain.errors import NonPositiveContribution
from app.modules.goals.domain.models import ContributionRecord, NewContribution
from app.modules.goals.domain.ports import GoalRepository


async def add_contribution(
    contribution: NewContribution, goal_id: UUID, user_id: UUID, goals: GoalRepository
) -> ContributionRecord:
    """El trigger suma el aporte a `current_amount` y, si llega al objetivo, la marca cumplida."""
    if contribution.amount <= 0:
        raise NonPositiveContribution()
    created = await goals.add_contribution(user_id, goal_id, contribution)
    if created is None:
        raise NotFound("La meta no existe")
    return created
