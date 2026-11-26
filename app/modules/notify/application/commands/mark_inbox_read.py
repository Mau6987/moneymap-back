"""Caso de uso de escritura: marcar como leídos los avisos (pantalla Avisos)."""

from uuid import UUID

from app.modules.notify.domain.ports import InboxRepository


async def mark_inbox_read(user_id: UUID, inbox: InboxRepository) -> None:
    await inbox.mark_all_read(user_id)
