"""Sugerencia de categoría por descripción contra PostgreSQL 16 (spec 007, RF-13, RF-14 y RF-16)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app

CASH_ACCOUNT = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}
URL = "/v1/transactions/category-suggestion"


async def _category_id(client: AsyncClient, template_key: str) -> str:
    response = await client.get("/v1/categories")
    return next(item["id"] for item in response.json() if item["template_key"] == template_key)


async def _move(client: AsyncClient, category_id: str, description: str, occurred_on: str) -> None:
    accounts = (await client.get("/v1/accounts")).json()
    account_id = accounts[0]["id"] if accounts else (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()["id"]
    response = await client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": account_id,
            "category_id": category_id,
            "amount": "10.00",
            "occurred_on": occurred_on,
            "description": description,
        },
    )
    assert response.status_code == 201, response.text


async def test_sugiere_la_del_ultimo_movimiento_sin_mayusculas_ni_tildes_rf13(client: AsyncClient) -> None:
    await _move(client, await _category_id(client, "utilities"), "Netflix", "2026-09-01")
    subscriptions = await _category_id(client, "subscriptions")
    await _move(client, subscriptions, "NETFLÍX", "2026-10-01")

    response = await client.get(URL, params={"description": "  netflix ", "type": "expense"})

    assert response.status_code == 200
    assert response.json()["id"] == subscriptions


async def test_sin_coincidencia_responde_204_rf13(client: AsyncClient) -> None:
    await _move(client, await _category_id(client, "subscriptions"), "Netflix", "2026-10-01")

    other_text = await client.get(URL, params={"description": "Spotify", "type": "expense"})
    other_type = await client.get(URL, params={"description": "Netflix", "type": "income"})

    assert (other_text.status_code, other_type.status_code) == (204, 204)
    assert other_text.content == b""


async def test_saltea_las_categorias_borradas(client: AsyncClient) -> None:
    utilities = await _category_id(client, "utilities")
    await _move(client, utilities, "Netflix", "2026-09-01")
    subscriptions = await _category_id(client, "subscriptions")
    await _move(client, subscriptions, "Netflix", "2026-10-01")
    await client.delete(f"/v1/categories/{subscriptions}")

    response = await client.get(URL, params={"description": "Netflix", "type": "expense"})

    assert response.json()["id"] == utilities


async def test_rechaza_la_descripcion_vacia_o_sin_tipo(client: AsyncClient) -> None:
    blank = await client.get(URL, params={"description": "   ", "type": "expense"})
    without_type = await client.get(URL, params={"description": "Netflix"})

    assert (blank.status_code, without_type.status_code) == (422, 422)


async def test_no_mira_los_movimientos_de_otro_usuario_rf16(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other_client:
        await _move(other_client, await _category_id(other_client, "subscriptions"), "Netflix", "2026-10-01")
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    response = await client.get(URL, params={"description": "Netflix", "type": "expense"})

    assert response.status_code == 204
