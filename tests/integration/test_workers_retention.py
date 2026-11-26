"""El job de limpieza de los tokens de un solo uso.

Se prueba la función que hace el trabajo (no la tarea de Celery): el calendario se
verifica mirando la app de Celery, y el borrado, contra PostgreSQL real.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import clock
from app.workers import celery
from app.workers.retention import RETENTION_DAYS, purge_old_identity_tokens


async def test_borra_lo_viejo_y_deja_lo_nuevo(
    owner_connection: AsyncConnection,
    user_id: UUID,
) -> None:
    nuevo = clock.utc_now()
    viejo = nuevo - timedelta(days=RETENTION_DAYS + 1)
    await owner_connection.execute(
        text(
            "INSERT INTO iam.email_verifications (email, token_hash, expires_at, created_at)"
            " VALUES (:email, :token_hash, :expires_at, :created_at)"
        ),
        {
            "email": "vieja.verificacion@example.com",
            "token_hash": "hash-viejo",
            "expires_at": viejo,
            "created_at": viejo,
        },
    )
    await owner_connection.execute(
        text(
            "INSERT INTO iam.email_verifications (email, token_hash, expires_at, created_at)"
            " VALUES (:email, :token_hash, :expires_at, :created_at)"
        ),
        {
            "email": "nueva.verificacion@example.com",
            "token_hash": "hash-nuevo",
            "expires_at": nuevo,
            "created_at": nuevo,
        },
    )
    await owner_connection.execute(
        text(
            "INSERT INTO iam.verification_tokens (user_id, purpose, token_hash, expires_at, created_at)"
            " VALUES (:user_id, 'password_reset', 'hash-viejo', :expires_at, :created_at)"
        ),
        {"user_id": user_id, "expires_at": viejo, "created_at": viejo},
    )
    await owner_connection.commit()

    deleted = await purge_old_identity_tokens()

    assert deleted >= 2
    quedan = (
        (
            await owner_connection.execute(
                text("SELECT email FROM iam.email_verifications WHERE email LIKE '%@example.com'")
            )
        )
        .scalars()
        .all()
    )
    assert list(quedan) == ["nueva.verificacion@example.com"]
    tokens = (
        await owner_connection.execute(
            text("SELECT count(*) FROM iam.verification_tokens WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    ).scalar_one()
    assert tokens == 0


def test_la_tarea_esta_en_el_calendario() -> None:
    """`celery -A app.workers worker --beat` tiene que tener algo que correr."""
    schedule = celery.conf.beat_schedule

    assert "purge-old-identity-tokens" in schedule
    assert schedule["purge-old-identity-tokens"]["task"] == "identity.purge_old_tokens"
