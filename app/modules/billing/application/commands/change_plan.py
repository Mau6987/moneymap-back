"""Caso de uso de escritura: elegir otro plan, sin cobro (MM-186, spec 011 RF-5)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.billing.domain.models import MyPlan
from app.modules.billing.domain.ports import PlanReader, PlanWriter


async def change_plan(code: str, user_id: UUID, writer: PlanWriter, plans: PlanReader) -> MyPlan:
    """Deja al usuario en el plan `code` al instante y responde su plan nuevo.

    Al bajar de plan no se borra nada: lo que ya tiene queda y la base impide
    crear más hasta estar dentro del límite. Un plan que no existe: 404.
    """
    if not await writer.change(code):
        raise NotFound("Ese plan no existe o no se puede elegir")
    return await plans.my_plan(user_id)
