"""Los dictados en PostgreSQL, con la RLS del usuario (spec 012)."""

from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.domain.voice import VoiceEntry
from app.modules.ai.infrastructure import audio as audio_store
from app.workers import celery

_CONSUME = text("SELECT billing.try_consume(:user_id, 'ai.voice_entries')")
_INSERT = text(
    "INSERT INTO ai.voice_entries (user_id, input_type, transcript) VALUES (:user_id, :input_type, :transcript)"
    " RETURNING id, created_at, input_type, status, transcript, extraction, transaction_id"
)
_SELECT = text(
    "SELECT id, created_at, input_type, status, transcript, extraction, transaction_id"
    " FROM ai.voice_entries WHERE user_id = :user_id AND id = :entry_id"
)
# RF-9: la transacción tiene que ser del usuario y estar viva; la FK lo vuelve a comprobar.
_CONFIRM = text(
    "UPDATE ai.voice_entries SET status = 'confirmed', transaction_id = :transaction_id, confirmed_at = now()"
    " WHERE user_id = :user_id AND id = :entry_id AND status = 'extracted'"
    " AND EXISTS (SELECT 1 FROM finance.transactions"
    "             WHERE user_id = :user_id AND id = :transaction_id AND deleted_at IS NULL)"
    " RETURNING id, created_at, input_type, status, transcript, extraction, transaction_id"
)
_DISCARD = text(
    "UPDATE ai.voice_entries SET status = 'discarded' WHERE user_id = :user_id AND id = :entry_id"
    " RETURNING id, created_at, input_type, status, transcript, extraction, transaction_id"
)
_FAIL = text(
    "UPDATE ai.voice_entries SET status = 'failed', error = :error"
    " WHERE user_id = :user_id AND id = :entry_id AND status IN ('received', 'transcribed')"
    " RETURNING id"
)
_RELEASE = text("SELECT billing.release(:user_id, 'ai.voice_entries')")


def _entry(row: RowMapping) -> VoiceEntry:
    extraction: dict[str, Any] | None = row["extraction"]
    return VoiceEntry(
        id=row["id"],
        created_at=row["created_at"],
        input_type=row["input_type"],
        status=row["status"],
        transcript=row["transcript"],
        extraction=extraction,
        transaction_id=row["transaction_id"],
    )


class SqlVoiceEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, transcript: str | None) -> VoiceEntry | None:
        if not (await self._session.execute(_CONSUME, {"user_id": user_id})).scalar_one():
            return None
        params = {"user_id": user_id, "input_type": "voice" if transcript is None else "text", "transcript": transcript}
        entry = _entry((await self._session.execute(_INSERT, params)).mappings().one())
        # Guardado antes de encolarlo: si no, el worker podría no encontrarlo.
        await self._session.commit()
        return entry

    async def get(self, user_id: UUID, entry_id: UUID) -> VoiceEntry | None:
        row = (await self._session.execute(_SELECT, {"user_id": user_id, "entry_id": entry_id})).mappings().first()
        return _entry(row) if row else None

    async def confirm(self, user_id: UUID, entry_id: UUID, transaction_id: UUID) -> VoiceEntry | None:
        params = {"user_id": user_id, "entry_id": entry_id, "transaction_id": transaction_id}
        row = (await self._session.execute(_CONFIRM, params)).mappings().first()
        return _entry(row) if row else None

    async def discard(self, user_id: UUID, entry_id: UUID) -> VoiceEntry:
        params = {"user_id": user_id, "entry_id": entry_id}
        return _entry((await self._session.execute(_DISCARD, params)).mappings().one())

    async def fail(self, user_id: UUID, entry_id: UUID, error: str) -> None:
        """Only a still-pending entry is failed; one already processed stays."""
        params = {"user_id": user_id, "entry_id": entry_id, "error": error}
        updated = (await self._session.execute(_FAIL, params)).first()
        if updated is None:
            return
        await self._session.execute(_RELEASE, {"user_id": user_id})
        await self._session.commit()


class CeleryVoiceQueue:
    """El audio va aparte, en memoria (`audio.put`): en la cola solo los ids (RF-10)."""

    def enqueue(self, user_id: UUID, entry: VoiceEntry, audio: bytes | None) -> None:
        if audio is not None:
            audio_store.put(entry.id, audio)
        # ponytail: si Redis no responde, el dictado queda en `received` con la cuota descontada.
        # Por nombre: importar app.workers.voice desde acá arma un import circular con los routers.
        args = [str(entry.id), entry.created_at.isoformat(), str(user_id)]
        celery.send_task("ai.process_voice_entry", args=args)
