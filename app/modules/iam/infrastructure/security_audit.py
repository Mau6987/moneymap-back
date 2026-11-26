"""La traza de seguridad, en `ops.log` (spec 001 RF-18).

`ops.log` es una función de la base: la API solo la ejecuta y nunca lee los
logs (db/migrations/900_security.sql). El contexto va con `jsonb_build_object`
para no mandar jsonb desde Python.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LOG_PASSWORD_RESET = text(
    """
    SELECT ops.log(
        p_level => 'info',
        p_category => 'security',
        p_event_code => 'auth.password.reset',
        p_message => 'La persona restableció su contraseña y se cerraron sus sesiones',
        p_service => 'api',
        p_user_id => :user_id
    )
    """
)

_LOG_DELETION_REQUESTED = text(
    """
    SELECT ops.log(
        p_level => 'info',
        p_category => 'security',
        p_event_code => 'account.deletion.requested',
        p_message => 'La persona pidió borrar su cuenta: se cerraron sus sesiones y se borra en 30 días',
        p_service => 'api',
        p_user_id => :user_id
    )
    """
)

_LOG_REFRESH_REUSED = text(
    """
    SELECT ops.log(
        p_level => 'warning',
        p_category => 'security',
        p_event_code => 'auth.refresh.reused',
        p_message => 'Se reusó un refresh token ya rotado: se cerraron las sesiones de ese dispositivo',
        p_service => 'api',
        p_user_id => :user_id,
        p_context => jsonb_build_object('session_id', CAST(:session_id AS text))
    )
    """
)


class SqlSecurityAudit:
    """Implementa `SecurityAudit` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh_token_reused(self, user_id: UUID, session_id: UUID) -> None:
        # `CAST(... AS text)` hace que Postgres espere texto: el UUID va como cadena.
        await self._session.execute(_LOG_REFRESH_REUSED, {"user_id": user_id, "session_id": str(session_id)})

    async def password_reset(self, user_id: UUID) -> None:
        # Sin el código ni la contraseña: solo que pasó y quién (constitución §5).
        await self._session.execute(_LOG_PASSWORD_RESET, {"user_id": user_id})

    async def account_deletion_requested(self, user_id: UUID) -> None:
        await self._session.execute(_LOG_DELETION_REQUESTED, {"user_id": user_id})
