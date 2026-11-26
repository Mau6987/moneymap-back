"""Caso de uso de lectura: las preferencias propias (spec 001, RF-15)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.iam.domain.models import Preferences
from app.modules.iam.domain.ports import PreferencesRepository


async def get_preferences(user_id: UUID, preferences: PreferencesRepository) -> Preferences:
    found = await preferences.get(user_id)
    if found is None:
        raise NotFound("No hay preferencias para este usuario")
    return found
