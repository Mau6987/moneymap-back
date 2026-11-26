"""El cliente de Redis: límite de intentos, idempotencia y lo que venga.

Es un pool de conexiones, no un dato global mutable, así que vive al lado del
motor de la base (`core/db.py`).
"""

from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """El cliente de Redis de la API, creado la primera vez que se usa."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis
