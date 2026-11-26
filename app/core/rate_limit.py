"""Límite de intentos por ventana fija, con Redis (spec 001, requisitos no funcionales).

La ventana empieza con el primer intento: el contador vive con su TTL y se
reinicia solo.

**Si Redis no responde se deja pasar.** Es a propósito: el límite protege al
servicio del abuso, no a un dato, así que una caída de la caché no puede dejar a
todo el mundo sin registro ni login. El costo es que la caída queda invisible
desde acá; se ve en las métricas de Redis, no en `/health`, porque un health
check que dependa de Redis marcaría como caída una API sana.
"""

from redis.exceptions import RedisError

from app.core.errors import TooManyRequests
from app.core.redis import get_redis

# Prefijo de todas las claves del limitador, para poder limpiarlas en las pruebas.
KEY_PREFIX = "ratelimit"


async def enforce_rate_limit(
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Corta con 429 cuando `identifier` se pasa de `limit` intentos en la ventana."""
    key = f"{KEY_PREFIX}:{scope}:{identifier}"
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            attempts, _, ttl = await pipe.execute()
    except RedisError:
        # A propósito, no es un error que se esconda: la política es dejar pasar.
        return

    if attempts > limit:
        raise TooManyRequests(retry_after_seconds=max(int(ttl), 1))


async def clear_rate_limits() -> None:
    """Borra los contadores. Solo lo usan las pruebas, para no arrastrarlos."""
    redis = get_redis()
    try:
        async for key in redis.scan_iter(f"{KEY_PREFIX}:*"):
            await redis.delete(key)
    except RedisError:
        return
