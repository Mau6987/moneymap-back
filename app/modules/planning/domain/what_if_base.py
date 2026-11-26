"""La base del simulador de What If? (spec 009, RF-17 a RF-20): Python puro, una sola moneda.

El simulador mueve montos en el cliente; acá solo están los montos de partida
de un periodo: lo que entró y salió por categoría y lo que se aporta a cada meta.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.money import Money

PeriodType = Literal["weekly", "semi_monthly", "monthly"]

# Cuántos periodos de cada tipo entran en un año: pasa el ritmo mensual de una meta al periodo.
PERIODS_PER_YEAR: dict[PeriodType, int] = {"weekly": 52, "semi_monthly": 24, "monthly": 12}


@dataclass(frozen=True, slots=True)
class BaseScope:
    """La moneda, el tipo de periodo y su rango (inclusive)."""

    currency: str
    decimals: int
    period_type: PeriodType
    starts_on: date
    ends_on: date


@dataclass(frozen=True, slots=True)
class BaseCategory:
    """Una categoría con movimientos en el periodo. Sin `category_id`: las borradas, juntas."""

    category_id: UUID | None
    name: str | None
    group: Literal["income", "needs", "lifestyle"]
    amount: Money


@dataclass(frozen=True, slots=True)
class BaseGoal:
    """Una meta activa de la moneda y su ritmo: el aporte mensual promedio (None sin aportes)."""

    goal_id: UUID
    name: str
    target_amount: Money
    current_amount: Money
    monthly_average: Decimal | None

    def period_contribution(self, period_type: PeriodType) -> Money:
        """El ritmo mensual pasado a un periodo: semanal × 12 / 52, quincenal ÷ 2."""
        monthly = self.monthly_average or Decimal(0)
        currency, decimals = self.target_amount.currency, self.target_amount.decimals
        return Money(monthly * 12 / PERIODS_PER_YEAR[period_type], currency, decimals)


@dataclass(frozen=True, slots=True)
class WhatIfBase:
    """Ingresos y gastos de mayor a menor, y las metas por prioridad."""

    scope: BaseScope
    account_id: UUID | None
    income: tuple[BaseCategory, ...]
    expenses: tuple[BaseCategory, ...]
    goals: tuple[BaseGoal, ...]
