"""Caso de uso de escritura: empezar un dictado o una frase escrita (spec 012, RF-1 a RF-3)."""

from uuid import UUID

from app.modules.ai.domain.voice import (
    VoiceEntry,
    VoiceEntryRepository,
    VoiceQueue,
    VoiceQueueUnavailable,
    VoiceQuotaExceeded,
)


async def start_voice_entry(
    user_id: UUID, audio: bytes | None, phrase: str | None, entries: VoiceEntryRepository, queue: VoiceQueue
) -> VoiceEntry:
    """Con audio se transcribe y se extrae; con la frase escrita, solo se extrae."""
    entry = await entries.create(user_id, phrase)
    if entry is None:
        raise VoiceQuotaExceeded()
    try:
        queue.enqueue(user_id, entry, audio)
    except Exception:
        # The quota was already consumed; fail the entry so it does not stay
        # "received" forever and return it to the user.
        await entries.fail(user_id, entry.id, "voice.enqueue")
        raise VoiceQueueUnavailable() from None
    return entry
