"""Caso de uso de escritura: borrar un presupuesto (spec 009, RF-2)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.planning.domain.ports import BudgetRepository


async def delete_budget(budget_id: UUID, user_id: UUID, budgets: BudgetRepository) -> None:
    if not await budgets.soft_delete(user_id, budget_id):
        raise NotFound("El presupuesto no existe")
