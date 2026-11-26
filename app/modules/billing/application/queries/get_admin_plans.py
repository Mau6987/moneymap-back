"""Casos de uso de lectura del panel de planes (MM-189)."""

from collections.abc import Sequence

from app.modules.billing.domain.models import AdminChange, AdminPlan
from app.modules.billing.domain.ports import AdminPlans


async def get_admin_plans(admin: AdminPlans) -> Sequence[AdminPlan]:
    """Del gratuito al más alto: datos, precios activos, cada funcionalidad y sus suscriptores."""
    return await admin.plans()


async def get_admin_changes(admin: AdminPlans, limit: int) -> Sequence[AdminChange]:
    """Los últimos cambios a planes, funcionalidades y precios, el más nuevo primero."""
    return await admin.changes(limit)
