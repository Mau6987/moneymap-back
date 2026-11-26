"""El job que borra las cuentas a los 30 días de pedirlo (spec 001, RF-29).

Se prueba la función que hace el trabajo, contra PostgreSQL real, como en
`test_workers_retention.py`.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import clock
from app.core.db import user_session
from app.modules.iam.application.commands.request_account_deletion import ACCOUNT_DELETION_GRACE_DAYS
from app.workers import celery
from app.workers.account_deletion import purge_deleted_accounts


async def _schedule(owner: AsyncConnection, user_id: UUID, days_ago: int) -> None:
    await owner.execute(
        text(
            "UPDATE iam.users SET status = 'pending_deletion', deletion_requested_at = :requested_at"
            " WHERE id = :user_id"
        ),
        {"user_id": user_id, "requested_at": clock.utc_now() - timedelta(days=days_ago)},
    )


async def _with_an_account(user_id: UUID) -> None:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.accounts (user_id, name, type, currency)"
                " VALUES (:user_id, 'Efectivo', 'cash', 'BOB')"
            ),
            {"user_id": user_id},
        )


async def _exists(owner: AsyncConnection, user_id: UUID) -> bool:
    found = await owner.execute(text("SELECT 1 FROM iam.users WHERE id = :user_id"), {"user_id": user_id})
    return found.scalar_one_or_none() is not None


async def test_borra_en_cascada_las_vencidas_y_deja_las_que_esperan(
    owner_connection: AsyncConnection,
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    expired = await new_financial_user()
    waiting = await new_financial_user()
    active = await new_financial_user()
    await _with_an_account(expired)
    await _schedule(owner_connection, expired, days_ago=ACCOUNT_DELETION_GRACE_DAYS + 1)
    await _schedule(owner_connection, waiting, days_ago=ACCOUNT_DELETION_GRACE_DAYS - 1)
    await owner_connection.commit()

    deleted = await purge_deleted_accounts()

    assert deleted >= 1
    assert not await _exists(owner_connection, expired)
    assert await _exists(owner_connection, waiting)
    assert await _exists(owner_connection, active)
    accounts = await owner_connection.execute(
        text("SELECT count(*) FROM finance.accounts WHERE user_id = :user_id"), {"user_id": expired}
    )
    assert accounts.scalar_one() == 0


def test_la_tarea_esta_en_el_calendario() -> None:
    schedule = celery.conf.beat_schedule
    assert schedule["purge-deleted-accounts"]["task"] == "identity.purge_deleted_accounts"
    assert "identity.purge_deleted_accounts" in celery.tasks
