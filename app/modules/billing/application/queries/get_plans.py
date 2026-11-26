"""Caso de uso de lectura: los planes para la pantalla Planes (spec 011, RF-1)."""

from collections.abc import Sequence

from app.modules.billing.domain.models import Plan
from app.modules.billing.domain.ports import PlanReader


async def get_plans(plans: PlanReader) -> Sequence[Plan]:
    return await plans.plans()
