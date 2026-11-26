"""Las fotos de los comprobantes en el S3 propio (SeaweedFS) (spec 014).

El cliente (`minio`, que habla S3) es síncrono: cada llamada corre en un hilo para no frenar
el event loop. El bucket se crea la primera vez que hace falta.
"""

import asyncio
from functools import lru_cache
from io import BytesIO

from minio import Minio

from app.core.config import get_settings
from app.modules.finance.domain.receipts import Receipt


class S3ReceiptStorage:
    """Implementa `ReceiptStorage`."""

    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        self._bucket_ready = False

    async def put(self, key: str, receipt: Receipt) -> None:
        await asyncio.to_thread(self._put, key, receipt)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)

    def _put(self, key: str, receipt: Receipt) -> None:
        if not self._bucket_ready:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._bucket_ready = True
        data = BytesIO(receipt.content)
        self._client.put_object(self._bucket, key, data, len(receipt.content), content_type=receipt.content_type)

    def _get(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


@lru_cache
def s3_receipt_storage() -> S3ReceiptStorage:
    settings = get_settings()
    client = Minio(
        settings.receipts_endpoint,
        access_key=settings.receipts_access_key,
        secret_key=settings.receipts_secret_key.get_secret_value(),
        secure=False,  # solo en la red interna del compose
    )
    return S3ReceiptStorage(client, settings.receipts_bucket)
