"""Caso de uso de lectura: los presupuestos del mes con su Spending Pace (spec 009, RF-3 a RF-7)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.planning.domain.budgets import Budget
from app.modules.planning.domain.ports import BudgetRepository


async def get_budgets(user_id: UUID, budgets: BudgetRepository) -> Sequence[Budget]:
    return await budgets.list(user_id)
