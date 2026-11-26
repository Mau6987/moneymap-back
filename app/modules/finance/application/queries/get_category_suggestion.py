"""Caso de uso de lectura: la categoría de la última vez (spec 007, RF-13 y RF-14)."""

from uuid import UUID

from app.modules.finance.domain.models import CategoryRecord
from app.modules.finance.domain.ports import CategoryRepository


async def get_category_suggestion(
    user_id: UUID, description: str, category_type: str, categories: CategoryRepository
) -> CategoryRecord | None:
    """Sin IA (RF-14): la del último movimiento del usuario con esa descripción.

    None si no hay ninguno con una categoría vigente.
    """
    return await categories.last_used_for(user_id, " ".join(description.split()), category_type)
