"""Esquemas de planning: Can I Afford It? (spec 005) y presupuestos (spec 009). Los montos van como texto.

Acá se valida solo la forma. Los decimales de más y la moneda desactivada los
responde la base.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.money import Money
from app.core.validation import CurrencyCode, MoneyAmount
from app.modules.planning.application.queries.simulate_what_if import WhatIfWithForecast
from app.modules.planning.domain.budgets import Budget, BudgetChanges, NewBudget
from app.modules.planning.domain.forecast import Forecast
from app.modules.planning.domain.models import Affordability, PurchaseCheck
from app.modules.planning.domain.what_if import Change
from app.modules.planning.domain.what_if_base import PERIODS_PER_YEAR, BaseCategory, BaseGoal, PeriodType, WhatIfBase

# numeric(19,4), como los movimientos.
PurchaseAmount = Annotated[MoneyAmount, Field(gt=0, max_digits=19, decimal_places=4, examples=["800.00"])]


class AffordabilityCheckCreate(BaseModel):
    """RF-11: sin `category_id` se evalúa igual; con ella, tiene que ser de gasto."""

    amount: PurchaseAmount
    currency: CurrencyCode = Field(examples=["BOB"])
    category_id: UUID | None = None

    def to_check(self) -> PurchaseCheck:
        return PurchaseCheck(self.amount, self.currency, self.category_id)


class GoalImpactRead(BaseModel):
    goal_id: UUID
    name: str
    amount: MoneyAmount = Field(description="Lo que saldría de los aportes del periodo a esta meta")
    delay_months: int | None = Field(description="Cuántos meses se atrasa su fecha estimada. Null si no tiene ritmo")


class ProjectionPointRead(BaseModel):
    on: date
    balance: MoneyAmount = Field(description="El saldo proyectado ese día")


class AssumptionsRead(BaseModel):
    """Los supuestos del cálculo (constitución: una estimación, no un consejo)."""

    period_starts_on: date
    period_ends_on: date
    monthly_income: MoneyAmount = Field(description="Ingresos recurrentes al mes, promedio de los próximos 12 meses")
    monthly_expenses: MoneyAmount = Field(
        description="Gastos recurrentes (promedio de 12 meses) más el gasto variable promedio"
    )
    monthly_goals: MoneyAmount = Field(description="La suma de los aportes mensuales promedio a metas, hoy")
    monthly_planned_savings: MoneyAmount = Field(description="El ahorro planificado llevado a 30 días")
    monthly_surplus: MoneyAmount = Field(description="Lo que sobra al mes después de todo. Puede ser negativo")
    limited_history: bool = Field(description="Sin meses completos de historial: el gasto variable es una estimación")


class AffordabilityBreakdownRead(BaseModel):
    """Los cuatro conceptos del Safe to Spend, para explicar el disponible."""

    current_balance: MoneyAmount
    pending_recurring: MoneyAmount
    planned_savings: MoneyAmount
    goal_contributions: MoneyAmount


class AffordabilityRead(BaseModel):
    verdict: Literal["affordable", "not_yet"]
    currency: str
    amount: MoneyAmount
    safe_to_spend: MoneyAmount = Field(description="El Safe to Spend del periodo")
    breakdown: AffordabilityBreakdownRead = Field(description="De dónde sale el Safe to Spend")
    income_in_period: MoneyAmount = Field(description="Ingresos recurrentes que todavía faltan llegar en el periodo")
    remaining_variable_spending: MoneyAmount = Field(description="Gasto variable que falta gastar en el periodo")
    available: MoneyAmount = Field(description="Lo que hay para la compra: Safe to Spend + ingresos − gasto variable")
    available_after: MoneyAmount = Field(description="Después de la compra. Puede quedar negativo")
    goal_impacts: list[GoalImpactRead] = Field(description="Información: de dónde saldría si se pagara con las metas")
    estimated_on: date | None = Field(description="Solo con `not_yet`: el día en que se junta; null a más de 5 años")
    projection: list[ProjectionPointRead] = Field(
        description="El saldo simulado: hoy, uno por mes y `estimated_on`, para dibujar la curva"
    )
    assumptions: AssumptionsRead

    @classmethod
    def from_record(cls, result: Affordability) -> "AffordabilityRead":
        available = result.safe_to_spend
        return cls(
            verdict=result.verdict,
            currency=available.currency,
            amount=result.amount.amount,
            safe_to_spend=available.amount.amount,
            breakdown=AffordabilityBreakdownRead(
                current_balance=available.current_balance.amount,
                pending_recurring=available.pending_recurring.amount,
                planned_savings=available.planned_savings.amount,
                goal_contributions=available.goal_contributions.amount,
            ),
            income_in_period=result.income_in_period.amount,
            remaining_variable_spending=result.remaining_variable_spending.amount,
            available=result.available.amount,
            available_after=result.available_after.amount,
            goal_impacts=[
                GoalImpactRead(
                    goal_id=impact.goal_id,
                    name=impact.name,
                    amount=impact.amount.amount,
                    delay_months=impact.delay_months,
                )
                for impact in result.goal_impacts
            ],
            estimated_on=result.estimated_on,
            projection=[ProjectionPointRead(on=point.on, balance=point.balance.amount) for point in result.projection],
            assumptions=AssumptionsRead(
                period_starts_on=available.period_starts_on,
                period_ends_on=available.period_ends_on,
                monthly_income=result.monthly_income.amount,
                monthly_expenses=result.monthly_expenses.amount,
                monthly_goals=result.monthly_goals.amount,
                monthly_planned_savings=result.monthly_planned_savings.amount,
                monthly_surplus=result.monthly_surplus.amount,
                limited_history=result.limited_history,
            ),
        )


# numeric(19,4), como las metas.
BudgetAmount = Annotated[MoneyAmount, Field(gt=0, max_digits=19, decimal_places=4, examples=["400.00"])]


class BudgetCreate(BaseModel):
    """Spec 009, RF-1: una categoría de gasto. Sin `currency`, la moneda principal."""

    category_id: UUID
    amount: BudgetAmount
    currency: CurrencyCode | None = Field(default=None, examples=["BOB"])
    alert_at_80: bool = Field(default=True, description="RF-18: avisar al llegar al 80 %")
    alert_at_100: bool = Field(default=True, description="RF-18: avisar al pasar el 100 %")

    def to_new_budget(self) -> NewBudget:
        return NewBudget(self.category_id, self.amount, self.currency, self.alert_at_80, self.alert_at_100)


class BudgetUpdate(BaseModel):
    """RF-2 y RF-18: el monto y los avisos, solo lo que se envía. Para otra categoría o moneda se crea otro."""

    amount: BudgetAmount | None = None
    alert_at_80: bool | None = None
    alert_at_100: bool | None = None

    @model_validator(mode="after")
    def _something(self) -> "BudgetUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Mandá al menos un campo")
        return self

    def to_changes(self) -> BudgetChanges:
        return BudgetChanges(self.amount, self.alert_at_80, self.alert_at_100)


class PaceRead(BaseModel):
    status: Literal["on_track", "a_bit_fast", "too_fast"] | None = Field(description="Null los primeros 3 días del mes")
    projected_total: MoneyAmount = Field(description="Lo que se gastaría al cierre a este ritmo")


class BudgetDayRead(BaseModel):
    on: date
    spent: MoneyAmount = Field(description="Lo gastado ese día")
    cumulative: MoneyAmount = Field(description="Lo gastado desde el 1 del mes hasta ese día")


class BudgetRead(BaseModel):
    id: UUID
    category_id: UUID
    category_name: str
    currency: str
    amount: MoneyAmount
    spent: MoneyAmount = Field(description="Lo gastado en el mes en curso, solo en esta moneda")
    remaining: MoneyAmount = Field(description="Negativo si se pasó")
    percent_used: int = Field(description="Entero hacia abajo; puede pasar de 100")
    pace: PaceRead
    period_starts_on: date
    period_ends_on: date
    daily: list[BudgetDayRead] = Field(description="Solo los días con gasto, del 1 en adelante")
    alert_at_80: bool
    alert_at_100: bool

    @classmethod
    def from_record(cls, budget: Budget) -> "BudgetRead":
        pace = budget.pace
        daily: list[BudgetDayRead] = []
        cumulative = Decimal(0)
        for day, spent in budget.daily:
            cumulative += spent.amount
            daily.append(BudgetDayRead(on=day, spent=spent.amount, cumulative=cumulative))
        return cls(
            id=budget.id,
            category_id=budget.category_id,
            category_name=budget.category_name,
            currency=budget.amount.currency,
            amount=budget.amount.amount,
            spent=budget.spent.amount,
            remaining=budget.remaining.amount,
            percent_used=budget.percent_used,
            pace=PaceRead(status=pace.status, projected_total=pace.projected_total.amount),
            period_starts_on=budget.period_starts_on,
            period_ends_on=budget.period_ends_on,
            daily=daily,
            alert_at_80=budget.alert_at_80,
            alert_at_100=budget.alert_at_100,
        )


# What If? (spec 009, RF-12 a RF-16). Un cambio puede bajar: va con signo.
SignedAmount = Annotated[MoneyAmount, Field(max_digits=19, decimal_places=4, examples=["200.00"])]
NonNegativeAmount = Annotated[MoneyAmount, Field(ge=0, max_digits=19, decimal_places=4, examples=["300.00"])]


class IncomeChange(BaseModel):
    type: Literal["income"]
    monthly_change: SignedAmount = Field(description="Cuánto sube (positivo) o baja (negativo) el ingreso por mes")

    def to_change(self) -> Change:
        return Change("income", self.monthly_change)


class RecurringExpenseChange(BaseModel):
    type: Literal["recurring_expense"]
    monthly_change: SignedAmount = Field(description="Un gasto fijo nuevo (positivo) o uno que se quita (negativo)")

    def to_change(self) -> Change:
        return Change("recurring_expense", self.monthly_change)


class CategorySpendingChange(BaseModel):
    type: Literal["category_spending"]
    category_id: UUID = Field(description="Una categoría de gasto")
    monthly_change: SignedAmount = Field(description="Cuánto más (positivo) o menos (negativo) se gasta por mes")

    def to_change(self) -> Change:
        return Change("category_spending", self.monthly_change, category_id=self.category_id)


class GoalContributionChange(BaseModel):
    type: Literal["goal_contribution"]
    goal_id: UUID
    monthly_amount: NonNegativeAmount = Field(description="El aporte mensual nuevo a esa meta")

    def to_change(self) -> Change:
        return Change("goal_contribution", self.monthly_amount, self.goal_id)


class PlannedSavingsChange(BaseModel):
    type: Literal["planned_savings"]
    amount: NonNegativeAmount = Field(description="El ahorro planificado nuevo del periodo")

    def to_change(self) -> Change:
        return Change("planned_savings", self.amount)


ScenarioChange = Annotated[
    IncomeChange | RecurringExpenseChange | CategorySpendingChange | GoalContributionChange | PlannedSavingsChange,
    Field(discriminator="type"),
]


class WhatIfCreate(BaseModel):
    """RF-12 y RF-13: uno o dos cambios, en la moneda pedida o en la principal."""

    currency: CurrencyCode | None = Field(default=None, examples=["BOB"])
    changes: list[ScenarioChange] = Field(min_length=1, max_length=2)

    def to_changes(self) -> list[Change]:
        return [change.to_change() for change in self.changes]


class GoalOutcomeRead(BaseModel):
    goal_id: UUID
    name: str
    estimated_completion: date | None = Field(description="Hoy, al ritmo de sus aportes. Null sin ritmo")
    estimated_completion_after: date | None = Field(description="Con los cambios. Null si se queda sin ritmo")
    delay_months: int | None = Field(description="Positivo si se atrasa, negativo si se adelanta")


class WhatIfAssumptionsRead(BaseModel):
    """RF-15: los supuestos del cálculo. Es una estimación, no un consejo."""

    period_starts_on: date
    period_ends_on: date
    monthly_savings: MoneyAmount = Field(description="La suma de los aportes mensuales promedio a metas, hoy")
    monthly_savings_after: MoneyAmount = Field(description="La misma suma con los cambios")


class WhatIfForecastPointRead(BaseModel):
    days: Literal[30, 60, 90]
    on: date
    balance: MoneyAmount = Field(description="Hoy, sin los cambios")
    balance_after: MoneyAmount = Field(description="Con los cambios")


class WhatIfRead(BaseModel):
    currency: str
    safe_to_spend: MoneyAmount = Field(description="Hoy")
    safe_to_spend_after: MoneyAmount = Field(description="Con los cambios. Puede quedar negativo")
    goals: list[GoalOutcomeRead]
    forecast: list[WhatIfForecastPointRead] = Field(description="El Forecast a 30, 60 y 90 días, antes y después")
    goes_negative_on: date | None = Field(description="Cuándo bajaría de 0 sin los cambios")
    goes_negative_on_after: date | None = Field(description="Cuándo bajaría de 0 con los cambios")
    assumptions: WhatIfAssumptionsRead

    @classmethod
    def from_record(cls, record: WhatIfWithForecast) -> "WhatIfRead":
        result = record.what_if
        available = result.safe_to_spend
        return cls(
            currency=available.currency,
            safe_to_spend=available.amount.amount,
            safe_to_spend_after=result.safe_to_spend_after.amount,
            goals=[
                GoalOutcomeRead(
                    goal_id=goal.goal_id,
                    name=goal.name,
                    estimated_completion=goal.estimated_completion,
                    estimated_completion_after=goal.estimated_completion_after,
                    delay_months=goal.delay_months,
                )
                for goal in result.goals
            ],
            forecast=[
                WhatIfForecastPointRead(
                    days=before.days, on=before.on, balance=before.balance.amount, balance_after=after.balance.amount
                )
                for before, after in zip(record.forecast.points, record.forecast_after.points, strict=True)
            ],
            goes_negative_on=record.forecast.goes_negative_on,
            goes_negative_on_after=record.forecast_after.goes_negative_on,
            assumptions=WhatIfAssumptionsRead(
                period_starts_on=available.period_starts_on,
                period_ends_on=available.period_ends_on,
                monthly_savings=result.monthly_savings.amount,
                monthly_savings_after=result.monthly_savings_after.amount,
            ),
        )


class ForecastPointRead(BaseModel):
    """El saldo de ese día y, desde hoy hasta ese día, lo que entra y sale."""

    days: Literal[30, 60, 90]
    on: date
    balance: MoneyAmount = Field(description="El saldo proyectado ese día. Puede ser negativo")
    recurring_income: MoneyAmount
    recurring_expenses: MoneyAmount
    goal_contributions: MoneyAmount
    variable_spending: MoneyAmount


class ForecastAssumptionsRead(BaseModel):
    """Spec 010, RF-5: los supuestos que se muestran junto al gráfico."""

    recurring_income: MoneyAmount = Field(description="Los ingresos recurrentes esperados en los próximos 30 días")
    recurring_expenses: MoneyAmount = Field(description="Los gastos recurrentes esperados en los próximos 30 días")
    goal_contributions: MoneyAmount = Field(description="Lo que se aporta por mes a metas, al ritmo de hoy")
    variable_spending: MoneyAmount = Field(description="El gasto que no es recurrente, promedio por mes")
    history_months: int = Field(description="Cuántos meses completos entraron en el promedio (0 a 3)")


class ForecastRead(BaseModel):
    currency: str
    balance: MoneyAmount = Field(description="El saldo de hoy")
    points: list[ForecastPointRead]
    goes_negative_on: date | None = Field(description="Cuándo bajaría de 0. Null si no baja en 90 días")
    limited_history: bool = Field(description="Menos de un mes de datos: la estimación mejora con más historial")
    assumptions: ForecastAssumptionsRead

    @classmethod
    def from_record(cls, forecast: Forecast) -> "ForecastRead":
        return cls(
            currency=forecast.currency,
            balance=forecast.balance.amount,
            points=[
                ForecastPointRead(
                    days=point.days,
                    on=point.on,
                    balance=point.balance.amount,
                    recurring_income=point.recurring_income.amount,
                    recurring_expenses=point.recurring_expenses.amount,
                    goal_contributions=point.goal_contributions.amount,
                    variable_spending=point.variable_spending.amount,
                )
                for point in forecast.points
            ],
            goes_negative_on=forecast.goes_negative_on,
            limited_history=forecast.limited_history,
            assumptions=ForecastAssumptionsRead(
                recurring_income=forecast.recurring_income.amount,
                recurring_expenses=forecast.recurring_expenses.amount,
                goal_contributions=forecast.goal_contributions.amount,
                variable_spending=forecast.variable_monthly.amount,
                history_months=forecast.history_months,
            ),
        )


class WhatIfBaseCategoryRead(BaseModel):
    """`category_id` y `name` en null: Sin categoría, las categorías borradas juntas."""

    category_id: UUID | None
    name: str | None
    group: Literal["income", "needs", "lifestyle"]
    amount: MoneyAmount

    @classmethod
    def from_record(cls, item: BaseCategory) -> "WhatIfBaseCategoryRead":
        return cls(category_id=item.category_id, name=item.name, group=item.group, amount=item.amount.amount)


class WhatIfBaseGoalRead(BaseModel):
    goal_id: UUID
    name: str
    target_amount: MoneyAmount
    current_amount: MoneyAmount
    monthly_contribution: MoneyAmount | None = Field(
        description="El aporte mensual promedio (meses con aporte). Null si todavía no tiene aportes"
    )
    period_contribution: MoneyAmount = Field(description="Ese ritmo pasado al periodo pedido. Cero sin aportes")

    @classmethod
    def from_record(cls, goal: BaseGoal, period_type: PeriodType) -> "WhatIfBaseGoalRead":
        monthly = goal.monthly_average
        return cls(
            goal_id=goal.goal_id,
            name=goal.name,
            target_amount=goal.target_amount.amount,
            current_amount=goal.current_amount.amount,
            monthly_contribution=None
            if monthly is None
            else Money(monthly, goal.target_amount.currency, goal.target_amount.decimals).amount,
            period_contribution=goal.period_contribution(period_type).amount,
        )


class WhatIfBaseRead(BaseModel):
    """RF-20 a RF-23: lo de partida del simulador. No guarda nada."""

    currency: str
    period_type: PeriodType
    periods_per_year: int = Field(description="52, 24 o 12: pasa un monto del periodo a mensual")
    period_starts_on: date
    period_ends_on: date
    account_id: UUID | None
    income: list[WhatIfBaseCategoryRead] = Field(description="De mayor a menor")
    expenses: list[WhatIfBaseCategoryRead] = Field(description="Necesidades y Estilo de vida juntos, de mayor a menor")
    goals: list[WhatIfBaseGoalRead] = Field(description="Las activas de la moneda, por prioridad")

    @classmethod
    def from_record(cls, base: WhatIfBase) -> "WhatIfBaseRead":
        period_type = base.scope.period_type
        return cls(
            currency=base.scope.currency,
            period_type=period_type,
            periods_per_year=PERIODS_PER_YEAR[period_type],
            period_starts_on=base.scope.starts_on,
            period_ends_on=base.scope.ends_on,
            account_id=base.account_id,
            income=[WhatIfBaseCategoryRead.from_record(item) for item in base.income],
            expenses=[WhatIfBaseCategoryRead.from_record(item) for item in base.expenses],
            goals=[WhatIfBaseGoalRead.from_record(goal, period_type) for goal in base.goals],
        )
