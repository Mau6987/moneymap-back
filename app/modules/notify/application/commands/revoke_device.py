"""Caso de uso de escritura: dar de baja un dispositivo (spec 006, RF-10 y RF-21)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.notify.domain.ports import DeviceRepository


async def revoke_device(device_id: UUID, user_id: UUID, devices: DeviceRepository) -> None:
    """El de otro usuario, uno que no existe o uno ya dado de baja: 404."""
    if not await devices.revoke(user_id, device_id):
        raise NotFound("No existe ese dispositivo")
