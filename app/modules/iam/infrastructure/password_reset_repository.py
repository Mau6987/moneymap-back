"""El SQL de los códigos del restablecimiento, en `iam.verification_tokens` (RF-3, RF-4).

La tabla ya existía con su `purpose = 'password_reset'`, así que no hizo falta una
migración. Del código solo se guarda su hash, y con argon2id: un hash rápido se
rompe en un segundo con 6 dígitos.

Este flujo pasa antes de que la persona entre, así que usa la sesión pública:
`iam.verification_tokens` no tiene RLS, como el resto de la identidad previa al
login.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Un solo código vale: marcar como usados los vigentes sirve para reemplazarlo
# (RF-4) y para consumirlo (RF-8).
_USE_ALL = text(
    """
    UPDATE iam.verification_tokens
    SET used_at = :now
    WHERE user_id = :user_id AND purpose = 'password_reset' AND used_at IS NULL
    """
)

_INSERT_CODE = text(
    """
    INSERT INTO iam.verification_tokens (user_id, purpose, token_hash, expires_at)
    VALUES (:user_id, 'password_reset', :code_hash, :expires_at)
    """
)

_LATEST_CODE = text(
    """
    SELECT token_hash
    FROM iam.verification_tokens
    WHERE user_id = :user_id AND purpose = 'password_reset'
      AND used_at IS NULL AND expires_at > :now
    ORDER BY created_at DESC
    LIMIT 1
    """
)


class SqlPasswordResetRepository:
    """Implementa `PasswordResetRepository` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_code(self, user_id: UUID, code_hash: str, expires_at: datetime, now: datetime) -> None:
        await self._session.execute(_USE_ALL, {"user_id": user_id, "now": now})
        await self._session.execute(
            _INSERT_CODE, {"user_id": user_id, "code_hash": code_hash, "expires_at": expires_at}
        )

    async def latest_code_hash(self, user_id: UUID, now: datetime) -> str | None:
        return (await self._session.execute(_LATEST_CODE, {"user_id": user_id, "now": now})).scalar_one_or_none()

    async def mark_used(self, user_id: UUID, now: datetime) -> None:
        await self._session.execute(_USE_ALL, {"user_id": user_id, "now": now})
