"""El borrado de las cuentas: a los 30 días de pedirlo, se borra todo (spec 001, RF-29).

`DELETE FROM iam.users` borra en cascada todo lo del usuario: cuentas,
movimientos, metas, sesiones. Las tablas financieras tienen RLS, así que cada
cuenta se borra en su propia transacción con `app.user_id`, igual que una
petición del usuario. Así no hace falta el rol `moneymap_worker` (ver
`retention.py`) y, si una falla, las demás siguen.

Se vuelve a mirar el estado y la fecha en el DELETE: si la persona entró
mientras corría el job, el borrado se canceló (RF-30) y la cuenta se queda.
"""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.config import get_settings
from app.modules.iam.application.commands.request_account_deletion import ACCOUNT_DELETION_GRACE_DAYS
from app.workers import celery

_SELECT_DUE = text("SELECT id FROM iam.users WHERE status = 'pending_deletion' AND deletion_requested_at <= :cutoff")

_DELETE_USER = text(
    """
    DELETE FROM iam.users
    WHERE id = :user_id AND status = 'pending_deletion' AND deletion_requested_at <= :cutoff
    """
)

# Sin el id del usuario: ya no existe y el log es lo único que queda.
_LOG_PURGED = text(
    """
    SELECT ops.log(
        p_level => 'info',
        p_category => 'job',
        p_event_code => 'account.deletion.purged',
        p_message => 'Se borraron las cuentas que pidieron borrarse hace más de 30 días',
        p_service => 'worker',
        p_context => jsonb_build_object('accounts', CAST(:accounts AS integer))
    )
    """
)


async def purge_deleted_accounts() -> int:
    """Borra las cuentas vencidas y devuelve cuántas."""
    cutoff = clock.utc_now() - timedelta(days=ACCOUNT_DELETION_GRACE_DAYS)
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            due = (await connection.execute(_SELECT_DUE, {"cutoff": cutoff})).scalars().all()
        deleted = 0
        for user_id in due:
            deleted += await _delete_one(engine, user_id, cutoff)
        if deleted:
            async with engine.begin() as connection:
                await connection.execute(_LOG_PURGED, {"accounts": deleted})
    finally:
        await engine.dispose()
    return deleted


async def _delete_one(engine: AsyncEngine, user_id: UUID, cutoff: datetime) -> int:
    async with engine.begin() as connection:
        await connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
        return (await connection.execute(_DELETE_USER, {"user_id": user_id, "cutoff": cutoff})).rowcount


@celery.task(name="identity.purge_deleted_accounts")  # type: ignore[untyped-decorator]  # celery no publica tipos
def purge_deleted_accounts_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): todos los días a las 04:30 UTC."""
    return asyncio.run(purge_deleted_accounts())
