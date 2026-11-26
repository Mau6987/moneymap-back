"""What If? (spec 009, RF-12 a RF-15; PRD §6.19): Python puro.

Simula sobre el mismo motor de Safe to Spend y el ritmo de las metas que usa Can
I Afford It?, en una sola moneda. No guarda ni cambia nada.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.errors import NotFound
from app.core.money import Money
from app.modules.finance.domain.models import SafeToSpend
from app.modules.planning.domain.estimates import add_months, months_needed
from app.modules.planning.domain.models import GoalPaces

ChangeType = Literal["income", "recurring_expense", "category_spending", "goal_contribution", "planned_savings"]


@dataclass(frozen=True, slots=True)
class Change:
    """RF-13. `amount` es, según el tipo:

    - `income` y `recurring_expense`: cuánto sube (positivo) o baja (negativo) por mes.
    - `category_spending`: cuánto más (positivo) o menos (negativo) se gasta por mes
      en `category_id`. Mueve el dinero igual que un gasto fijo.
    - `goal_contribution`: el aporte mensual nuevo a `goal_id`.
    - `planned_savings`: el ahorro planificado nuevo del periodo.
    """

    type: ChangeType
    amount: Decimal
    goal_id: UUID | None = None
    category_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GoalOutcome:
    goal_id: UUID
    name: str
    estimated_completion: date | None
    estimated_completion_after: date | None

    @property
    def delay_months(self) -> int | None:
        """Positivo si se atrasa, negativo si se adelanta. None si alguna de las dos no tiene fecha."""
        if self.estimated_completion is None or self.estimated_completion_after is None:
            return None
        after, before = self.estimated_completion_after, self.estimated_completion
        return (after.year - before.year) * 12 + after.month - before.month


@dataclass(frozen=True, slots=True)
class WhatIf:
    safe_to_spend: SafeToSpend
    safe_to_spend_after: Money
    goals: list[GoalOutcome]
    monthly_savings: Money
    monthly_savings_after: Money
    # Para el Forecast con los cambios: lo que entra o sale de las cuentas por mes
    # (ingreso y gastos fijos) y el aporte mensual de cada meta.
    monthly_cash_change: Decimal
    goal_paces_after: dict[UUID, Decimal]


def simulate(available: SafeToSpend, paces: GoalPaces, changes: list[Change]) -> WhatIf:
    """RF-12 a RF-14.

    Cada cambio mueve Safe to Spend por su diferencia con lo de hoy. Si queda
    negativo, lo que falta sale de los aportes mensuales a metas, primero de la
    de menor prioridad (el orden de `paces`), como en Can I Afford It?.
    """
    decimals = available.current_balance.decimals
    pace = {goal.goal_id: goal.monthly_average or Decimal(0) for goal in paces.goals}
    pace_after = dict(pace)
    delta = Decimal(0)
    cash = Decimal(0)
    for change in changes:
        if change.type == "income":
            delta += change.amount
            cash += change.amount
        elif change.type in ("recurring_expense", "category_spending"):
            delta -= change.amount
            cash -= change.amount
        elif change.type == "planned_savings":
            delta -= change.amount - available.planned_savings.amount
        else:
            goal_id = change.goal_id
            if goal_id is None or goal_id not in pace_after:
                raise NotFound("La meta no existe o es de otra moneda")
            delta -= change.amount - pace_after[goal_id]
            pace_after[goal_id] = change.amount

    after = available.amount.amount + delta
    missing = -after
    for goal in paces.goals:
        if missing <= 0:
            break
        cut = min(missing, pace_after[goal.goal_id])
        pace_after[goal.goal_id] -= cut
        missing -= cut

    def estimate(remaining: Decimal, per_month: Decimal) -> date | None:
        months = months_needed(remaining, per_month)
        return None if months is None else add_months(paces.today, months)

    goals = [
        GoalOutcome(
            goal.goal_id,
            goal.name,
            estimate(goal.remaining, pace[goal.goal_id]),
            estimate(goal.remaining, pace_after[goal.goal_id]),
        )
        for goal in paces.goals
    ]
    return WhatIf(
        safe_to_spend=available,
        safe_to_spend_after=Money(after, available.currency, decimals),
        goals=goals,
        monthly_savings=Money(sum(pace.values(), Decimal(0)), available.currency, decimals),
        monthly_savings_after=Money(sum(pace_after.values(), Decimal(0)), available.currency, decimals),
        monthly_cash_change=cash,
        goal_paces_after=pace_after,
    )
