"""El SQL de `iam.sessions`: la rotación del refresh token (RF-17, RF-18).

La rotación se reclama con un `UPDATE ... WHERE revoked_at IS NULL`: si otra
petición llegó primero, no devuelve fila y quien llama sabe que el token se
reusó. Así dos refresh simultáneos no abren dos sesiones.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.domain.models import NewSession, SessionRecord

_INSERT_SESSION = text(
    """
    INSERT INTO iam.sessions (user_id, device_id, refresh_token_hash, expires_at)
    VALUES (:user_id, :device_id, :refresh_token_hash, :expires_at)
    RETURNING id
    """
)

_SELECT_BY_REFRESH_HASH = text(
    """
    SELECT id, user_id, device_id, expires_at, revoked_at
    FROM iam.sessions
    WHERE refresh_token_hash = :refresh_token_hash
    """
)

_CLAIM_FOR_ROTATION = text(
    """
    UPDATE iam.sessions
    SET revoked_at = :now
    WHERE id = :session_id AND revoked_at IS NULL
    RETURNING id
    """
)

# Todas las sesiones abiertas del usuario, en todos sus dispositivos (RF-8 de la 008).
_REVOKE_ALL = text(
    """
    UPDATE iam.sessions SET revoked_at = :now
    WHERE user_id = :user_id AND revoked_at IS NULL
    RETURNING id
    """
)

_LINK_REPLACEMENT = text("UPDATE iam.sessions SET replaced_by = :new_id WHERE id = :previous_id")

# BUG-053: la sesión que reemplazó a esta, si se rotó hace poco y nadie la usó
# todavía. Es el caso de una respuesta de refresh que se perdió en la red.
_UNUSED_REPLACEMENT = text(
    """
    SELECT replacement.id
    FROM iam.sessions AS previous
    JOIN iam.sessions AS replacement ON replacement.id = previous.replaced_by
    WHERE previous.id = :session_id
      AND previous.revoked_at >= :since
      AND replacement.revoked_at IS NULL
      AND replacement.replaced_by IS NULL
    """
)

# La cadena de ese dispositivo: la sesión y todo lo que la reemplazó.
# UNION (no ALL) para que un ciclo no cuelgue la consulta.
_REVOKE_CHAIN = text(
    """
    WITH RECURSIVE chain AS (
        SELECT id, replaced_by FROM iam.sessions WHERE id = :session_id
        UNION
        SELECT sessions.id, sessions.replaced_by
        FROM iam.sessions
        JOIN chain ON sessions.id = chain.replaced_by
    )
    UPDATE iam.sessions
    SET revoked_at = :now
    WHERE id IN (SELECT id FROM chain) AND revoked_at IS NULL
    RETURNING id
    """
)


class SqlSessionRepository:
    """Implementa `SessionRepository` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, session: NewSession) -> UUID:
        session_id: UUID = (
            await self._session.execute(
                _INSERT_SESSION,
                {
                    "user_id": session.user_id,
                    "device_id": session.device_id,
                    "refresh_token_hash": session.refresh_token_hash,
                    "expires_at": session.expires_at,
                },
            )
        ).scalar_one()
        return session_id

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None:
        row = (
            (await self._session.execute(_SELECT_BY_REFRESH_HASH, {"refresh_token_hash": refresh_token_hash}))
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _to_session_record(row)

    async def rotate(self, previous_id: UUID, new_session: NewSession, now: datetime) -> UUID | None:
        claimed = (
            await self._session.execute(_CLAIM_FOR_ROTATION, {"session_id": previous_id, "now": now})
        ).scalar_one_or_none()
        if claimed is None:
            return None
        new_id = await self.create(new_session)
        await self._session.execute(_LINK_REPLACEMENT, {"previous_id": previous_id, "new_id": new_id})
        return new_id

    async def unused_replacement(self, session_id: UUID, since: datetime) -> UUID | None:
        params = {"session_id": session_id, "since": since}
        replacement: UUID | None = (await self._session.execute(_UNUSED_REPLACEMENT, params)).scalar_one_or_none()
        return replacement

    async def revoke_chain(self, session_id: UUID, now: datetime) -> int:
        revoked = (await self._session.execute(_REVOKE_CHAIN, {"session_id": session_id, "now": now})).scalars().all()
        return len(revoked)

    async def revoke_all(self, user_id: UUID, now: datetime) -> int:
        revoked = (await self._session.execute(_REVOKE_ALL, {"user_id": user_id, "now": now})).scalars().all()
        return len(revoked)


def _to_session_record(row: RowMapping) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )
