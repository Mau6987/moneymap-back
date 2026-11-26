"""Abrir una sesión: guardar el hash del refresh token y armar el par de tokens (RF-17)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.core.security import (
    access_token_ttl_seconds,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    refresh_token_ttl_days,
)
from app.modules.iam.domain.models import NewSession, TokenPair
from app.modules.iam.domain.ports import SessionRepository


async def open_session(user_id: UUID, sessions: SessionRepository, now: datetime) -> TokenPair:
    """El refresh token en claro solo lo ve la app; la base guarda su hash."""
    refresh_token = create_refresh_token()
    await sessions.create(
        NewSession(
            user_id=user_id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=now + timedelta(days=refresh_token_ttl_days()),
        )
    )
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=refresh_token,
        expires_in=access_token_ttl_seconds(),
    )
