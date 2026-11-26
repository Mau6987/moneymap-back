"""Caso de uso de escritura: borrar una categoría (spec 007, RF-12)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.ports import CategoryRepository


async def delete_category(category_id: UUID, user_id: UUID, categories: CategoryRepository) -> None:
    """Borrado lógico: sus movimientos quedan en `sin_categoria` en los reportes."""
    if not await categories.soft_delete(user_id, category_id):
        raise NotFound("La categoría no existe")
