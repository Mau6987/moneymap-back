"""Caso de uso de lectura: el perfil de quien está usando la app (RF-9)."""

from uuid import UUID

from app.core.errors import Unauthorized
from app.modules.iam.domain.models import UserProfile
from app.modules.iam.domain.ports import UserRepository


async def get_me(user_id: UUID, users: UserRepository) -> UserProfile:
    """El perfil del usuario del token, con lo que la base devolvió."""
    profile = await users.get_profile(user_id)
    if profile is None:
        raise Unauthorized("El token apunta a un usuario que ya no existe")
    return profile
