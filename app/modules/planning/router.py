"""Endpoints de planning (spec 005, Can I Afford It?, y spec 009, presupuestos): HTTP, sin SQL ni reglas."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_current_user_id
from app.core.validation import CurrencyCode
from app.modules.finance.deps import get_safe_to_spend_reader
from app.modules.finance.domain.ports import SafeToSpendReader
from app.modules.planning.application.commands.create_budget import create_budget
from app.modules.planning.application.commands.delete_budget import delete_budget
from app.modules.planning.application.commands.update_budget import update_budget
from app.modules.planning.application.queries.check_affordability import check_affordability
from app.modules.planning.application.queries.get_budgets import get_budgets
from app.modules.planning.application.queries.get_forecast import get_forecast
from app.modules.planning.application.queries.get_what_if_base import get_what_if_base
from app.modules.planning.application.queries.simulate_what_if import simulate_what_if
from app.modules.planning.deps import (
    get_budget_repository,
    get_forecast_reader,
    get_planning_reader,
    get_what_if_base_reader,
)
from app.modules.planning.domain.ports import BudgetRepository, ForecastReader, PlanningReader, WhatIfBaseReader
from app.modules.planning.domain.what_if_base import PeriodType
from app.modules.planning.schemas import (
    AffordabilityCheckCreate,
    AffordabilityRead,
    BudgetCreate,
    BudgetRead,
    BudgetUpdate,
    ForecastRead,
    WhatIfBaseRead,
    WhatIfCreate,
    WhatIfRead,
)

router = APIRouter(tags=["planning"])
budgets_router = APIRouter(prefix="/budgets", tags=["planning"])

User = Annotated[UUID, Depends(get_current_user_id)]
Budgets = Annotated[BudgetRepository, Depends(get_budget_repository)]


@router.post("/affordability-checks", response_model=AffordabilityRead, summary="¿Me alcanza para esta compra?")
async def check_affordability_route(
    payload: AffordabilityCheckCreate,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    safe_to_spend: Annotated[SafeToSpendReader, Depends(get_safe_to_spend_reader)],
    planning: Annotated[PlanningReader, Depends(get_planning_reader)],
    reader: Annotated[ForecastReader, Depends(get_forecast_reader)],
) -> AffordabilityRead:
    """RF-11 a RF-19: 200 y no guarda nada. Es una estimación con sus supuestos."""
    result = await check_affordability(payload.to_check(), user_id, safe_to_spend, planning, reader)
    return AffordabilityRead.from_record(result)


@router.post("/what-if", response_model=WhatIfRead, summary="¿Qué pasa si…? Simula uno o dos cambios")
async def what_if_route(
    payload: WhatIfCreate,
    user_id: User,
    safe_to_spend: Annotated[SafeToSpendReader, Depends(get_safe_to_spend_reader)],
    planning: Annotated[PlanningReader, Depends(get_planning_reader)],
    reader: Annotated[ForecastReader, Depends(get_forecast_reader)],
) -> WhatIfRead:
    """Spec 009, RF-12 a RF-16: 200 y no guarda ni cambia nada. Es una estimación con sus supuestos."""
    changes = payload.to_changes()
    result = await simulate_what_if(payload.currency, changes, user_id, safe_to_spend, planning, reader)
    return WhatIfRead.from_record(result)


@router.get("/what-if/baseline", response_model=WhatIfBaseRead, summary="Lo de partida del simulador de What If?")
async def what_if_baseline_route(
    user_id: User,
    reader: Annotated[WhatIfBaseReader, Depends(get_what_if_base_reader)],
    currency: Annotated[CurrencyCode | None, Query(examples=["BOB"])] = None,
    period_type: Annotated[
        PeriodType | None, Query(description="Sin él, el que configuró el usuario", examples=["semi_monthly"])
    ] = None,
    on: Annotated[date | None, Query(description="Un día del periodo; sin él, hoy", examples=["2026-10-08"])] = None,
    account_id: Annotated[UUID | None, Query(description="Solo los movimientos de esa cuenta")] = None,
) -> WhatIfBaseRead:
    """Spec 009, RF-20 a RF-23: ingresos y gastos por categoría y el aporte a cada meta. No guarda nada."""
    base = await get_what_if_base(user_id, currency, period_type, on, account_id, reader)
    return WhatIfBaseRead.from_record(base)


@router.get("/forecast", response_model=ForecastRead, summary="El saldo proyectado a 30, 60 y 90 días")
async def forecast_route(
    user_id: User,
    safe_to_spend: Annotated[SafeToSpendReader, Depends(get_safe_to_spend_reader)],
    planning: Annotated[PlanningReader, Depends(get_planning_reader)],
    reader: Annotated[ForecastReader, Depends(get_forecast_reader)],
    currency: Annotated[CurrencyCode | None, Query(examples=["BOB"])] = None,
) -> ForecastRead:
    """Spec 010: en la moneda pedida o en la principal. Una estimación, nunca una recomendación."""
    return ForecastRead.from_record(await get_forecast(user_id, currency, safe_to_spend, planning, reader))


@budgets_router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED, summary="Crea un presupuesto")
async def create_budget_route(payload: BudgetCreate, user_id: User, budgets: Budgets) -> BudgetRead:
    """RF-1. Uno por categoría y moneda (409 `budget_exists`); el gratuito permite 3 (409 `plan_limit`)."""
    return BudgetRead.from_record(await create_budget(payload.to_new_budget(), user_id, budgets))


@budgets_router.get("", response_model=list[BudgetRead], summary="Los presupuestos del mes con su ritmo")
async def get_budgets_route(user_id: User, budgets: Budgets) -> list[BudgetRead]:
    """RF-3 a RF-7: lo gastado en el mes en curso y el Spending Pace de cada uno."""
    return [BudgetRead.from_record(budget) for budget in await get_budgets(user_id, budgets)]


@budgets_router.patch("/{budget_id}", response_model=BudgetRead, summary="Corrige el monto o los avisos")
async def update_budget_route(budget_id: UUID, payload: BudgetUpdate, user_id: User, budgets: Budgets) -> BudgetRead:
    """RF-2 y RF-18: el monto vale desde el mes en curso."""
    return BudgetRead.from_record(await update_budget(payload.to_changes(), budget_id, user_id, budgets))


@budgets_router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borra un presupuesto")
async def delete_budget_route(budget_id: UUID, user_id: User, budgets: Budgets) -> Response:
    """RF-2: los gastos no cambian."""
    await delete_budget(budget_id, user_id, budgets)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
