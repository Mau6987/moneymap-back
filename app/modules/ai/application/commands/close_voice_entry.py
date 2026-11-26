"""Caso de uso de escritura: confirmar o descartar un dictado (spec 012, RF-9)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.ai.domain.voice import UnknownTransaction, VoiceEntry, VoiceEntryNotReady, VoiceEntryRepository


async def confirm_voice_entry(
    user_id: UUID, entry_id: UUID, transaction_id: UUID, entries: VoiceEntryRepository
) -> VoiceEntry:
    """La app crea el movimiento con POST /v1/transactions y después lo enlaza acá."""
    await _ready(user_id, entry_id, entries, ("extracted",))
    confirmed = await entries.confirm(user_id, entry_id, transaction_id)
    if confirmed is None:
        raise UnknownTransaction()
    return confirmed


async def discard_voice_entry(user_id: UUID, entry_id: UUID, entries: VoiceEntryRepository) -> VoiceEntry:
    """También uno que todavía se procesa: la app lo cancela (BUG-047) y el worker ya no lo pisa.

    La cuota no se devuelve: el procesamiento ya se hizo o se está haciendo.
    """
    await _ready(user_id, entry_id, entries, ("received", "transcribed", "extracted", "failed"))
    return await entries.discard(user_id, entry_id)


async def _ready(user_id: UUID, entry_id: UUID, entries: VoiceEntryRepository, statuses: tuple[str, ...]) -> None:
    entry = await entries.get(user_id, entry_id)
    if entry is None:
        raise NotFound()
    if entry.status not in statuses:
        raise VoiceEntryNotReady()
