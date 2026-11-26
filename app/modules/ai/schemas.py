"""Esquemas del registro por voz (spec 012)."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.ai.domain.voice import VoiceEntry

MAX_AUDIO_BYTES = 2 * 1024 * 1024


class VoiceTextCreate(BaseModel):
    """RF-2: la frase escrita en lugar de dictada."""

    text: str = Field(min_length=1, max_length=500, examples=["Gasté 50 en almuerzo con la Visa"])


class VoiceEntryConfirm(BaseModel):
    """RF-9: el movimiento que la app creó con POST /v1/transactions (`source: "voice"`)."""

    transaction_id: UUID


class MovementRead(BaseModel):
    kind: Literal["income", "expense"] | None
    amount: str | None = Field(description="Texto con punto decimal, como en el resto de la API")
    currency: str | None
    category_id: UUID | None
    account_id: UUID | None
    description: str | None
    occurred_on: str | None
    missing: list[str] = Field(description="Lo que la app tiene que pedir antes de guardar")


class ExtractionRead(MovementRead):
    """El primer movimiento arriba y todos los de la frase en `movements`."""

    multiple: bool = Field(default=False, description="La frase tenía más de un movimiento")
    movements: list[MovementRead] = Field(default_factory=list, description="Todos, en el orden en que se dijeron")


class VoiceEntryRead(BaseModel):
    id: UUID
    created_at: datetime
    input_type: Literal["voice", "text"]
    status: Literal["received", "transcribed", "extracted", "confirmed", "discarded", "failed"]
    transcript: str | None
    extraction: ExtractionRead | None
    transaction_id: UUID | None

    @classmethod
    def from_record(cls, entry: VoiceEntry) -> "VoiceEntryRead":
        return cls.model_validate(asdict(entry))
