"""Qué gasto tiene foto y dónde está (spec 014), sobre la sesión del usuario (con RLS)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Solo un gasto vivo del usuario: otro tipo, uno borrado o ajeno no inserta
# nada y la API responde 404.
_SAVE = text(
    """
    INSERT INTO finance.transaction_receipts (user_id, transaction_id, object_key, content_type, size_bytes)
    SELECT transactions.user_id, transactions.id, :key, :content_type, :size
    FROM finance.transactions AS transactions
    WHERE transactions.user_id = :user_id AND transactions.id = :transaction_id
      AND transactions.kind = 'expense' AND transactions.deleted_at IS NULL
    ON CONFLICT (user_id, transaction_id) DO UPDATE
      SET object_key = EXCLUDED.object_key, content_type = EXCLUDED.content_type,
          size_bytes = EXCLUDED.size_bytes, created_at = now()
    RETURNING transaction_id
    """
)

_FIND = text(
    """
    SELECT receipts.object_key, receipts.content_type
    FROM finance.transaction_receipts AS receipts
    JOIN finance.transactions AS transactions
      ON transactions.user_id = receipts.user_id AND transactions.id = receipts.transaction_id
    WHERE receipts.user_id = :user_id AND receipts.transaction_id = :transaction_id
      AND transactions.deleted_at IS NULL
    """
)

_REMOVE = text(
    """
    DELETE FROM finance.transaction_receipts
    WHERE user_id = :user_id AND transaction_id = :transaction_id
    RETURNING object_key
    """
)


class SqlReceiptRepository:
    """Implementa `ReceiptRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user_id: UUID, transaction_id: UUID, key: str, content_type: str, size: int) -> bool:
        params = {
            "user_id": user_id,
            "transaction_id": transaction_id,
            "key": key,
            "content_type": content_type,
            "size": size,
        }
        return (await self._session.execute(_SAVE, params)).scalar_one_or_none() is not None

    async def find(self, user_id: UUID, transaction_id: UUID) -> tuple[str, str] | None:
        params = {"user_id": user_id, "transaction_id": transaction_id}
        row = (await self._session.execute(_FIND, params)).one_or_none()
        return None if row is None else (row.object_key, row.content_type)

    async def remove(self, user_id: UUID, transaction_id: UUID) -> str | None:
        params = {"user_id": user_id, "transaction_id": transaction_id}
        key: str | None = (await self._session.execute(_REMOVE, params)).scalar_one_or_none()
        return key
