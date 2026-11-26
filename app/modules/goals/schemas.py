"""Esquemas de las metas (spec 005). Los montos van y vuelven como texto (RF-17).

Acá se valida solo la forma. El monto no positivo o con decimales de más, la
moneda desactivada y el límite del plan, si lo hay, los responde la base.
"""

import base64
import binascii
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.core.validation import CurrencyCode, MoneyAmount
from app.modules.goals.domain.errors import InvalidGoalMovementCursor
from app.modules.goals.domain.models import (
    ContributionRecord,
    GoalChanges,
    GoalMovement,
    GoalMovementCursor,
    GoalMovementPage,
    GoalRecord,
    NewContribution,
    NewGoal,
)
from app.modules.goals.domain.suggested_contribution import PeriodType

# Espejan los CHECK de goals.goals y numeric(19,4).
GOAL_NAME_MAX_LENGTH = 80
AMOUNT_MAX_DIGITS = 19
AMOUNT_MAX_DECIMALS = 4


def _clean_name(value: str) -> str:
    """Sin espacios de más y con al menos una letra o un número (BUG-006): "🏠" o "-" solos no."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("No puede quedar vacío")
    if not any(char.isalnum() for char in cleaned):
        raise ValueError("Tiene que tener al menos una letra o un número, no solo símbolos o emojis")
    return cleaned


GoalName = Annotated[
    str, Field(max_length=GOAL_NAME_MAX_LENGTH, examples=["Viaje a Cusco"]), AfterValidator(_clean_name)
]
GoalAmount = Annotated[
    MoneyAmount, Field(max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_MAX_DECIMALS, examples=["5000.00"])
]
# 1 es la más alta (CHECK de goals.goals.priority).
Priority = Annotated[int, Field(ge=1, le=5, examples=[1])]


class GoalCreate(BaseModel):
    """RF-1: empieza en cero. Sin `priority`, 3."""

    name: GoalName
    target_amount: GoalAmount
    currency: CurrencyCode = Field(examples=["BOB"])
    target_date: date | None = None
    priority: Priority = 3

    def to_new_goal(self) -> NewGoal:
        return NewGoal(self.name, self.target_amount, self.currency, self.target_date, self.priority)


class GoalUpdate(BaseModel):
    """RF-4: solo lo que se envía. La moneda no se cambia."""

    name: GoalName | None = None
    target_amount: GoalAmount | None = None
    target_date: date | None = None
    priority: Priority | None = None

    @model_validator(mode="after")
    def _something_changes(self) -> "GoalUpdate":
        if not self.model_fields_set:
            raise ValueError("Enviá al menos un campo")
        return self

    def to_changes(self) -> GoalChanges:
        return GoalChanges(self.name, self.target_amount, self.target_date, self.priority)


class GoalRead(BaseModel):
    id: UUID
    name: str
    target_amount: MoneyAmount
    current_amount: MoneyAmount
    currency: str
    target_date: date | None
    priority: int
    status: Literal["active", "paused", "achieved", "archived"]
    progress_percent: int = Field(description="De 0 a 100, entero hacia abajo")
    estimated_completion: date | None = Field(
        description="Cuándo llega al ritmo de sus aportes. Null sin aportes o si ya no está activa"
    )
    suggested_contribution: MoneyAmount | None = Field(
        description="Cuánto aportar en cada periodo de ahorro para llegar a `target_date`."
        " Null sin fecha, con la fecha vencida o si ya no está activa"
    )
    period_type: PeriodType = Field(description="El periodo de ahorro del usuario: al que corresponde ese aporte")

    @classmethod
    def from_record(cls, goal: GoalRecord) -> "GoalRead":
        suggested = goal.suggested_contribution
        return cls(
            id=goal.id,
            name=goal.name,
            target_amount=goal.target_amount.amount,
            current_amount=goal.current_amount.amount,
            currency=goal.target_amount.currency,
            target_date=goal.target_date,
            priority=goal.priority,
            status=goal.status,
            progress_percent=goal.progress_percent,
            estimated_completion=goal.estimated_completion,
            suggested_contribution=suggested.amount if suggested else None,
            period_type=goal.period_type,
        )


class ContributionCreate(BaseModel):
    """RF-6: en la moneda de la meta. Sin `contributed_on`, hoy."""

    amount: GoalAmount
    contributed_on: date | None = None
    account_id: UUID | None = Field(
        default=None, description="Cuenta de donde sale el aporte, en la moneda de la meta: baja su saldo"
    )

    def to_contribution(self) -> NewContribution:
        return NewContribution(self.amount, self.contributed_on, self.account_id)


class WithdrawalCreate(BaseModel):
    """RF-20: lo acumulado vuelve a una cuenta en la moneda de la meta. Sin `withdrawn_on`, hoy."""

    amount: GoalAmount
    account_id: UUID = Field(description="Cuenta a donde vuelve el dinero: sube su saldo")
    withdrawn_on: date | None = None

    def to_withdrawal(self) -> NewContribution:
        return NewContribution(self.amount, self.withdrawn_on, self.account_id)


class ContributionRead(BaseModel):
    id: UUID
    amount: MoneyAmount
    contributed_on: date


class ContributionCreatedRead(BaseModel):
    """El aporte y la meta como quedó: con su avance y, si llegó, cumplida."""

    contribution: ContributionRead
    goal: GoalRead

    @classmethod
    def from_record(cls, record: ContributionRecord) -> "ContributionCreatedRead":
        contribution = ContributionRead(id=record.id, amount=record.amount.amount, contributed_on=record.contributed_on)
        return cls(contribution=contribution, goal=GoalRead.from_record(record.goal))


# REQ-056: cuántos aportes y retiros trae una página si la app no lo pide.
GOAL_MOVEMENT_PAGE_DEFAULT_SIZE = 50
GOAL_MOVEMENT_PAGE_MAX_SIZE = 100


def encode_goal_movement_cursor(cursor: GoalMovementCursor) -> str:
    """El cursor viaja opaco: la app lo devuelve tal cual, sin interpretarlo."""
    return base64.urlsafe_b64encode(f"{cursor.occurred_on.isoformat()}_{cursor.id}".encode()).decode()


def decode_goal_movement_cursor(value: str) -> GoalMovementCursor:
    """El cursor que dio `encode_goal_movement_cursor`; otro texto es 422 `invalid_cursor`."""
    try:
        occurred_on, movement_id = base64.urlsafe_b64decode(value.encode()).decode().split("_")
        return GoalMovementCursor(occurred_on=date.fromisoformat(occurred_on), id=UUID(movement_id))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidGoalMovementCursor from error


class GoalMovementRead(BaseModel):
    """REQ-056: un aporte (`contribution`, salió de la cuenta) o un retiro (`withdrawal`, volvió a ella).

    `amount` va siempre positivo, en la moneda de la meta. `account_id` es null
    en los aportes de antes de que salieran de una cuenta.
    """

    id: UUID
    kind: Literal["contribution", "withdrawal"]
    goal_id: UUID
    goal_name: str
    account_id: UUID | None
    amount: MoneyAmount
    currency: str
    occurred_on: date
    created_at: datetime

    @classmethod
    def from_record(cls, movement: GoalMovement) -> "GoalMovementRead":
        return cls(
            id=movement.id,
            kind="contribution" if movement.kind == "contribution" else "withdrawal",
            goal_id=movement.goal_id,
            goal_name=movement.goal_name,
            account_id=movement.account_id,
            amount=movement.amount.amount,
            currency=movement.amount.currency,
            occurred_on=movement.occurred_on,
            created_at=movement.created_at,
        )


class GoalMovementPageRead(BaseModel):
    """Una página de aportes y retiros. Con `next_cursor` null, no hay más."""

    items: list[GoalMovementRead]
    next_cursor: str | None

    @classmethod
    def from_record(cls, page: GoalMovementPage) -> "GoalMovementPageRead":
        cursor = page.next_cursor
        return cls(
            items=[GoalMovementRead.from_record(item) for item in page.items],
            next_cursor=None if cursor is None else encode_goal_movement_cursor(cursor),
        )
