"""Registra solos los recurrentes con `auto_post` al vencer (spec 003, RF-20).

`finance.recurring_rules` tiene RLS, así que no se puede pedir "todos los que
vencen" sin el rol del worker. En su lugar se recorre a las personas (`iam.users`
no tiene RLS) y cada una se atiende en su propia transacción con `app.user_id`,
como el borrado de cuentas (`account_deletion.py`). Si una falla, queda en
`ops.log` y siguen las demás: un recurrente mal configurado no frena a nadie más.

El registro es el mismo SQL que usa la API (`recurring_posting.py`), en la fecha
en que vencía. Si el job no corrió unos días, registra cada vencimiento atrasado.
"""

import asyncio
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.modules.finance.infrastructure.recurring_posting import post_on_due_date
from app.workers import celery

# ponytail: recorre a todas las personas cada día; con muchas, una conexión con
# moneymap_worker que pida directo los vencidos (recurring_rules_due_idx).
_SELECT_PEOPLE = text("SELECT id FROM iam.users WHERE deleted_at IS NULL AND status IN ('active', 'pending_deletion')")

# El "hoy" de cada persona, en su zona horaria.
_SELECT_DUE = text(
    """
    SELECT rules.id
    FROM finance.recurring_rules AS rules
    JOIN iam.users AS users ON users.id = rules.user_id
    WHERE rules.user_id = :user_id AND rules.auto_post AND rules.is_active AND rules.deleted_at IS NULL
      AND rules.next_due_on <= (now() AT TIME ZONE users.timezone)::date
    """
)

_LOG_FAILED = text(
    """
    SELECT ops.log(
        p_level => 'error',
        p_category => 'job',
        p_event_code => 'finance.recurring.post_failed',
        p_message => 'No se pudieron registrar los recurrentes vencidos de una persona',
        p_service => 'worker',
        p_user_id => :user_id,
        p_error_type => :error_type
    )
    """
)

# Un semanal que no se registró en un año son 52 vueltas; el tope corta un
# recurrente que, por un error, nunca avanzara.
MAX_CATCH_UP_ROUNDS = 400


async def post_due_recurring_rules() -> int:
    """Registra los vencimientos de todos y devuelve cuántos movimientos quedaron."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            people = (await connection.execute(_SELECT_PEOPLE)).scalars().all()
        posted = 0
        for user_id in people:
            posted += await _post_for(engine, user_id)
    finally:
        await engine.dispose()
    return posted


async def _post_for(engine: AsyncEngine, user_id: UUID) -> int:
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            return await _catch_up(connection, user_id)
    except DBAPIError as error:  # se anota y se sigue con la próxima persona (ver el docstring del módulo)
        async with engine.begin() as connection:
            await connection.execute(_LOG_FAILED, {"user_id": user_id, "error_type": type(error.orig).__name__})
        return 0


async def _catch_up(connection: AsyncConnection, user_id: UUID) -> int:
    posted = 0
    for _ in range(MAX_CATCH_UP_ROUNDS):
        due = (await connection.execute(_SELECT_DUE, {"user_id": user_id})).scalars().all()
        if not due:
            break
        for rule_id in due:
            posted += await post_on_due_date(connection, user_id, rule_id) is not None
    return posted


@celery.task(name="finance.post_due_recurring_rules")  # type: ignore[untyped-decorator]  # celery no publica tipos
def post_due_recurring_rules_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): todos los días a las 05:00 UTC."""
    return asyncio.run(post_due_recurring_rules())
