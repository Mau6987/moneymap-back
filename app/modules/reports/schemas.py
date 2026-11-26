"""Esquemas de los reportes (spec 004) y de la Money Story (spec 006). Los montos salen como texto (RF-12)."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.validation import MoneyAmount
from app.modules.reports.domain.models import FlowCategories, FlowGroup, MoneyFlow, MoneyStory


class PositionRead(BaseModel):
    """RF-1: la posición del Map en una moneda. `saved` son los aportes a metas."""

    currency: str
    period_starts_on: date
    period_ends_on: date
    available_balance: MoneyAmount
    income: MoneyAmount
    expenses: MoneyAmount
    saved: MoneyAmount

    @classmethod
    def from_record(cls, flow: MoneyFlow) -> "PositionRead":
        return cls(
            currency=flow.scope.currency,
            period_starts_on=flow.scope.starts_on,
            period_ends_on=flow.scope.ends_on,
            available_balance=flow.current_balance.amount,
            income=flow.income.amount,
            expenses=flow.expenses.amount,
            saved=flow.goals.amount,
        )


class MoneyFlowNodesRead(BaseModel):
    """RF-6 y RF-7: needs + lifestyle + goals + available = income."""

    income: MoneyAmount
    needs: MoneyAmount
    lifestyle: MoneyAmount
    goals: MoneyAmount
    available: MoneyAmount


class MoneyFlowRead(BaseModel):
    currency: str
    period_starts_on: date
    period_ends_on: date
    nodes: MoneyFlowNodesRead

    @classmethod
    def from_record(cls, flow: MoneyFlow) -> "MoneyFlowRead":
        return cls(
            currency=flow.scope.currency,
            period_starts_on=flow.scope.starts_on,
            period_ends_on=flow.scope.ends_on,
            nodes=MoneyFlowNodesRead(
                income=flow.income.amount,
                needs=flow.needs.amount,
                lifestyle=flow.lifestyle.amount,
                goals=flow.goals.amount,
                available=flow.available.amount,
            ),
        )


class FlowCategoryRead(BaseModel):
    """`category_id` y `name` en null: `sin_categoria`, las categorías borradas (RF-10)."""

    category_id: UUID | None
    name: str | None
    amount: MoneyAmount


class FlowCategoriesRead(BaseModel):
    currency: str
    period_starts_on: date
    period_ends_on: date
    group: FlowGroup
    items: list[FlowCategoryRead]

    @classmethod
    def from_record(cls, detail: FlowCategories) -> "FlowCategoriesRead":
        return cls(
            currency=detail.scope.currency,
            period_starts_on=detail.scope.starts_on,
            period_ends_on=detail.scope.ends_on,
            group=detail.group,
            items=[
                FlowCategoryRead(category_id=item.category_id, name=item.name, amount=item.amount.amount)
                for item in detail.items
            ],
        )


class StoryHighlightRead(BaseModel):
    """RF-4: `text` sale de la plantilla; `key` y `params` sirven para armarlo distinto en la app."""

    key: str
    params: dict[str, str]
    text: str


class StoryCategoryRead(BaseModel):
    name: str
    total: MoneyAmount


class StoryComparisonRead(BaseModel):
    """RF-2: el mes anterior en la misma moneda."""

    period: str = Field(examples=["2026-09"])
    income_total: MoneyAmount
    expense_total: MoneyAmount
    savings_total: MoneyAmount
    goals_contributed: MoneyAmount
    top_expense_category: StoryCategoryRead | None


class MoneyStoryRead(BaseModel):
    """RF-1 a RF-3. `savings_rate` es ahorro ÷ ingresos (0.7000 es 70 %); null sin ingresos."""

    currency: str
    period_starts_on: date
    period_ends_on: date
    income_total: MoneyAmount
    expense_total: MoneyAmount
    savings_total: MoneyAmount
    savings_rate: Decimal | None
    is_first_month: bool
    comparison: StoryComparisonRead | None
    highlights: list[StoryHighlightRead]
    generated_at: datetime | None

    @classmethod
    def from_record(cls, story: MoneyStory) -> "MoneyStoryRead":
        return cls.model_validate(
            {
                "currency": story.income.currency,
                "period_starts_on": story.starts_on,
                "period_ends_on": story.ends_on,
                "income_total": story.income.amount,
                "expense_total": story.expense.amount,
                "savings_total": story.savings.amount,
                "savings_rate": story.savings_rate,
                "is_first_month": story.comparison is None,
                "comparison": story.comparison,
                "highlights": [
                    {"key": line.key, "params": line.params, "text": line.text} for line in story.highlights
                ],
                "generated_at": story.generated_at,
            }
        )


class MoneyStoryMonthRead(BaseModel):
    """RF-5 a RF-7: una historia por moneda con movimientos. `period` en null si todavía no hay ninguna."""

    period: str | None = Field(examples=["2026-09"])
    items: list[MoneyStoryRead]

    @classmethod
    def from_record(cls, month: date | None, stories: Sequence[MoneyStory]) -> "MoneyStoryMonthRead":
        return cls(
            period=None if month is None else month.strftime("%Y-%m"),
            items=[MoneyStoryRead.from_record(story) for story in stories],
        )
