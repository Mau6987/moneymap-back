"""Caso de uso de lectura: los avisos recibidos (pantalla Avisos)."""

from datetime import datetime
from uuid import UUID

from app.modules.notify.domain.models import Inbox
from app.modules.notify.domain.ports import InboxRepository


async def get_inbox(user_id: UUID, before: datetime | None, limit: int, inbox: InboxRepository) -> Inbox:
    """Del más nuevo al más viejo. Para la página siguiente, `before` es el `created_at` del último."""
    return await inbox.page(user_id, before, limit)
