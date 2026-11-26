"""Puertos de planning: lo que la aplicación pide y la infraestructura implementa."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.modules.planning.domain.budgets import Budget, BudgetChanges, NewBudget
from app.modules.planning.domain.forecast import RecurringFlow
from app.modules.planning.domain.models import GoalPaces
from app.modules.planning.domain.what_if_base import BaseScope, PeriodType, WhatIfBase


class PlanningReader(Protocol):
    """Lecturas para Can I Afford It?: solo escribe el contador del plan (RF-15, MM-186)."""

    async def is_expense_category(self, user_id: UUID, category_id: UUID) -> bool: ...

    async def assert_amount(self, amount: Decimal, currency: str) -> None:
        """Más decimales que los de la moneda: la base responde `invalid_amount`."""
        ...

    async def goal_paces(self, user_id: UUID, currency: str, starts_on: date, ends_on: date) -> GoalPaces: ...

    async def consume_check(self, user_id: UUID) -> bool:
        """Cuenta una consulta contra el plan (MM-186). False si ya no le quedan este mes."""
        ...


class BudgetRepository(Protocol):
    """Los presupuestos del usuario (spec 009). None o False: no existe, está borrado o es de otro."""

    async def create(self, user_id: UUID, budget: NewBudget) -> Budget: ...

    async def list(self, user_id: UUID) -> Sequence[Budget]: ...

    async def update(self, user_id: UUID, budget_id: UUID, changes: BudgetChanges) -> Budget | None: ...

    async def soft_delete(self, user_id: UUID, budget_id: UUID) -> bool: ...


class ForecastReader(Protocol):
    """Lecturas del Financial Forecast (spec 010): nada escribe."""

    async def recurring(self, user_id: UUID, currency: str) -> list[RecurringFlow]: ...

    async def variable_spending(self, user_id: UUID, currency: str) -> tuple[date, Decimal, int]:
        """El hoy del usuario, el gasto variable por mes y cuántos meses completos entraron."""
        ...


class WhatIfBaseReader(Protocol):
    """Lecturas de la base del simulador de What If? (spec 009, RF-20 a RF-23): nada escribe."""

    async def scope(
        self, user_id: UUID, currency: str | None, period_type: PeriodType | None, on: date | None
    ) -> BaseScope | None:
        """El periodo y la moneda. None si el usuario todavía no tiene moneda principal."""
        ...

    async def has_account(self, user_id: UUID, account_id: UUID, currency: str) -> bool: ...

    async def base(self, user_id: UUID, scope: BaseScope, account_id: UUID | None) -> WhatIfBase: ...
