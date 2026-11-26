"""El SQL de los dispositivos para avisos (spec 006, RF-8 a RF-10).

`iam.devices` no tiene RLS, así que todo filtra por `user_id`. El índice único
`devices_push_token_uq` deja un solo dispositivo activo por token push.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notify.domain.models import Device, NewDevice

# RF-9: el token pasa a quien lo registra ahora; la fila de la otra cuenta se da de baja.
_REVOKE_FROM_OTHERS = text(
    """
    UPDATE iam.devices SET revoked_at = now()
    WHERE push_token = :push_token AND revoked_at IS NULL AND user_id <> :user_id
    """
)

# RF-8: si el token ya era de este usuario, se actualiza la misma fila.
_UPSERT_DEVICE = text(
    """
    INSERT INTO iam.devices (user_id, platform, push_token, app_version, os_version)
    VALUES (:user_id, :platform, :push_token, :app_version, :os_version)
    ON CONFLICT (push_token) WHERE push_token IS NOT NULL AND revoked_at IS NULL
    DO UPDATE SET platform = EXCLUDED.platform, app_version = EXCLUDED.app_version,
                  os_version = EXCLUDED.os_version, last_seen_at = now()
    RETURNING id, platform, app_version, os_version, created_at, last_seen_at
    """
)

_REVOKE_DEVICE = text(
    """
    UPDATE iam.devices SET revoked_at = now()
    WHERE id = :device_id AND user_id = :user_id AND revoked_at IS NULL
    RETURNING id
    """
)


class SqlDeviceRepository:
    """Implementa `DeviceRepository` sobre la sesión de la petición."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, user_id: UUID, device: NewDevice) -> Device:
        params = {
            "user_id": user_id,
            "platform": device.platform,
            "push_token": device.push_token,
            "app_version": device.app_version,
            "os_version": device.os_version,
        }
        await self._session.execute(_REVOKE_FROM_OTHERS, params)
        row = (await self._session.execute(_UPSERT_DEVICE, params)).mappings().one()
        return Device(**row)

    async def revoke(self, user_id: UUID, device_id: UUID) -> bool:
        params = {"user_id": user_id, "device_id": device_id}
        return (await self._session.execute(_REVOKE_DEVICE, params)).scalar_one_or_none() is not None
