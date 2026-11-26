"""El SQL de los ajustes de aviso (spec 006, RF-11 y RF-12).

`notify.preferences` solo guarda lo que el usuario cambió; lo efectivo lo dice
`notify.is_enabled`, que deja siempre encendidos los avisos transaccionales.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notify.domain.models import NotificationSetting

_SELECT_SETTINGS = text(
    """
    SELECT types.key, types.description, notify.is_enabled(:user_id, types.key) AS enabled,
           NOT types.is_transactional AS can_disable
    FROM notify.notification_types AS types
    ORDER BY types.key
    """
)

# RF-12: un tipo que no existe o que no se puede apagar no inserta nada.
_SET_SETTING = text(
    """
    INSERT INTO notify.preferences (user_id, type_key, channel, is_enabled)
    SELECT :user_id, types.key, 'push', :enabled
    FROM notify.notification_types AS types
    WHERE types.key = :type_key AND NOT types.is_transactional
    ON CONFLICT (user_id, type_key, channel) DO UPDATE SET is_enabled = EXCLUDED.is_enabled, updated_at = now()
    RETURNING type_key
    """
)


class SqlSettingsRepository:
    """Implementa `SettingsRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UUID) -> Sequence[NotificationSetting]:
        rows = (await self._session.execute(_SELECT_SETTINGS, {"user_id": user_id})).mappings()
        return [NotificationSetting(**row) for row in rows]

    async def set(self, user_id: UUID, type_key: str, enabled: bool) -> bool:
        params = {"user_id": user_id, "type_key": type_key, "enabled": enabled}
        return (await self._session.execute(_SET_SETTING, params)).scalar_one_or_none() is not None
