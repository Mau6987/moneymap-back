"""Caso de uso de lectura: la Money Story de un mes (spec 006, RF-5 a RF-7)."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.modules.reports.domain.models import MoneyStory
from app.modules.reports.domain.ports import MoneyStoryReader


async def get_money_story(
    user_id: UUID, month: date | None, currency: str | None, reader: MoneyStoryReader
) -> tuple[date | None, Sequence[MoneyStory]]:
    """Sin `month`, el último mes cerrado con historia (RF-6). Sin historias, una lista vacía."""
    stories = await reader.month(user_id, month, currency)
    return (stories[0].starts_on if stories else month), stories
