"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.ai.infrastructure.voice_entries import CeleryVoiceQueue, SqlVoiceEntryRepository


def get_voice_entries(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlVoiceEntryRepository:
    return SqlVoiceEntryRepository(session)


def get_voice_queue() -> CeleryVoiceQueue:
    return CeleryVoiceQueue()
