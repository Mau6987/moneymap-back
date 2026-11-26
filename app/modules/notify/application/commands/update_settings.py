"""Caso de uso de escritura: encender o apagar tipos de aviso (spec 006, RF-11 y RF-12)."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.notify.domain.errors import UnknownNotificationType
from app.modules.notify.domain.models import NotificationSetting
from app.modules.notify.domain.ports import SettingsRepository


async def update_settings(
    changes: Mapping[str, bool], user_id: UUID, settings: SettingsRepository
) -> Sequence[NotificationSetting]:
    """Cambia solo los tipos enviados. Uno que no sirve es 422 y la petición no cambia nada."""
    for type_key, enabled in changes.items():
        if not await settings.set(user_id, type_key, enabled):
            raise UnknownNotificationType(type_key)
    return await settings.list(user_id)
