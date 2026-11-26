"""Caso de uso de escritura: cambiar las preferencias propias (spec 001, RF-15 y RF-16)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.iam.domain.models import Preferences, PreferencesChanges
from app.modules.iam.domain.ports import PreferencesRepository


async def update_preferences(
    changes: PreferencesChanges, user_id: UUID, preferences: PreferencesRepository
) -> Preferences:
    """Solo lo enviado; un valor que no sirve ya lo rechazó el esquema (RF-16)."""
    updated = await preferences.update(user_id, changes)
    if updated is None:
        raise NotFound("No hay preferencias para este usuario")
    return updated
