"""Caso de uso de lectura: Financial Forecast a 30, 60 y 90 días (spec 010; PRD §6.18).

Una estimación, nunca una recomendación. En una sola moneda: nunca se convierte.
"""

from decimal import Decimal
from uuid import UUID

from app.modules.finance.application.queries.get_safe_to_spend import get_safe_to_spend
from app.modules.finance.domain.models import SafeToSpend
from app.modules.finance.domain.ports import SafeToSpendReader
from app.modules.planning.domain.forecast import Forecast, ForecastInputs, GoalFlow, project
from app.modules.planning.domain.models import GoalPaces
from app.modules.planning.domain.ports import ForecastReader, PlanningReader


async def forecast_inputs(
    user_id: UUID, available: SafeToSpend, paces: GoalPaces, reader: ForecastReader
) -> ForecastInputs:
    """Lo que necesita la proyección. What If? lo reusa y le cambia el ritmo de las metas."""
    code = available.currency
    today, variable_monthly, history_months = await reader.variable_spending(user_id, code)
    return ForecastInputs(
        currency=code,
        decimals=available.current_balance.decimals,
        today=today,
        balance=available.current_balance.amount,
        recurring=await reader.recurring(user_id, code),
        goals=[
            GoalFlow(goal.goal_id, goal.remaining, max(goal.monthly_average or Decimal(0), Decimal(0)))
            for goal in paces.goals
        ],
        variable_monthly=variable_monthly,
        history_months=history_months,
    )


async def get_forecast(
    user_id: UUID,
    currency: str | None,
    safe_to_spend: SafeToSpendReader,
    planning: PlanningReader,
    reader: ForecastReader,
) -> Forecast:
    available = await get_safe_to_spend(user_id, currency, safe_to_spend)
    paces = await planning.goal_paces(user_id, available.currency, available.period_starts_on, available.period_ends_on)
    return project(await forecast_inputs(user_id, available, paces, reader))
