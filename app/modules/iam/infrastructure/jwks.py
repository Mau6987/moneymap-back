"""Las claves públicas de un proveedor de identidad, con caché (spec 001, RF-6)."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import httpx
from joserfc.jwk import KeySet

from app.core import clock

# Las claves cambian poco: no se piden en cada verificación.
KEY_SET_TTL = timedelta(hours=1)
HTTP_TIMEOUT_SECONDS = 5

LoadKeySet = Callable[[], Awaitable[KeySet]]


class CachedKeySet:
    """El JWKS de un proveedor, cacheado una vez por proceso."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._cached: KeySet | None = None
        self._expires_at: datetime | None = None

    async def __call__(self) -> KeySet:
        now = clock.utc_now()
        if self._cached is not None and self._expires_at is not None and now < self._expires_at:
            return self._cached
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(self._url)
            response.raise_for_status()
        self._cached = KeySet.import_key_set(response.json())
        self._expires_at = now + KEY_SET_TTL
        return self._cached
