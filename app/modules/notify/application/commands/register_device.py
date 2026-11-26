"""Caso de uso de escritura: registrar un dispositivo para avisos (spec 006, RF-8 y RF-9)."""

from uuid import UUID

from app.modules.notify.domain.models import Device, NewDevice
from app.modules.notify.domain.ports import DeviceRepository


async def register_device(device: NewDevice, user_id: UUID, devices: DeviceRepository) -> Device:
    """Registra o reactiva; un token de otra cuenta pasa a esta (RF-9)."""
    return await devices.register(user_id, device)
