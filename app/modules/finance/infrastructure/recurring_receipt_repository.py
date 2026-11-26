"""Qué gasto fijo tiene foto y dónde está (spec 014 + recurrentes), sobre la sesión del usuario (con RLS)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Solo un gasto fijo vivo del usuario: uno borrado o ajeno no inserta
# nada y la API responde 404.
_SAVE = text(
    """
    INSERT INTO finance.recurring_rule_receipts (user_id, rule_id, object_key, content_type, size_bytes)
    SELECT rules.user_id, rules.id, :key, :content_type, :size
    FROM finance.recurring_rules AS rules
    WHERE rules.user_id = :user_id AND rules.id = :rule_id
      AND rules.deleted_at IS NULL
    ON CONFLICT (user_id, rule_id) DO UPDATE
      SET object_key = EXCLUDED.object_key, content_type = EXCLUDED.content_type,
          size_bytes = EXCLUDED.size_bytes, created_at = now()
    RETURNING rule_id
    """
)

_FIND = text(
    """
    SELECT receipts.object_key, receipts.content_type
    FROM finance.recurring_rule_receipts AS receipts
    JOIN finance.recurring_rules AS rules
      ON rules.user_id = receipts.user_id AND rules.id = receipts.rule_id
    WHERE receipts.user_id = :user_id AND receipts.rule_id = :rule_id
      AND rules.deleted_at IS NULL
    """
)

_REMOVE = text(
    """
    DELETE FROM finance.recurring_rule_receipts
    WHERE user_id = :user_id AND rule_id = :rule_id
    RETURNING object_key
    """
)


class SqlRecurringReceiptRepository:
    """Implementa `RecurringReceiptRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user_id: UUID, rule_id: UUID, key: str, content_type: str, size: int) -> bool:
        params = {
            "user_id": user_id,
            "rule_id": rule_id,
            "key": key,
            "content_type": content_type,
            "size": size,
        }
        return (await self._session.execute(_SAVE, params)).scalar_one_or_none() is not None

    async def find(self, user_id: UUID, rule_id: UUID) -> tuple[str, str] | None:
        params = {"user_id": user_id, "rule_id": rule_id}
        row = (await self._session.execute(_FIND, params)).one_or_none()
        return None if row is None else (row.object_key, row.content_type)

    async def remove(self, user_id: UUID, rule_id: UUID) -> str | None:
        params = {"user_id": user_id, "rule_id": rule_id}
        key: str | None = (await self._session.execute(_REMOVE, params)).scalar_one_or_none()
        return key

