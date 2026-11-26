"""Financial Forecast a 30, 60 y 90 días (spec 010, RF-1 a RF-6; PRD §6.18): Python puro.

Saldo proyectado = saldo actual + ingresos recurrentes esperados − gastos
recurrentes esperados − aportes a metas − gasto variable promedio, en una sola
moneda. Se recorre día por día para saber en qué fecha bajaría de cero.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.money import Money
from app.modules.planning.domain.estimates import add_months

HORIZONS = (30, 60, 90)
# El gasto variable y los aportes son promedios por mes: se reparten en días de 30.
_DAYS_PER_MONTH = Decimal(30)


@dataclass(frozen=True, slots=True)
class RecurringFlow:
    """Un recurrente vigente: cuándo vence de nuevo y cada cuánto."""

    kind: Literal["income", "expense"]
    amount: Decimal
    frequency: Literal["weekly", "biweekly", "monthly", "yearly"]
    start_date: date
    next_due_on: date
    end_date: date | None

    def occurrences(self, until: date) -> list[date]:
        """Desde `next_due_on` (aunque ya haya pasado y siga pendiente) hasta `until`.

        Igual que `finance.next_occurrence`: cada fecha sale de `start_date`, no de
        la anterior, así el 31 vuelve a ser 31 después de un febrero.
        """
        last = until if self.end_date is None else min(until, self.end_date)
        dates: list[date] = []
        n = 0
        while True:
            day = self._nth(n)
            if day > last:
                return dates
            if day >= self.next_due_on:
                dates.append(day)
            n += 1

    def _nth(self, n: int) -> date:
        if self.frequency == "weekly":
            return self.start_date + timedelta(weeks=n)
        if self.frequency == "biweekly":
            return self.start_date + timedelta(weeks=2 * n)
        return add_months(self.start_date, n if self.frequency == "monthly" else 12 * n)


@dataclass(frozen=True, slots=True)
class GoalFlow:
    goal_id: UUID
    remaining: Decimal
    monthly: Decimal


@dataclass(frozen=True, slots=True)
class ForecastInputs:
    currency: str
    decimals: int
    today: date
    balance: Decimal
    recurring: list[RecurringFlow]
    goals: list[GoalFlow]
    variable_monthly: Decimal
    history_months: int  # meses completos de historial que entraron en el promedio (0 a 3)
    extra_monthly: Decimal = field(default=Decimal(0))  # What If?: lo que un cambio suma o resta por mes


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """El saldo de ese día y lo que entró y salió desde hoy hasta ese día."""

    days: int
    on: date
    balance: Money
    recurring_income: Money
    recurring_expenses: Money
    goal_contributions: Money
    variable_spending: Money


@dataclass(frozen=True, slots=True)
class Forecast:
    currency: str
    balance: Money
    points: list[ForecastPoint]
    goes_negative_on: date | None
    limited_history: bool
    recurring_income: Money  # lo esperado en los primeros 30 días
    recurring_expenses: Money
    goal_contributions: Money  # por mes
    variable_monthly: Money
    history_months: int


def project(inputs: ForecastInputs) -> Forecast:
    """RF-1 a RF-4: el saldo de cada día hasta 90 días, con los recurrentes en su fecha."""

    def money(amount: Decimal) -> Money:
        return Money(amount, inputs.currency, inputs.decimals)

    horizon = inputs.today + timedelta(days=max(HORIZONS))
    flows: dict[date, dict[str, Decimal]] = {}
    for rule in inputs.recurring:
        for day in rule.occurrences(horizon):
            # Un gasto vencido y pendiente cuenta hoy, como en Safe to Spend. Un
            # ingreso vencido no: si no se marcó recibido, no se sabe si llega
            # (pedido de QA, 2026-10-30), y sumarlo inflaba la proyección.
            if rule.kind == "income" and day < inputs.today:
                continue
            day_flows = flows.setdefault(max(day, inputs.today), {"income": Decimal(0), "expense": Decimal(0)})
            day_flows[rule.kind] += rule.amount

    # Lo acumulado desde hoy: el desglose de cada punto.
    totals = {"income": Decimal(0), "expense": Decimal(0), "goals": Decimal(0), "variable": Decimal(0)}

    def add_flows(day: date) -> None:
        for kind, amount in flows.get(day, {}).items():
            totals[kind] += amount

    goals_left = {goal.goal_id: goal.remaining for goal in inputs.goals}
    daily_variable = inputs.variable_monthly / _DAYS_PER_MONTH
    daily_extra = inputs.extra_monthly / _DAYS_PER_MONTH
    extra = Decimal(0)

    def balance() -> Decimal:
        return inputs.balance + totals["income"] - totals["expense"] - totals["goals"] - totals["variable"] + extra

    add_flows(inputs.today)
    negative_on = inputs.today if balance() < 0 else None
    points: list[ForecastPoint] = []
    for offset in range(1, max(HORIZONS) + 1):
        day = inputs.today + timedelta(days=offset)
        add_flows(day)
        totals["variable"] += daily_variable
        extra += daily_extra
        for goal in inputs.goals:
            contribution = min(goal.monthly / _DAYS_PER_MONTH, goals_left[goal.goal_id])
            if contribution > 0:
                goals_left[goal.goal_id] -= contribution
                totals["goals"] += contribution
        if negative_on is None and balance() < 0:
            negative_on = day
        if offset in HORIZONS:
            points.append(
                ForecastPoint(
                    days=offset,
                    on=day,
                    balance=money(balance()),
                    recurring_income=money(totals["income"]),
                    recurring_expenses=money(totals["expense"]),
                    goal_contributions=money(totals["goals"]),
                    variable_spending=money(totals["variable"]),
                )
            )

    return Forecast(
        currency=inputs.currency,
        balance=money(inputs.balance),
        points=points,
        goes_negative_on=negative_on,
        limited_history=inputs.history_months == 0,
        recurring_income=points[0].recurring_income,
        recurring_expenses=points[0].recurring_expenses,
        goal_contributions=money(sum((goal.monthly for goal in inputs.goals), Decimal(0))),
        variable_monthly=money(inputs.variable_monthly),
        history_months=inputs.history_months,
    )
