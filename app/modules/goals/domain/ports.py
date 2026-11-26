"""Puertos de las metas: lo que la aplicación pide y la infraestructura implementa."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.goals.domain.models import (
    ContributionRecord,
    GoalChanges,
    GoalMovement,
    GoalMovementCursor,
    GoalMovementFilters,
    GoalRecord,
    NewContribution,
    NewGoal,
)


class GoalRepository(Protocol):
    """Las metas del usuario. None o False: no existe, está borrada o es de otro."""

    async def create(self, user_id: UUID, goal: NewGoal) -> GoalRecord: ...

    async def list(self, user_id: UUID) -> Sequence[GoalRecord]: ...

    async def update(self, user_id: UUID, goal_id: UUID, changes: GoalChanges) -> GoalRecord | None: ...

    async def soft_delete(self, user_id: UUID, goal_id: UUID) -> bool: ...

    async def add_contribution(
        self, user_id: UUID, goal_id: UUID, contribution: NewContribution
    ) -> ContributionRecord | None: ...


class GoalMovementReader(Protocol):
    """REQ-056: los aportes y retiros del usuario, del más reciente al más viejo."""

    async def page(
        self,
        user_id: UUID,
        filters: GoalMovementFilters,
        after: GoalMovementCursor | None,
        limit: int,
    ) -> Sequence[GoalMovement]: ...
