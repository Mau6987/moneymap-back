"""El SQL de `GET /v1/money-story` (spec 006, RF-5 a RF-7).

Lee lo que guardó el cierre de mes (`app/workers/money_story.py`) y arma el texto
de cada frase con la plantilla de su versión. Una moneda desactivada después del
cierre se sigue devolviendo: la historia ya está guardada.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.reports.domain.models import MoneyStory, StoryHighlight
from app.modules.reports.domain.money_story import render

# Sin `month`, el último mes con historia (RF-6). La moneda principal primero.
_SELECT_MONTH = text(
    """
    SELECT stories.period_start, stories.period_end, stories.currency, currencies.decimals, currencies.symbol,
           stories.income_total, stories.expense_total, stories.savings_total, stories.savings_rate,
           stories.highlights, stories.comparison, stories.generated_at,
           (SELECT jsonb_object_agg(templates.key, templates.body)
              FROM catalog.story_templates AS templates
             WHERE templates.template_version = stories.template_version) AS templates
    FROM reports.money_stories AS stories
    JOIN catalog.currencies AS currencies ON currencies.code = stories.currency
    LEFT JOIN finance.user_settings AS settings ON settings.user_id = stories.user_id
    WHERE stories.user_id = :user_id AND stories.period_type = 'month' AND stories.status = 'ready'
      AND stories.period_start = coalesce(CAST(:month AS date), (
          SELECT max(latest.period_start) FROM reports.money_stories AS latest
          WHERE latest.user_id = :user_id AND latest.period_type = 'month' AND latest.status = 'ready'))
      AND (CAST(:currency AS char(3)) IS NULL OR stories.currency = CAST(:currency AS char(3)))
    ORDER BY stories.currency = settings.main_currency DESC NULLS LAST, stories.currency
    """
)


class SqlMoneyStoryReader:
    """Implementa `MoneyStoryReader` sobre la sesión del usuario (con RLS, RF-21)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def month(self, user_id: UUID, month: date | None, currency: str | None) -> Sequence[MoneyStory]:
        params = {"user_id": user_id, "month": month, "currency": currency}
        rows = (await self._session.execute(_SELECT_MONTH, params)).mappings().all()
        return [_to_story(row) for row in rows]


def _to_story(row: Any) -> MoneyStory:
    def money(column: str) -> Money:
        return Money(row[column], row["currency"], row["decimals"])

    templates: dict[str, str] = row["templates"] or {}
    highlights = tuple(
        StoryHighlight(
            line["key"], line["params"], render(templates.get(line["key"], ""), line["params"], row["symbol"])
        )
        for line in row["highlights"]
    )
    return MoneyStory(
        starts_on=row["period_start"],
        ends_on=row["period_end"],
        income=money("income_total"),
        expense=money("expense_total"),
        savings=money("savings_total"),
        savings_rate=row["savings_rate"],
        comparison=row["comparison"],
        highlights=highlights,
        generated_at=row["generated_at"],
    )
