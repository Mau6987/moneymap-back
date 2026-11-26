"""Las cuentas de Can I Afford It? (spec 005, RF-11 a RF-14): Python puro.

El dinero disponible para una compra es el Safe to Spend más los ingresos
recurrentes que todavía faltan llegar en el periodo, menos el gasto variable que
falta gastar. El tiempo para juntarla sale de simular los meses que siguen con
los recurrentes en sus fechas, el gasto variable promedio, los aportes a metas y
el ahorro planificado. Nunca se convierte de otra moneda ni se suma una distinta.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.modules.planning.domain.estimates import add_months
from app.modules.planning.domain.forecast import RecurringFlow
from app.modules.planning.domain.models import GoalPace

# El gasto variable y el ahorro se miden por mes de 30 días, como en Forecast.
DAYS_PER_MONTH = Decimal(30)
MONTHS_PER_YEAR = 12
# A más de 5 años, "a este ritmo no se junta".
MAX_PROJECTION_MONTHS = 60


@dataclass(frozen=True, slots=True)
class MonthlyFlow:
    """Lo que entra y sale al mes en una sola moneda, sin contar el saldo."""

    income: Decimal
    recurring_expenses: Decimal
    variable_spending: Decimal
    goals: Decimal
    planned_savings: Decimal

    @property
    def expenses(self) -> Decimal:
        return self.recurring_expenses + self.variable_spending

    @property
    def surplus(self) -> Decimal:
        """Lo que sobra al mes después de todo. Puede ser negativo."""
        return self.income - self.expenses - self.goals - self.planned_savings


@dataclass(frozen=True, slots=True)
class AvailableForPurchase:
    """Cuánto hay para una compra y de dónde sale (RF-11)."""

    income_in_period: Decimal
    remaining_variable_spending: Decimal

    def total(self, safe_to_spend: Decimal) -> Decimal:
        return safe_to_spend + self.income_in_period - self.remaining_variable_spending


def income_in_period(recurring: list[RecurringFlow], today: date, starts_on: date, ends_on: date) -> Decimal:
    """Ingresos recurrentes que faltan llegar hasta el fin del periodo.

    Se excluyen los vencimientos anteriores a hoy: si el usuario ya los cobró sin
    marcarlos como pagados, contarlos otra vez inflaría el disponible.
    """
    first = max(today, starts_on)
    total = Decimal(0)
    for rule in recurring:
        if rule.kind != "income":
            continue
        for day in rule.occurrences(ends_on):
            if first <= day <= ends_on:
                total += rule.amount
    return total


def remaining_variable_spending(variable_monthly: Decimal, today: date, ends_on: date) -> Decimal:
    """La parte del gasto variable promedio que falta gastar en el periodo."""
    if today > ends_on:
        return Decimal(0)
    days_left = (ends_on - today).days + 1
    return variable_monthly * Decimal(days_left) / DAYS_PER_MONTH


def available_for_purchase(
    recurring: list[RecurringFlow], variable_monthly: Decimal, today: date, starts_on: date, ends_on: date
) -> AvailableForPurchase:
    return AvailableForPurchase(
        income_in_period=income_in_period(recurring, today, starts_on, ends_on),
        remaining_variable_spending=remaining_variable_spending(variable_monthly, today, ends_on),
    )


def monthly_flow(
    recurring: list[RecurringFlow],
    goals: list[GoalPace],
    variable_monthly: Decimal,
    planned_savings: Decimal,
    period_days: int,
    today: date,
) -> MonthlyFlow:
    """El ritmo mensual: el promedio de los recurrentes de los próximos 12 meses.

    Doce meses y no 30 días: así un seguro anual o un aguinaldo cuentan su parte
    en cada mes. `planned_savings` llega en cero para las monedas que no son la
    principal (RF-6 de la spec 003); se prorratea a 30 días porque el usuario lo
    define por periodo (semanal, quincenal o mensual).
    """
    until = add_months(today, MONTHS_PER_YEAR) - timedelta(days=1)
    income = Decimal(0)
    recurring_expenses = Decimal(0)
    for rule in recurring:
        for day in rule.occurrences(until):
            if day < today:
                continue
            if rule.kind == "income":
                income += rule.amount
            else:
                recurring_expenses += rule.amount

    monthly_planned = planned_savings * DAYS_PER_MONTH / Decimal(period_days) if period_days > 0 else Decimal(0)
    return MonthlyFlow(
        income=income / MONTHS_PER_YEAR,
        recurring_expenses=recurring_expenses / MONTHS_PER_YEAR,
        variable_spending=variable_monthly,
        goals=sum((max(goal.monthly_average or Decimal(0), Decimal(0)) for goal in goals), Decimal(0)),
        planned_savings=monthly_planned,
    )


@dataclass(frozen=True, slots=True)
class PurchaseProjection:
    """Cuándo se junta la compra y la curva mes a mes hasta ese día (RF-14)."""

    estimated_on: date | None
    points: list[tuple[date, Decimal]]


def project_purchase(
    recurring: list[RecurringFlow],
    available: Decimal,
    monthly_out: Decimal,
    today: date,
    ends_on: date,
    amount: Decimal,
) -> PurchaseProjection:
    """Simula día a día desde el fin del periodo hasta juntar `amount` (RF-14).

    Arranca en el disponible, que ya cuenta lo que entra y sale hasta `ends_on`:
    después de esa fecha suma y resta los recurrentes el día que vencen, y resta
    `monthly_out` (gasto variable, aportes a metas y ahorro planificado) de a un
    trigésimo por día. La fecha estimada es el primer día en que alcanza; la
    curva tiene un punto por mes desde hoy y cierra en ese día, sin repetir mes.
    A más de `MAX_PROJECTION_MONTHS`, no se junta: sin fecha ni curva.
    """
    horizon = add_months(today, MAX_PROJECTION_MONTHS)
    flows: dict[date, Decimal] = {}
    for rule in recurring:
        for day in rule.occurrences(horizon):
            if day > ends_on:
                flows[day] = flows.get(day, Decimal(0)) + (rule.amount if rule.kind == "income" else -rule.amount)

    daily_out = monthly_out / DAYS_PER_MONTH
    points: list[tuple[date, Decimal]] = [(today, available)]
    balance = available
    month = 1
    day = max(today, ends_on)
    while balance < amount:
        day += timedelta(days=1)
        if day > horizon:
            return PurchaseProjection(None, [])
        balance += flows.get(day, Decimal(0)) - daily_out
        if day >= add_months(today, month):
            points.append((day, balance))
            month += 1
    # La app y la web rotulan cada punto con su mes: si el día en que alcanza
    # cae en el mes del último punto mensual, lo reemplaza (hoy siempre queda).
    last = points[-1][0]
    if len(points) > 1 and (last.year, last.month) == (day.year, day.month):
        points[-1] = (day, balance)
    elif last != day:
        points.append((day, balance))
    return PurchaseProjection(day, points)
