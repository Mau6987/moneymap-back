"""La cola de salida de los avisos (spec 006, RF-13 y RF-14): `notify.notifications`.

La usan los workers, con la conexión de la persona (`app.user_id` puesto). Se
encola **una fila por aviso**, no por dispositivo: quien envía la reparte entre
los dispositivos activos del momento, y así uno que se registra o se da de baja
entre que se encola y se envía no queda mal.

Solo se guarda si la persona tiene ese tipo de aviso encendido, y una sola vez
por `dedupe_key`. Queda en la bandeja de la pantalla Avisos aunque no tenga
dispositivo; sin dispositivo activo entra como `skipped` y no se envía push (RF-13).
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_ENQUEUE = text(
    """
    INSERT INTO notify.notifications (user_id, type_key, title, body, data, dedupe_key, status)
    SELECT :user_id, :type_key, :title, :body, CAST(:data AS jsonb), :dedupe_key,
           CASE WHEN EXISTS (SELECT 1 FROM iam.devices AS devices
                             WHERE devices.user_id = :user_id AND devices.revoked_at IS NULL
                               AND devices.push_token IS NOT NULL)
                THEN 'queued' ELSE 'skipped' END
    WHERE notify.is_enabled(:user_id, :type_key)
      AND NOT EXISTS (SELECT 1 FROM notify.notifications AS sent
                      WHERE sent.user_id = :user_id AND sent.dedupe_key = :dedupe_key)
    """
)

# RF-14: con el modo privado, los textos van sin montos ni nombres.
_HIDES_AMOUNTS = text(
    "SELECT coalesce((SELECT hide_amounts FROM iam.user_preferences WHERE user_id = :user_id), false)"
)


async def hides_amounts(connection: AsyncConnection, user_id: UUID) -> bool:
    hidden: bool = (await connection.execute(_HIDES_AMOUNTS, {"user_id": user_id})).scalar_one()
    return hidden


async def enqueue(
    connection: AsyncConnection,
    user_id: UUID,
    type_key: str,
    title: str,
    body: str,
    dedupe_key: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Guarda el aviso y dice si entró (False: apagado o repetido)."""
    params = {
        "user_id": user_id,
        "type_key": type_key,
        "title": title,
        "body": body,
        "data": json.dumps(data or {}),
        "dedupe_key": dedupe_key,
    }
    return bool((await connection.execute(_ENQUEUE, params)).rowcount)
