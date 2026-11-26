"""Presupuestos y Spending Pace (spec 009, RF-1 a RF-9): Python puro.

El periodo es el mes calendario en la zona horaria del usuario. Lo gastado es lo
de la categoría en la moneda del presupuesto, sin conversión.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Literal
from uuid import UUID

from app.core.money import Money

PaceStatus = Literal["on_track", "a_bit_fast", "too_fast"]

# RF-7: los primeros 3 días la proyección todavía no sirve.
_DAYS_WITHOUT_PACE = 3
# RF-6: hasta 10 puntos por encima del mes es "un poco rápido".
_A_BIT_FAST = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class NewBudget:
    category_id: UUID
    amount: Decimal
    currency: str | None  # sin moneda, la principal
    alert_at_80: bool = True
    alert_at_100: bool = True


@dataclass(frozen=True, slots=True)
class BudgetChanges:
    """RF-2 y RF-18: None es "no se envió"."""

    amount: Decimal | None = None
    alert_at_80: bool | None = None
    alert_at_100: bool | None = None


@dataclass(frozen=True, slots=True)
class Pace:
    status: PaceStatus | None
    projected_total: Money


@dataclass(frozen=True, slots=True)
class Budget:
    id: UUID
    category_id: UUID
    category_name: str
    amount: Money
    spent: Money
    period_starts_on: date
    period_ends_on: date
    today: date
    daily: list[tuple[date, Money]] = field(default_factory=list)  # solo los días con gasto, en orden
    alert_at_80: bool = True
    alert_at_100: bool = True

    @property
    def remaining(self) -> Money:
        """Negativo si se pasó."""
        return self.amount - self.spent

    @property
    def percent_used(self) -> int:
        return int((self.spent.amount * 100 / self.amount.amount).to_integral_value(ROUND_FLOOR))

    @property
    def pace(self) -> Pace:
        """RF-6 y RF-7. Ritmo = gastado ÷ presupuesto − días transcurridos ÷ días del mes."""
        elapsed = (self.today - self.period_starts_on).days + 1
        days = (self.period_ends_on - self.period_starts_on).days + 1
        projected = Money(self.spent.amount / elapsed * days, self.spent.currency, self.spent.decimals)
        if elapsed <= _DAYS_WITHOUT_PACE:
            return Pace(None, projected)
        ahead = self.spent.amount / self.amount.amount - Decimal(elapsed) / days
        status: PaceStatus = "on_track" if ahead <= 0 else "a_bit_fast" if ahead <= _A_BIT_FAST else "too_fast"
        return Pace(status, projected)
