"""Caso de uso de lectura: el plan del usuario y cuánto usó (spec 011, RF-2)."""

from uuid import UUID

from app.modules.billing.domain.models import MyPlan
from app.modules.billing.domain.ports import PlanReader


async def get_my_plan(user_id: UUID, plans: PlanReader) -> MyPlan:
    """Sin suscripción vigente, el gratuito con `status` `free`."""
    return await plans.my_plan(user_id)
