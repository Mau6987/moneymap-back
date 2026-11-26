"""Caso de uso de escritura: rotar el refresh token (RF-17) y cortar la cadena si se reusa (RF-18)."""

from datetime import datetime, timedelta

from app.core import clock
from app.core.security import (
    access_token_ttl_seconds,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    refresh_token_ttl_days,
)
from app.modules.iam.domain.errors import InvalidRefreshToken, RefreshTokenReused
from app.modules.iam.domain.models import NewSession, SessionRecord, TokenPair
from app.modules.iam.domain.ports import SecurityAudit, SessionRepository, UnitOfWork

REUSED_DETAIL = "Ese refresh token ya se usó: cerramos la sesión de ese dispositivo"
# BUG-053: margen para un refresh cuya respuesta se perdió (timeout, mala señal).
REFRESH_GRACE = timedelta(seconds=60)


async def refresh_session(
    refresh_token: str,
    sessions: SessionRepository,
    audit: SecurityAudit,
    unit_of_work: UnitOfWork,
) -> TokenPair:
    """Entrega un par nuevo y revoca el anterior.

    Un token que ya se había rotado significa que alguien lo copió: se revoca
    toda la cadena de ese dispositivo, se deja la traza y no se entrega nada.
    Salvo una excepción (BUG-053): si se rotó hace menos de `REFRESH_GRACE` y
    el par nuevo nunca se usó, la respuesta se perdió en la red; se rota desde
    ese par sin usar y la persona no pierde la sesión.
    """
    now = clock.utc_now()
    session = await sessions.find_by_refresh_hash(hash_refresh_token(refresh_token))
    if session is None:
        raise InvalidRefreshToken("El refresh token no es válido")
    previous_id = session.id
    if session.revoked_at is not None:
        replacement = await sessions.unused_replacement(session.id, now - REFRESH_GRACE)
        if replacement is None:
            await _cut_chain(session, sessions, audit, unit_of_work, now)
            raise RefreshTokenReused(REUSED_DETAIL)
        previous_id = replacement
    if session.expires_at <= now:
        raise InvalidRefreshToken("El refresh token venció: volvé a iniciar sesión")

    new_refresh_token = create_refresh_token()
    rotated = await sessions.rotate(
        previous_id,
        NewSession(
            user_id=session.user_id,
            refresh_token_hash=hash_refresh_token(new_refresh_token),
            expires_at=now + timedelta(days=refresh_token_ttl_days()),
            device_id=session.device_id,
        ),
        now,
    )
    if rotated is None:
        await _cut_chain(session, sessions, audit, unit_of_work, now)
        raise RefreshTokenReused(REUSED_DETAIL)

    return TokenPair(
        access_token=create_access_token(session.user_id),
        refresh_token=new_refresh_token,
        expires_in=access_token_ttl_seconds(),
    )


async def _cut_chain(
    session: SessionRecord,
    sessions: SessionRepository,
    audit: SecurityAudit,
    unit_of_work: UnitOfWork,
    now: datetime,
) -> None:
    """Revoca la cadena, deja la traza y confirma las dos cosas.

    Confirma acá y no al cerrar la sesión porque la petición termina en 401: sin
    este commit, la dependencia de sesión haría rollback y el corte no quedaría.
    """
    await sessions.revoke_chain(session.id, now)
    await audit.refresh_token_reused(session.user_id, session.id)
    await unit_of_work.commit()
