"""Endpoints de los avisos (spec 006): HTTP, sin SQL ni reglas.

Ver docs/adr/001-monolito-modular-cqrs.md.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_current_user_id
from app.modules.notify.application.commands.mark_inbox_read import mark_inbox_read
from app.modules.notify.application.commands.register_device import register_device
from app.modules.notify.application.commands.revoke_device import revoke_device
from app.modules.notify.application.commands.update_settings import update_settings
from app.modules.notify.application.queries.get_inbox import get_inbox
from app.modules.notify.application.queries.get_settings import get_settings
from app.modules.notify.deps import get_device_repository, get_inbox_repository, get_settings_repository
from app.modules.notify.domain.ports import DeviceRepository, InboxRepository, SettingsRepository
from app.modules.notify.schemas import (
    DeviceCreate,
    DeviceRead,
    InboxRead,
    NotificationSettingsRead,
    NotificationSettingsUpdate,
)

router = APIRouter(tags=["notify"])

User = Annotated[UUID, Depends(get_current_user_id)]
Devices = Annotated[DeviceRepository, Depends(get_device_repository)]
Settings = Annotated[SettingsRepository, Depends(get_settings_repository)]
InboxRepo = Annotated[InboxRepository, Depends(get_inbox_repository)]


@router.post(
    "/me/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED, summary="Registra un dispositivo"
)
async def register_device_route(payload: DeviceCreate, user_id: User, devices: Devices) -> DeviceRead:
    """RF-8 y RF-9: registra o reactiva; si el token era de otra cuenta, pasa a esta."""
    return DeviceRead.from_record(await register_device(payload.to_new(), user_id, devices))


@router.delete("/me/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Da de baja un dispositivo")
async def revoke_device_route(device_id: UUID, user_id: User, devices: Devices) -> Response:
    """RF-10: deja de recibir avisos. El de otro usuario es 404 (RF-21)."""
    await revoke_device(device_id, user_id, devices)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/notification-settings", response_model=NotificationSettingsRead, summary="Los ajustes de aviso")
async def get_settings_route(user_id: User, settings: Settings) -> NotificationSettingsRead:
    """RF-11: cada tipo de aviso, si está encendido y si se puede apagar."""
    return NotificationSettingsRead.from_records(await get_settings(user_id, settings))


@router.put("/me/notification-settings", response_model=NotificationSettingsRead, summary="Cambia los ajustes de aviso")
async def update_settings_route(
    payload: NotificationSettingsUpdate, user_id: User, settings: Settings
) -> NotificationSettingsRead:
    """RF-11 y RF-12: solo los tipos enviados; uno que no existe o no se puede apagar es 422."""
    return NotificationSettingsRead.from_records(await update_settings(payload.to_changes(), user_id, settings))


@router.get("/me/notifications", response_model=InboxRead, summary="Los avisos recibidos")
async def get_inbox_route(
    user_id: User,
    inbox: InboxRepo,
    before: Annotated[datetime | None, Query(description="El `created_at` del último de la página anterior")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InboxRead:
    """Pantalla Avisos: del más nuevo al más viejo, con cuántos sin leer."""
    return InboxRead.from_record(await get_inbox(user_id, before, limit, inbox))


@router.post("/me/notifications/read", status_code=status.HTTP_204_NO_CONTENT, summary="Marca los avisos como leídos")
async def mark_inbox_read_route(user_id: User, inbox: InboxRepo) -> Response:
    """Todos los avisos sin leer pasan a leídos."""
    await mark_inbox_read(user_id, inbox)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
