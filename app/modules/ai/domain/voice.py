"""El dictado como lo ve la API (spec 012), sus puertos y sus errores."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.errors import ApiError


@dataclass(frozen=True, slots=True)
class VoiceEntry:
    id: UUID
    created_at: datetime
    input_type: str  # voice o text
    status: str  # received, transcribed, extracted, confirmed, discarded o failed
    transcript: str | None
    extraction: dict[str, Any] | None
    transaction_id: UUID | None


class VoiceEntryRepository(Protocol):
    async def create(self, user_id: UUID, transcript: str | None) -> VoiceEntry | None:
        """Descuenta la cuota y crea el dictado, y lo deja guardado. None si no queda cuota."""
        ...

    async def get(self, user_id: UUID, entry_id: UUID) -> VoiceEntry | None: ...

    async def confirm(self, user_id: UUID, entry_id: UUID, transaction_id: UUID) -> VoiceEntry | None:
        """None si la transacción no es del usuario o ya no existe."""
        ...

    async def discard(self, user_id: UUID, entry_id: UUID) -> VoiceEntry: ...

    async def fail(self, user_id: UUID, entry_id: UUID, error: str) -> None:
        """Marks an entry that never reached the worker as failed and releases its quota."""
        ...


class VoiceQueue(Protocol):
    def enqueue(self, user_id: UUID, entry: VoiceEntry, audio: bytes | None) -> None: ...


class VoiceQueueUnavailable(ApiError):
    """The queue could not take the entry: it is failed and its quota released."""

    status_code = 503
    code = "voice_queue_unavailable"

    def __init__(self) -> None:
        super().__init__("El servicio de dictado no está disponible: probá de nuevo en un rato")


class VoiceQuotaExceeded(ApiError):
    """RF-3: se acabaron los dictados del mes del plan."""

    status_code = 409
    code = "plan_limit"

    def __init__(self) -> None:
        super().__init__("Ya usaste los registros por voz de este mes en tu plan")

    def to_problem(self) -> dict[str, Any]:
        return {**super().to_problem(), "feature": "ai.voice_entries"}


class VoiceEntryNotReady(ApiError):
    """RF-9: solo se confirma o descarta un dictado que terminó de procesarse."""

    status_code = 409
    code = "voice_entry_not_ready"

    def __init__(self) -> None:
        super().__init__("El dictado todavía se está procesando o ya se cerró")


class UnknownTransaction(ApiError):
    status_code = 422
    code = "validation_error"

    def __init__(self) -> None:
        super().__init__("Ese movimiento no existe")
