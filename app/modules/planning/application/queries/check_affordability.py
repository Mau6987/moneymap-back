"""Caso de uso de lectura: Can I Afford It? (spec 005, RF-11 a RF-19; PRD §6.13).

Se calcula en el momento y no guarda nada (RF-15). Todo en la moneda de la
compra: nunca se convierte (RF-16).

El dinero disponible no es solo el saldo: suma los ingresos recurrentes que
todavía faltan llegar en el periodo y resta el gasto variable que falta gastar.
El tiempo para juntar lo que falta sale de simular los meses que siguen con los
recurrentes en sus fechas, no solo de los aportes a metas.
"""

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from app.core.errors import PlanLimitReached
from app.core.money import Money
from app.modules.finance.application.queries.get_safe_to_spend import get_safe_to_spend
from app.modules.finance.domain.ports import SafeToSpendReader
from app.modules.planning.application.queries.get_forecast import forecast_inputs
from app.modules.planning.domain.affordability import available_for_purchase, monthly_flow, project_purchase
from app.modules.planning.domain.errors import ExpenseCategoryRequired
from app.modules.planning.domain.estimates import months_needed
from app.modules.planning.domain.models import (
    Affordability,
    GoalImpact,
    GoalPace,
    GoalPaces,
    ProjectionPoint,
    PurchaseCheck,
    Verdict,
)
from app.modules.planning.domain.ports import ForecastReader, PlanningReader


async def check_affordability(
    check: PurchaseCheck,
    user_id: UUID,
    safe_to_spend: SafeToSpendReader,
    planning: PlanningReader,
    reader: ForecastReader,
) -> Affordability:
    """RF-12 a RF-14.

    1. Si la compra entra en el disponible, `affordable` con lo que queda.
    2. Si no, `not_yet` con cuánto falta y el día en que se junta al ritmo
       actual, o sin fecha sin sobrante positivo o si no se junta en 5 años.
    3. Las metas se muestran como información ("si lo pagaras con tus metas"),
       nunca como una forma de pagar.
    """
    if check.category_id is not None and not await planning.is_expense_category(user_id, check.category_id):
        raise ExpenseCategoryRequired()
    available = await get_safe_to_spend(user_id, check.currency, safe_to_spend)
    await planning.assert_amount(check.amount, available.currency)
    # MM-186: solo cuenta una consulta que pasó las validaciones.
    if not await planning.consume_check(user_id):
        raise PlanLimitReached(
            "planning.affordability_checks", "Ya usaste las consultas de Can I Afford It? de este mes en tu plan"
        )
    paces = await planning.goal_paces(user_id, available.currency, available.period_starts_on, available.period_ends_on)
    inputs = await forecast_inputs(user_id, available, paces, reader)
    decimals = available.current_balance.decimals

    def money(amount: Decimal) -> Money:
        return Money(amount, available.currency, decimals)

    today = inputs.today
    period_days = (available.period_ends_on - available.period_starts_on).days + 1
    flow = monthly_flow(
        inputs.recurring,
        paces.goals,
        inputs.variable_monthly,
        available.planned_savings.amount,
        period_days,
        today,
    )
    for_purchase = available_for_purchase(
        inputs.recurring,
        inputs.variable_monthly,
        today,
        available.period_starts_on,
        available.period_ends_on,
    )
    total_available = for_purchase.total(available.amount.amount)
    shortfall = check.amount - total_available
    verdict: Verdict
    impacts: list[GoalImpact]
    estimated_on = None
    projection: list[ProjectionPoint] = []
    if shortfall <= 0:
        verdict, impacts = "affordable", []
    else:
        verdict = "not_yet"
        # La fecha y la curva salen de la misma simulación, mes a mes. Sin
        # sobrante positivo no hay fecha: la app y la web dicen "tu ahorro sube
        # X al mes" con `monthly_surplus`, y un ingreso suelto no es un ritmo.
        if flow.surplus > 0:
            simulated = project_purchase(
                inputs.recurring,
                total_available,
                flow.variable_spending + flow.goals + flow.planned_savings,
                today,
                available.period_ends_on,
                check.amount,
            )
            estimated_on = simulated.estimated_on
            projection = [ProjectionPoint(on, money(balance)) for on, balance in simulated.points]
        # No se recomienda recortar: se informa de dónde saldría si lo hiciera.
        impacts = _goal_impacts(paces, shortfall, money)

    return Affordability(
        verdict=verdict,
        amount=money(check.amount),
        safe_to_spend=available,
        income_in_period=money(for_purchase.income_in_period),
        remaining_variable_spending=money(for_purchase.remaining_variable_spending),
        available=money(total_available),
        goal_impacts=impacts,
        monthly_income=money(flow.income),
        monthly_expenses=money(flow.expenses),
        monthly_goals=money(flow.goals),
        monthly_planned_savings=money(flow.planned_savings),
        monthly_surplus=money(flow.surplus),
        estimated_on=estimated_on,
        projection=projection,
        limited_history=inputs.history_months == 0,
    )


def _goal_impacts(paces: GoalPaces, shortfall: Decimal, money: Callable[[Decimal], Money]) -> list[GoalImpact]:
    """De dónde saldría lo que falta si se pagara con las metas: la de menor prioridad primero."""
    impacts: list[GoalImpact] = []
    left = shortfall
    for goal in paces.goals:
        if left <= 0:
            break
        cut = min(left, goal.contributed_in_period)
        if cut > 0:
            impacts.append(GoalImpact(goal.goal_id, goal.name, money(cut), _delay_months(goal, cut)))
            left -= cut
    return impacts


def _delay_months(goal: GoalPace, cut: Decimal) -> int | None:
    """Los meses de más hasta la fecha estimada de la meta (la de RF-10)."""
    before = months_needed(goal.remaining, goal.monthly_average)
    after = months_needed(goal.remaining + cut, goal.monthly_average)
    return None if before is None or after is None else after - before
