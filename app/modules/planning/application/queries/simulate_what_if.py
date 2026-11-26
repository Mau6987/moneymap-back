"""Caso de uso de lectura: What If? (spec 009, RF-12 a RF-16; PRD §6.19).

Se calcula en el momento sobre Safe to Spend y el Forecast (spec 010), y no
guarda nada. Todo en una sola moneda: nunca se convierte.
"""

from dataclasses import dataclass, replace
from uuid import UUID

from app.modules.finance.application.queries.get_safe_to_spend import get_safe_to_spend
from app.modules.finance.domain.ports import SafeToSpendReader
from app.modules.planning.application.queries.get_forecast import forecast_inputs
from app.modules.planning.domain.errors import ExpenseCategoryRequired
from app.modules.planning.domain.forecast import Forecast, GoalFlow, project
from app.modules.planning.domain.ports import ForecastReader, PlanningReader
from app.modules.planning.domain.what_if import Change, WhatIf, simulate


@dataclass(frozen=True, slots=True)
class WhatIfWithForecast:
    what_if: WhatIf
    forecast: Forecast
    forecast_after: Forecast


async def simulate_what_if(
    currency: str | None,
    changes: list[Change],
    user_id: UUID,
    safe_to_spend: SafeToSpendReader,
    planning: PlanningReader,
    reader: ForecastReader,
) -> WhatIfWithForecast:
    available = await get_safe_to_spend(user_id, currency, safe_to_spend)
    for change in changes:
        await planning.assert_amount(abs(change.amount), available.currency)
        if change.category_id is not None and not await planning.is_expense_category(user_id, change.category_id):
            raise ExpenseCategoryRequired()
    paces = await planning.goal_paces(user_id, available.currency, available.period_starts_on, available.period_ends_on)
    result = simulate(available, paces, changes)
    # PRD §6.19: también el Forecast a 30, 60 y 90 días, antes y después.
    inputs = await forecast_inputs(user_id, available, paces, reader)
    after = replace(
        inputs,
        extra_monthly=result.monthly_cash_change,
        goals=[GoalFlow(goal.goal_id, goal.remaining, result.goal_paces_after[goal.goal_id]) for goal in inputs.goals],
    )
    return WhatIfWithForecast(result, project(inputs), project(after))
