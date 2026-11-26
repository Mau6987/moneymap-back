"""Puertos de los avisos: lo que la aplicación pide y la infraestructura implementa."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notify.domain.models import Device, Inbox, NewDevice, NotificationSetting


class DeviceRepository(Protocol):
    """`iam.devices` no tiene RLS (spec 001): cada consulta filtra por `user_id` a mano."""

    async def register(self, user_id: UUID, device: NewDevice) -> Device: ...

    async def revoke(self, user_id: UUID, device_id: UUID) -> bool: ...


class SettingsRepository(Protocol):
    """Los ajustes de aviso del usuario (`notify.preferences`, con RLS)."""

    async def list(self, user_id: UUID) -> Sequence[NotificationSetting]: ...

    async def set(self, user_id: UUID, type_key: str, enabled: bool) -> bool:
        """False si el tipo no existe o no se puede apagar (RF-12)."""
        ...


class InboxRepository(Protocol):
    """Los avisos recibidos (`notify.notifications`, con RLS)."""

    async def page(self, user_id: UUID, before: datetime | None, limit: int) -> Inbox:
        """Del más nuevo al más viejo, los anteriores a `before`, y cuántos sin leer en total."""
        ...

    async def mark_all_read(self, user_id: UUID) -> None: ...
