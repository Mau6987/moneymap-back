"""Caso de uso de escritura: crear una categoría (spec 007, RF-7 a RF-9)."""

from uuid import UUID

from app.modules.finance.domain.models import CategoryRecord, NewCategory
from app.modules.finance.domain.ports import CategoryRepository


async def create_category(category: NewCategory, user_id: UUID, categories: CategoryRepository) -> CategoryRecord:
    """El nombre repetido en el mismo tipo lo rechaza la base: 409 `category_name_taken`."""
    return await categories.insert(user_id, category)
