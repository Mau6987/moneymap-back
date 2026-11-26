"""Caso de uso de lectura: cómo va un dictado (spec 012, RF-8)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.ai.domain.voice import VoiceEntry, VoiceEntryRepository


async def get_voice_entry(user_id: UUID, entry_id: UUID, entries: VoiceEntryRepository) -> VoiceEntry:
    entry = await entries.get(user_id, entry_id)
    if entry is None:
        raise NotFound()
    return entry
