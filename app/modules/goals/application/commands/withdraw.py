"""Caso de uso de escritura: sacar dinero de una meta a una cuenta (spec 005, RF-20)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.goals.domain.errors import NonPositiveContribution
from app.modules.goals.domain.models import ContributionRecord, NewContribution
from app.modules.goals.domain.ports import GoalRepository


async def withdraw(
    withdrawal: NewContribution, goal_id: UUID, user_id: UUID, goals: GoalRepository
) -> ContributionRecord:
    """Un aporte negativo: la base baja la meta, sube la cuenta y no deja sacar más de lo acumulado."""
    if withdrawal.amount <= 0:
        raise NonPositiveContribution()
    negative = NewContribution(-withdrawal.amount, withdrawal.contributed_on, withdrawal.account_id)
    created = await goals.add_contribution(user_id, goal_id, negative)
    if created is None:
        raise NotFound("La meta no existe")
    return created
