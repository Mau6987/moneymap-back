"""Caso de uso de lectura: las categorías del usuario (spec 007, RF-6)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.finance.domain.models import CategoryRecord
from app.modules.finance.domain.ports import CategoryRepository


async def get_categories(
    user_id: UUID, category_type: str | None, categories: CategoryRepository
) -> Sequence[CategoryRecord]:
    """Las de gasto con su grupo del Money Flow y las de ingreso, con ícono y color."""
    return await categories.list(user_id, category_type)
