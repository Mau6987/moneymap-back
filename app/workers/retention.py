"""Los trabajos de limpieza: los tokens de un solo uso que ya no sirven se borran.

`iam.email_verifications` (los links de la verificación del correo) y
`iam.verification_tokens` (los códigos del restablecimiento) guardan credenciales
de un solo uso: cada pedido deja una fila y **nadie las borraba**, así que crecían
para siempre.

Ninguna de las dos tablas tiene RLS —son de antes de que la persona entre—, así
que este job no necesita el rol del worker: alcanza con el usuario de la API, que
tiene permiso de DELETE sobre `iam`. El día que haya un job que toque datos
financieros de todos los usuarios va a hacer falta una conexión con
`moneymap_worker` (ver `db/README.md`).

El motor es propio y **sin pool** a propósito: cada tarea corre en su propio bucle
de asyncio (`asyncio.run`) y las conexiones de asyncpg no se pueden reusar entre
bucles.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.config import get_settings
from app.workers import celery

# Cuánto se guarda un token de un solo uso. Vence en minutos, así que 30 días
# sobra para mirar un caso raro de soporte.
RETENTION_DAYS = 30

_DELETE_OLD_VERIFICATIONS = text("DELETE FROM iam.email_verifications WHERE created_at < :cutoff")

_DELETE_OLD_USER_TOKENS = text("DELETE FROM iam.verification_tokens WHERE created_at < :cutoff")


async def purge_old_identity_tokens() -> int:
    """Borra lo anterior a la retención en las dos tablas y devuelve cuántas filas."""
    cutoff = clock.utc_now() - timedelta(days=RETENTION_DAYS)
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            verifications = (await connection.execute(_DELETE_OLD_VERIFICATIONS, {"cutoff": cutoff})).rowcount
            tokens = (await connection.execute(_DELETE_OLD_USER_TOKENS, {"cutoff": cutoff})).rowcount
    finally:
        await engine.dispose()
    return verifications + tokens


@celery.task(name="identity.purge_old_tokens")  # type: ignore[untyped-decorator]  # celery no publica tipos
def purge_old_identity_tokens_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): todos los días a las 04:00 UTC."""
    return asyncio.run(purge_old_identity_tokens())
