"""Casos de uso de escritura del panel de planes (MM-189).

Cada uno corrige una parte de un plan. La base valida el rol y las reglas (el
gratuito siempre visible y sin precio, límites no negativos) y audita el cambio.
Bajar un límite no borra nada de nadie.
"""

from decimal import Decimal

from app.core.errors import NotFound
from app.modules.billing.domain.ports import AdminPlans


async def update_plan(code: str, name: str, description: str | None, is_public: bool, admin: AdminPlans) -> None:
    """Nombre, descripción y si se muestra en Planes."""
    if not await admin.update_plan(code, name, description, is_public):
        raise NotFound("Ese plan no existe")


async def set_plan_feature(code: str, key: str, enabled: bool, limit: int | None, admin: AdminPlans) -> None:
    """Si el plan tiene la funcionalidad y con qué límite (None = ilimitado)."""
    if not await admin.set_feature(code, key, enabled, limit):
        raise NotFound("Ese plan o esa funcionalidad no existen")


async def set_plan_price(code: str, period: str, currency: str, amount: Decimal, admin: AdminPlans) -> None:
    """El precio mensual o anual en una moneda: el anterior se cierra, no se edita."""
    if not await admin.set_price(code, period, currency, amount):
        raise NotFound("Ese plan no existe")
