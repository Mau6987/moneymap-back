"""Endpoints de los reportes (spec 004) y de la Money Story (spec 006): HTTP, sin SQL ni reglas.

Ver docs/adr/001-monolito-modular-cqrs.md.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user_id
from app.core.validation import CurrencyCode
from app.modules.reports.application.queries.get_money_flow import get_flow_categories, get_money_flow
from app.modules.reports.application.queries.get_money_story import get_money_story
from app.modules.reports.deps import get_money_story_reader, get_reports_reader
from app.modules.reports.domain.models import FlowGroup
from app.modules.reports.domain.ports import MoneyStoryReader, ReportsReader
from app.modules.reports.schemas import FlowCategoriesRead, MoneyFlowRead, MoneyStoryMonthRead, PositionRead

router = APIRouter(prefix="/reports", tags=["reports"])
# Fuera de /reports porque así lo pide la spec 006 (RF-5).
money_story_router = APIRouter(prefix="/money-story", tags=["reports"])

User = Annotated[UUID, Depends(get_current_user_id)]
Reader = Annotated[ReportsReader, Depends(get_reports_reader)]
Currency = Annotated[CurrencyCode | None, Query(examples=["BOB"])]
# RF-5: AAAA-MM; otra forma es 422 `validation_error`.
Period = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-10"])]
# RF-17: el periodo financiero del usuario (semanal, quincenal o mensual) que contiene ese día.
On = Annotated[date | None, Query(description="Un día: el periodo financiero que lo contiene", examples=["2026-10-08"])]


def _month(period: str | None) -> date | None:
    return None if period is None else date.fromisoformat(f"{period}-01")


@router.get("/position", response_model=PositionRead, summary="Posición del mes en una moneda (Map)")
async def get_position_route(
    user_id: User, reader: Reader, period: Period = None, on: On = None, currency: Currency = None
) -> PositionRead:
    """Spec 004, RF-1 a RF-5: saldo disponible, ingresos, gastos y ahorrado."""
    return PositionRead.from_record(await get_money_flow(user_id, currency, _month(period), reader, on))


@router.get("/money-flow", response_model=MoneyFlowRead, summary="Recorrido del dinero por grupo")
async def get_money_flow_route(
    user_id: User, reader: Reader, period: Period = None, on: On = None, currency: Currency = None
) -> MoneyFlowRead:
    """Spec 004, RF-6 y RF-7: income = needs + lifestyle + goals + available."""
    return MoneyFlowRead.from_record(await get_money_flow(user_id, currency, _month(period), reader, on))


@router.get(
    "/money-flow/categories", response_model=FlowCategoriesRead, summary="Categorías de un grupo del Money Flow"
)
async def get_flow_categories_route(
    user_id: User,
    reader: Reader,
    group: FlowGroup,
    period: Period = None,
    on: On = None,
    currency: Currency = None,
) -> FlowCategoriesRead:
    """Spec 004, RF-8 y RF-10: de mayor a menor; las borradas, juntas sin id."""
    detail = await get_flow_categories(user_id, currency, _month(period), group, reader, on)
    return FlowCategoriesRead.from_record(detail)


@money_story_router.get("", response_model=MoneyStoryMonthRead, summary="La Money Story de un mes")
async def get_money_story_route(
    user_id: User,
    reader: Annotated[MoneyStoryReader, Depends(get_money_story_reader)],
    period: Period = None,
    currency: Currency = None,
) -> MoneyStoryMonthRead:
    """Spec 006, RF-5 a RF-7: una historia por moneda; sin `period`, el último mes cerrado."""
    month, stories = await get_money_story(user_id, _month(period), currency, reader)
    return MoneyStoryMonthRead.from_record(month, stories)
