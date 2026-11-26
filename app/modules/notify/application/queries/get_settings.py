"""Caso de uso de lectura: los ajustes de aviso (spec 006, RF-11)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notify.domain.models import NotificationSetting
from app.modules.notify.domain.ports import SettingsRepository


async def get_settings(user_id: UUID, settings: SettingsRepository) -> Sequence[NotificationSetting]:
    return await settings.list(user_id)
