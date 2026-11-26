"""La API no deja un dictado en `received` si la cola no lo acepta (QA BUG-047)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.ai.application.commands.start_voice_entry import start_voice_entry
from app.modules.ai.domain.voice import VoiceEntry, VoiceQueueUnavailable


class _Entries:
    def __init__(self) -> None:
        self.failed: tuple[UUID, UUID, str] | None = None

    async def create(self, user_id: UUID, transcript: str | None) -> VoiceEntry:
        return VoiceEntry(
            id=uuid4(),
            created_at=datetime.now(UTC),
            input_type="voice" if transcript is None else "text",
            status="received",
            transcript=transcript,
            extraction=None,
            transaction_id=None,
        )

    async def fail(self, user_id: UUID, entry_id: UUID, error: str) -> None:
        self.failed = (user_id, entry_id, error)


class _BrokenQueue:
    def enqueue(self, user_id: UUID, entry: VoiceEntry, audio: bytes | None) -> None:
        raise RuntimeError("redis down")


async def test_si_la_cola_falla_la_entrada_queda_failed_y_sin_cuota() -> None:
    user_id = uuid4()
    entries = _Entries()

    with pytest.raises(VoiceQueueUnavailable):
        await start_voice_entry(user_id, b"audio", None, entries, _BrokenQueue())

    assert entries.failed is not None
    assert entries.failed[0] == user_id
    assert entries.failed[2] == "voice.enqueue"
