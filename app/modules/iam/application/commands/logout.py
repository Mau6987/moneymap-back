"""Caso de uso de escritura: cerrar la sesión de un dispositivo (RF-32)."""

from app.core import clock
from app.core.security import hash_refresh_token
from app.modules.iam.domain.ports import SessionRepository


async def logout(refresh_token: str, sessions: SessionRepository) -> None:
    """Revoca la sesión de ese refresh token y todo lo que la reemplazó.

    Un token que no existe, ya se revocó o venció no es un error: la sesión
    ya no sirve, que es lo que la app pide. Responder igual en todos los casos
    tampoco delata qué tokens existieron.
    """
    session = await sessions.find_by_refresh_hash(hash_refresh_token(refresh_token))
    if session is None or session.revoked_at is not None:
        return
    await sessions.revoke_chain(session.id, clock.utc_now())
