"""Registro por voz con IA (spec 012): solo HTTP, sin SQL ni reglas.

Ver docs/adr/001-monolito-modular-cqrs.md.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.core.dependencies import get_current_user_id
from app.core.errors import ApiError
from app.modules.ai.application.commands.close_voice_entry import confirm_voice_entry, discard_voice_entry
from app.modules.ai.application.commands.start_voice_entry import start_voice_entry
from app.modules.ai.application.queries.get_voice_entry import get_voice_entry
from app.modules.ai.deps import get_voice_entries, get_voice_queue
from app.modules.ai.domain.voice import VoiceEntryRepository, VoiceQueue
from app.modules.ai.schemas import MAX_AUDIO_BYTES, VoiceEntryConfirm, VoiceEntryRead, VoiceTextCreate

router = APIRouter(prefix="/voice-entries", tags=["ai"])

User = Annotated[UUID, Depends(get_current_user_id)]
Entries = Annotated[VoiceEntryRepository, Depends(get_voice_entries)]
Queue = Annotated[VoiceQueue, Depends(get_voice_queue)]

_AUDIO_BODY = {
    "requestBody": {
        "required": True,
        "content": {"audio/*": {"schema": {"type": "string", "format": "binary"}}},
        "description": "El audio crudo: m4a, ogg, webm o wav, hasta 2 MB y 60 s",
    }
}


class InvalidAudio(ApiError):
    status_code = 422
    code = "invalid_audio"

    def __init__(self) -> None:
        super().__init__("Mandá el audio en el cuerpo, con Content-Type audio/*, hasta 2 MB")


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VoiceEntryRead,
    summary="Dicta un movimiento",
    openapi_extra=_AUDIO_BODY,
)
async def start_voice_entry_route(request: Request, user_id: User, entries: Entries, queue: Queue) -> VoiceEntryRead:
    """RF-1 y RF-3: responde enseguida; el resultado se consulta con GET."""
    if not request.headers.get("content-type", "").startswith("audio/"):
        raise InvalidAudio()
    if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
        raise InvalidAudio()
    audio = await request.body()
    if not 0 < len(audio) <= MAX_AUDIO_BYTES:
        raise InvalidAudio()
    return VoiceEntryRead.from_record(await start_voice_entry(user_id, audio, None, entries, queue))


@router.post("/text", status_code=status.HTTP_202_ACCEPTED, response_model=VoiceEntryRead, summary="Escribe la frase")
async def start_text_entry_route(
    payload: VoiceTextCreate, user_id: User, entries: Entries, queue: Queue
) -> VoiceEntryRead:
    """RF-2: el mismo agente, sin el paso de voz a texto."""
    return VoiceEntryRead.from_record(await start_voice_entry(user_id, None, payload.text, entries, queue))


@router.get("/{entry_id}", response_model=VoiceEntryRead, summary="Cómo va un dictado")
async def get_voice_entry_route(entry_id: UUID, user_id: User, entries: Entries) -> VoiceEntryRead:
    """RF-8: la app consulta hasta que queda en `extracted` o `failed`."""
    return VoiceEntryRead.from_record(await get_voice_entry(user_id, entry_id, entries))


@router.post("/{entry_id}/confirm", response_model=VoiceEntryRead, summary="Enlaza el movimiento guardado")
async def confirm_voice_entry_route(
    entry_id: UUID, payload: VoiceEntryConfirm, user_id: User, entries: Entries
) -> VoiceEntryRead:
    """RF-9."""
    return VoiceEntryRead.from_record(await confirm_voice_entry(user_id, entry_id, payload.transaction_id, entries))


@router.post("/{entry_id}/discard", response_model=VoiceEntryRead, summary="Descarta un dictado")
async def discard_voice_entry_route(entry_id: UUID, user_id: User, entries: Entries) -> VoiceEntryRead:
    """RF-9."""
    return VoiceEntryRead.from_record(await discard_voice_entry(user_id, entry_id, entries))
