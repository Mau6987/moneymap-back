"""El SQL de la bandeja de avisos: `notify.notifications` (pantalla Avisos)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notify.domain.models import Inbox, InboxItem

# `notifications_user_idx` es (user_id, created_at DESC): cada página cuesta lo mismo.
_SELECT_PAGE = text(
    """
    SELECT id, type_key, title, body, data, created_at, read_at
    FROM notify.notifications
    WHERE user_id = :user_id
      AND (CAST(:before AS timestamptz) IS NULL OR created_at < CAST(:before AS timestamptz))
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    """
)

_COUNT_UNREAD = text("SELECT count(*) FROM notify.notifications WHERE user_id = :user_id AND read_at IS NULL")

_MARK_ALL_READ = text("UPDATE notify.notifications SET read_at = now() WHERE user_id = :user_id AND read_at IS NULL")


class SqlInboxRepository:
    """Implementa `InboxRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(self, user_id: UUID, before: datetime | None, limit: int) -> Inbox:
        params = {"user_id": user_id, "before": before, "limit": limit}
        rows = (await self._session.execute(_SELECT_PAGE, params)).mappings().all()
        unread: int = (await self._session.execute(_COUNT_UNREAD, {"user_id": user_id})).scalar_one()
        return Inbox(items=[InboxItem(**row) for row in rows], unread=unread)

    async def mark_all_read(self, user_id: UUID) -> None:
        await self._session.execute(_MARK_ALL_READ, {"user_id": user_id})
