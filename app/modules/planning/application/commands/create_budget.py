"""Caso de uso de escritura: crear un presupuesto (spec 009, RF-1).

La categoría ajena, borrada o de ingreso, la moneda desactivada, los decimales
de más, el presupuesto repetido y el límite del plan los responde la base.
"""

from uuid import UUID

from app.modules.planning.domain.budgets import Budget, NewBudget
from app.modules.planning.domain.ports import BudgetRepository


async def create_budget(budget: NewBudget, user_id: UUID, budgets: BudgetRepository) -> Budget:
    return await budgets.create(user_id, budget)
