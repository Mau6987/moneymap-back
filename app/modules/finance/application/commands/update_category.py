"""Caso de uso de escritura: corregir una categoría (spec 007, RF-10 y RF-11)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.errors import CategoryTypeInUse
from app.modules.finance.domain.models import CategoryChanges, CategoryRecord
from app.modules.finance.domain.ports import CategoryRepository


async def update_category(
    changes: CategoryChanges,
    category_id: UUID,
    user_id: UUID,
    categories: CategoryRepository,
) -> CategoryRecord:
    """Corrige solo lo que se envía; el tipo, solo si no la usa ningún movimiento ni recurrente."""
    if changes.type is not None and await categories.type_in_use(user_id, category_id, changes.type):
        raise CategoryTypeInUse()
    updated = await categories.update(user_id, category_id, changes)
    if updated is None:
        raise NotFound("La categoría no existe")
    return updated
