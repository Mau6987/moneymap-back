"""Read models y comandos de las metas (spec 005): Python puro."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.core.money import Money
from app.modules.goals.domain.suggested_contribution import PeriodType, suggested_contribution


@dataclass(frozen=True, slots=True)
class NewGoal:
    """RF-1: la meta empieza en cero; `current_amount` lo mantiene la base."""

    name: str
    target_amount: Decimal
    currency: str
    target_date: date | None
    priority: int


@dataclass(frozen=True, slots=True)
class GoalChanges:
    """RF-4: None es "no cambia". La moneda no se cambia: los aportes van en ella."""

    name: str | None
    target_amount: Decimal | None
    target_date: date | None
    priority: int | None


@dataclass(frozen=True, slots=True)
class GoalRecord:
    id: UUID
    name: str
    target_amount: Money
    current_amount: Money
    target_date: date | None
    priority: int
    status: str
    estimated_completion: date | None
    today: date
    period_type: PeriodType

    @property
    def suggested_contribution(self) -> Money | None:
        """RF-23: cuánto aportar por periodo para llegar a `target_date`. Solo las activas."""
        if self.status != "active":
            return None
        remaining = self.target_amount.amount - self.current_amount.amount
        amount = suggested_contribution(remaining, self.today, self.target_date, self.period_type)
        if amount is None:
            return None
        return Money(amount, self.target_amount.currency, self.target_amount.decimals)

    @property
    def progress_percent(self) -> int:
        """RF-9: 2500 de 5000 es 50. Entero hacia abajo y como máximo 100."""
        if self.current_amount.amount <= 0:
            return 0
        return min(int(self.current_amount.amount * 100 // self.target_amount.amount), 100)


@dataclass(frozen=True, slots=True)
class NewContribution:
    """RF-6: sin fecha, hoy en la zona horaria del usuario. Negativo es un retiro.

    Con `account_id`, el aporte sale de esa cuenta y el retiro vuelve a ella.
    """

    amount: Decimal
    contributed_on: date | None
    account_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ContributionRecord:
    """El aporte y la meta como quedó después del trigger."""

    id: UUID
    amount: Money
    contributed_on: date
    goal: GoalRecord


@dataclass(frozen=True, slots=True)
class GoalMovementFilters:
    """REQ-056: los filtros del historial de Movimientos; None es "todos"."""

    currency: str | None = None
    account_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None


@dataclass(frozen=True, slots=True)
class GoalMovementCursor:
    """Dónde sigue la lista: el último aporte o retiro de la página anterior."""

    occurred_on: date
    id: UUID


@dataclass(frozen=True, slots=True)
class GoalMovement:
    """REQ-056: un aporte (sale de `account_id`) o un retiro (vuelve a ella).

    `amount` es siempre positivo; `kind` dice hacia dónde va. La meta puede
    estar borrada: el dinero igual se movió y el historial lo muestra.
    """

    id: UUID
    kind: str
    goal_id: UUID
    goal_name: str
    account_id: UUID | None
    amount: Money
    occurred_on: date
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GoalMovementPage:
    """Una página; sin `next_cursor`, no hay más."""

    items: Sequence[GoalMovement]
    next_cursor: GoalMovementCursor | None
