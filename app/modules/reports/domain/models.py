"""Read models de los reportes (spec 004): Python puro, una sola moneda cada uno."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.core.money import Money

# El grupo del detalle (RF-8): uno de gasto (catalog.flow_group) o los ingresos.
FlowGroup = Literal["income", "needs", "lifestyle"]


@dataclass(frozen=True, slots=True)
class ReportScope:
    """La moneda y el rango (inclusive) de un reporte."""

    currency: str
    decimals: int
    starts_on: date
    ends_on: date


@dataclass(frozen=True, slots=True)
class MoneyFlow:
    """Los nodos del Money Flow y el saldo de la moneda (RF-1 y RF-6)."""

    scope: ReportScope
    current_balance: Money
    income: Money
    needs: Money
    lifestyle: Money
    goals: Money

    @property
    def expenses(self) -> Money:
        return self.needs + self.lifestyle

    @property
    def available(self) -> Money:
        """RF-7: ingresos − Necesidades − Estilo de vida − Metas. Puede ser negativo."""
        return self.income - self.expenses - self.goals


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    """Una categoría del detalle. Sin `category_id` es `sin_categoria` (RF-10)."""

    category_id: UUID | None
    name: str | None
    amount: Money


@dataclass(frozen=True, slots=True)
class FlowCategories:
    """El detalle de un grupo (RF-8), de mayor a menor."""

    scope: ReportScope
    group: FlowGroup
    items: tuple[CategoryTotal, ...]


@dataclass(frozen=True, slots=True)
class StoryHighlight:
    """Una frase de la Money Story: su clave, sus parámetros y el texto ya armado (RF-4)."""

    key: str
    params: dict[str, str]
    text: str


@dataclass(frozen=True, slots=True)
class MoneyStory:
    """La Money Story guardada de un mes en una moneda (spec 006, RF-1 a RF-7)."""

    starts_on: date
    ends_on: date
    income: Money
    expense: Money
    savings: Money
    savings_rate: Decimal | None
    comparison: dict[str, Any] | None
    highlights: tuple[StoryHighlight, ...]
    generated_at: datetime | None
