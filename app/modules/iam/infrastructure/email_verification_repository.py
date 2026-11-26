"""El SQL de `iam.email_verifications` (RF-22 a RF-26).

Sin RLS: la verificación ocurre antes de que exista el usuario. Del link solo se
guarda el hash, así que leer la tabla no sirve para verificar un correo ajeno.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.domain.models import EmailVerification

_INSERT = text(
    """
    INSERT INTO iam.email_verifications (email, token_hash, expires_at, last_sent_at)
    VALUES (:email, :token_hash, :expires_at, :now)
    RETURNING id, email, expires_at, last_sent_at, verified_at, used_at
    """
)

_SELECT = text(
    """
    SELECT id, email, expires_at, last_sent_at, verified_at, used_at
    FROM iam.email_verifications
    WHERE id = :id
    """
)

_SELECT_FOR_UPDATE = text(
    """
    SELECT id, email, expires_at, last_sent_at, verified_at, used_at
    FROM iam.email_verifications
    WHERE id = :id
    FOR UPDATE
    """
)

_SELECT_BY_TOKEN = text(
    """
    SELECT id, email, expires_at, last_sent_at, verified_at, used_at
    FROM iam.email_verifications
    WHERE token_hash = :token_hash
    """
)

_RENEW = text(
    """
    UPDATE iam.email_verifications
    SET token_hash = :token_hash, expires_at = :expires_at, last_sent_at = :now
    WHERE id = :id
    RETURNING id, email, expires_at, last_sent_at, verified_at, used_at
    """
)

_MARK_VERIFIED = text("UPDATE iam.email_verifications SET verified_at = :now WHERE id = :id AND verified_at IS NULL")

_MARK_USED = text("UPDATE iam.email_verifications SET used_at = :now WHERE id = :id")


class SqlEmailVerificationRepository:
    """Implementa `EmailVerificationRepository` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, email: str, token_hash: str, expires_at: datetime, now: datetime) -> EmailVerification:
        result = await self._session.execute(
            _INSERT, {"email": email, "token_hash": token_hash, "expires_at": expires_at, "now": now}
        )
        return _to_verification(result.mappings().one())

    async def get(self, verification_id: UUID, *, for_update: bool = False) -> EmailVerification | None:
        query = _SELECT_FOR_UPDATE if for_update else _SELECT
        row = (await self._session.execute(query, {"id": verification_id})).mappings().one_or_none()
        return None if row is None else _to_verification(row)

    async def find_by_token_hash(self, token_hash: str) -> EmailVerification | None:
        row = (await self._session.execute(_SELECT_BY_TOKEN, {"token_hash": token_hash})).mappings().one_or_none()
        return None if row is None else _to_verification(row)

    async def renew_token(
        self, verification_id: UUID, token_hash: str, expires_at: datetime, now: datetime
    ) -> EmailVerification:
        result = await self._session.execute(
            _RENEW, {"id": verification_id, "token_hash": token_hash, "expires_at": expires_at, "now": now}
        )
        return _to_verification(result.mappings().one())

    async def mark_verified(self, verification_id: UUID, now: datetime) -> None:
        await self._session.execute(_MARK_VERIFIED, {"id": verification_id, "now": now})

    async def mark_used(self, verification_id: UUID, now: datetime) -> None:
        await self._session.execute(_MARK_USED, {"id": verification_id, "now": now})


def _to_verification(row: RowMapping) -> EmailVerification:
    return EmailVerification(
        id=row["id"],
        email=row["email"],
        expires_at=row["expires_at"],
        last_sent_at=row["last_sent_at"],
        verified_at=row["verified_at"],
        used_at=row["used_at"],
    )
