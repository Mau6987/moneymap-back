"""`GET /v1/money-story` con historias como las deja el cierre de mes (spec 006, RF-5 a RF-7 y RF-21)."""

import json
from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app

_INSERT_STORY = text(
    """
    INSERT INTO reports.money_stories
        (user_id, period_type, period_start, period_end, status, currency, income_total, expense_total,
         savings_total, savings_rate, highlights, comparison, template_version, generated_at)
    VALUES (:user_id, 'month', CAST(:month AS date), (CAST(:month AS date) + INTERVAL '1 month')::date - 1, 'ready',
            :currency, 5000, 1500, 3500, 0.7, CAST(:highlights AS jsonb), CAST(:comparison AS jsonb), '1', now())
    """
)

SAVED = [{"key": "saved", "params": {"savings": "3500.00", "rate": "70"}}]
COMPARISON = {
    "period": "2026-08",
    "income_total": "4000.00",
    "expense_total": "1000.00",
    "savings_total": "3000.00",
    "goals_contributed": "0.00",
    "top_expense_category": {"name": "Supermercado", "total": "1000.00"},
}


async def _story(user_id: UUID, month: str, currency: str = "BOB", comparison: object = COMPARISON) -> None:
    params = {
        "user_id": user_id,
        "month": date.fromisoformat(month),
        "currency": currency,
        "highlights": json.dumps(SAVED),
        "comparison": None if comparison is None else json.dumps(comparison),
    }
    async with user_session(user_id) as session:
        await session.execute(_INSERT_STORY, params)


async def test_sin_period_devuelve_el_ultimo_mes_con_su_texto_rf5_rf6(client: AsyncClient, user_id: UUID) -> None:
    await _story(user_id, "2026-08-01", comparison=None)
    await _story(user_id, "2026-09-01")

    response = await client.get("/v1/money-story")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "2026-09"
    [story] = body["items"]
    assert story["period_starts_on"] == "2026-09-01"
    assert story["period_ends_on"] == "2026-09-30"
    assert (story["income_total"], story["savings_rate"], story["is_first_month"]) == ("5000.00", "0.7000", False)
    assert story["comparison"] == COMPARISON
    assert story["highlights"] == [{**SAVED[0], "text": "Ahorraste Bs 3500.00: el 70 % de lo que entró."}]


async def test_una_historia_por_moneda_y_filtro_por_moneda_rf7(client: AsyncClient, user_id: UUID) -> None:
    await _story(user_id, "2026-09-01", currency="USD", comparison=None)
    await _story(user_id, "2026-09-01")

    both = (await client.get("/v1/money-story", params={"period": "2026-09"})).json()
    usd = (await client.get("/v1/money-story", params={"period": "2026-09", "currency": "USD"})).json()

    assert [story["currency"] for story in both["items"]] == ["BOB", "USD"]  # la principal primero
    assert [(story["currency"], story["is_first_month"]) for story in usd["items"]] == [("USD", True)]


async def test_sin_historias_responde_una_lista_vacia(client: AsyncClient) -> None:
    assert (await client.get("/v1/money-story")).json() == {"period": None, "items": []}


async def test_cada_usuario_ve_solo_las_suyas_rf21(
    user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    await _story(user_id, "2026-09-01")
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other_client:
        theirs = (await other_client.get("/v1/money-story", params={"period": "2026-09"})).json()
    app.dependency_overrides.clear()

    assert theirs["items"] == []
