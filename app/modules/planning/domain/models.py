"""Read models de Can I Afford It? (spec 005, RF-11 a RF-19): Python puro."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.money import Money
from app.modules.finance.domain.models import SafeToSpend

Verdict = Literal["affordable", "not_yet"]


@dataclass(frozen=True, slots=True)
class PurchaseCheck:
    """RF-11: la compra que se evalúa. No se guarda (RF-15)."""

    amount: Decimal
    currency: str
    category_id: UUID | None


@dataclass(frozen=True, slots=True)
class GoalPace:
    """Una meta: lo aportado en el periodo y a qué ritmo.

    El impacto se muestra como información ("si lo pagaras con tus metas"), no
    como una forma de pagar la compra.
    """

    goal_id: UUID
    name: str
    remaining: Decimal
    contributed_in_period: Decimal
    monthly_average: Decimal | None


@dataclass(frozen=True, slots=True)
class GoalPaces:
    """Las metas de la moneda, la de menor prioridad arriba, y el hoy del usuario."""

    today: date
    goals: list[GoalPace]


@dataclass(frozen=True, slots=True)
class GoalImpact:
    goal_id: UUID
    name: str
    amount: Money
    delay_months: int | None


@dataclass(frozen=True, slots=True)
class ProjectionPoint:
    """El saldo proyectado en una fecha: el punto de la curva de RF-14."""

    on: date
    balance: Money


@dataclass(frozen=True, slots=True)
class Affordability:
    """La respuesta de Can I Afford It?, calculada y nunca guardada (RF-15).

    `available` es lo que hay para la compra: Safe to Spend más los ingresos que
    faltan llegar en el periodo, menos el gasto variable que falta gastar.
    `available_after` es lo que queda después de la compra y puede ser negativo.
    `projection` es el saldo simulado desde hoy hasta `estimated_on`, uno por
    mes, para dibujar la curva: empieza en `available`, no en el saldo real.
    """

    verdict: Verdict
    amount: Money
    safe_to_spend: SafeToSpend
    income_in_period: Money
    remaining_variable_spending: Money
    available: Money
    goal_impacts: list[GoalImpact]
    monthly_income: Money
    monthly_expenses: Money
    monthly_goals: Money
    monthly_planned_savings: Money
    monthly_surplus: Money
    estimated_on: date | None
    projection: list[ProjectionPoint]
    limited_history: bool

    @property
    def available_after(self) -> Money:
        """Puede quedar negativo: todavía no alcanza (RF-14)."""
        return self.available - self.amount
