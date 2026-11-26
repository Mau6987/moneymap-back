"""Caso de uso de escritura: corregir un presupuesto (spec 009, RF-2 y RF-18)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.planning.domain.budgets import Budget, BudgetChanges
from app.modules.planning.domain.ports import BudgetRepository


async def update_budget(changes: BudgetChanges, budget_id: UUID, user_id: UUID, budgets: BudgetRepository) -> Budget:
    """El monto vale desde el mes en curso: no se guarda historial de montos. También los avisos (RF-18)."""
    updated = await budgets.update(user_id, budget_id, changes)
    if updated is None:
        raise NotFound("El presupuesto no existe")
    return updated
