"""Idempotencia de los POST que registran dinero (spec 002, requisito no funcional).

`POST /v1/transactions` acepta un `Idempotency-Key`: un reintento con la misma
clave devuelve la misma respuesta sin crear un segundo movimiento. La respuesta
se guarda 24 h en Redis, que ya está en el proyecto, así que no hace falta una
tabla nueva.

Es un asunto del transporte —el encabezado— y por eso vive en `core/` y no en el
módulo: cualquier POST que cree algo con una clave puede reusarlo.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from redis.exceptions import RedisError

from app.core.dependencies import get_current_user_id
from app.core.redis import get_redis

KEY_PREFIX = "idempotency"
KEY_TTL_SECONDS = 24 * 60 * 60
MAX_KEY_LENGTH = 128


class IdempotentRequest:
    """El `Idempotency-Key` de esta petición, si vino.

    El caso de uso no se entera: el endpoint pregunta si la respuesta ya está
    guardada y, si no lo está, la guarda al terminar.
    """

    def __init__(self, key: str | None, user_id: UUID) -> None:
        self._key = key
        self._user_id = user_id

    @property
    def key(self) -> str | None:
        """La clave, o None si el cliente no mandó el encabezado."""
        return self._key

    async def replay(self) -> str | None:
        """La respuesta guardada, si esta clave ya se usó."""
        if self._key is None:
            return None
        try:
            stored: str | None = await get_redis().get(self._cache_key())
            return stored
        except RedisError:
            return None

    async def remember(self, body: str) -> None:
        """Guarda la respuesta para el reintento."""
        if self._key is None:
            return
        try:
            await get_redis().set(self._cache_key(), body, ex=KEY_TTL_SECONDS)
        except RedisError:
            return

    def _cache_key(self) -> str:
        # Por usuario, para que la clave de uno no choque con la de otro.
        return f"{KEY_PREFIX}:{self._user_id}:{self._key}"


async def get_idempotent_request(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=MAX_KEY_LENGTH)] = None,
) -> IdempotentRequest:
    return IdempotentRequest(key, user_id)
