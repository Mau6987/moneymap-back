"""Caso de uso de escritura: corregir el perfil propio (RF-10 a RF-12)."""

from uuid import UUID

from app.core.errors import Unauthorized
from app.modules.iam.domain.models import ProfileChanges, UserProfile
from app.modules.iam.domain.ports import UserRepository


async def update_me(changes: ProfileChanges, user_id: UUID, users: UserRepository) -> UserProfile:
    """El teléfono, el país y los espacios los normaliza la base; el teléfono inválido, 422."""
    profile = await users.update_profile(user_id, changes)
    if profile is None:
        raise Unauthorized("El token apunta a un usuario que ya no existe")
    return profile
