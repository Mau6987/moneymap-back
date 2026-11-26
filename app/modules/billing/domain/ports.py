"""Puertos de los planes: lo que la aplicación pide y la infraestructura implementa."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.modules.billing.domain.models import AdminChange, AdminPlan, MyPlan, Plan


class PlanReader(Protocol):
    async def plans(self) -> Sequence[Plan]:
        """Los públicos y activos, del gratuito al más alto."""
        ...

    async def my_plan(self, user_id: UUID) -> MyPlan: ...


class PlanWriter(Protocol):
    async def change(self, code: str) -> bool:
        """Cambia el plan del usuario de la sesión. False si el plan no existe."""
        ...


class AdminPlans(Protocol):
    """El panel de planes (MM-189). La base vuelve a mirar el rol en cada escritura."""

    async def is_admin(self) -> bool: ...

    async def plans(self) -> Sequence[AdminPlan]: ...

    async def update_plan(self, code: str, name: str, description: str | None, is_public: bool) -> bool:
        """False si el plan no existe."""
        ...

    async def set_feature(self, code: str, key: str, enabled: bool, limit: int | None) -> bool:
        """False si el plan o la funcionalidad no existen."""
        ...

    async def set_price(self, code: str, period: str, currency: str, amount: Decimal) -> bool:
        """False si el plan no existe."""
        ...

    async def changes(self, limit: int) -> Sequence[AdminChange]: ...
