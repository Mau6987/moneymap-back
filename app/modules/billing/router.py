"""Planes y suscripción (spec 011): solo HTTP, sin SQL ni reglas.

Ver docs/adr/001-monolito-modular-cqrs.md.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user_id
from app.modules.billing.application.commands.change_plan import change_plan
from app.modules.billing.application.queries.get_my_plan import get_my_plan
from app.modules.billing.application.queries.get_plans import get_plans
from app.modules.billing.deps import get_plan_reader, get_plan_writer
from app.modules.billing.domain.ports import PlanReader, PlanWriter
from app.modules.billing.schemas import MyPlanRead, PlanChange, PlanRead

router = APIRouter(tags=["billing"])

User = Annotated[UUID, Depends(get_current_user_id)]
Plans = Annotated[PlanReader, Depends(get_plan_reader)]
Writer = Annotated[PlanWriter, Depends(get_plan_writer)]


@router.get("/plans", response_model=list[PlanRead], summary="Los planes con sus precios y límites")
async def get_plans_route(plans: Plans) -> list[PlanRead]:
    """RF-1: del gratuito al más alto. Pide sesión, como el resto de la API."""
    return [PlanRead.from_record(plan) for plan in await get_plans(plans)]


@router.get("/me/plan", response_model=MyPlanRead, summary="El plan propio y cuánto lleva usado")
async def get_my_plan_route(user_id: User, plans: Plans) -> MyPlanRead:
    """RF-2: sin suscripción, el gratuito."""
    return MyPlanRead.from_record(await get_my_plan(user_id, plans))


@router.put("/me/plan", response_model=MyPlanRead, summary="Elige otro plan (sin cobro todavía)")
async def change_my_plan_route(payload: PlanChange, user_id: User, writer: Writer, plans: Plans) -> MyPlanRead:
    """RF-5 (MM-186): cambia al instante; al bajar, lo que ya existe queda. 404 si el plan no existe;
    409 `plan_managed_by_store` si la suscripción es de App Store o Play Store."""
    return MyPlanRead.from_record(await change_plan(payload.code, user_id, writer, plans))
