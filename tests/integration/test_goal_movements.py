"""Los aportes y retiros de las metas para Movimientos (REQ-056), contra PostgreSQL 16."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from httpx import AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app

TRIP = {"name": "Viaje a Cusco", "target_amount": "5000.00", "currency": "BOB", "priority": 1}


async def _goal(client: AsyncClient, **changes: object) -> str:
    response = await client.post("/v1/goals", json={**TRIP, **changes})
    assert response.status_code == 201, response.text
    goal_id: str = response.json()["id"]
    return goal_id


async def _account(client: AsyncClient, name: str = "Efectivo") -> str:
    body = {"name": name, "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}
    response = await client.post("/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def _move(client: AsyncClient, goal: str, kind: str, amount: str, account: str, on: str) -> None:
    path = "contributions" if kind == "contribution" else "withdrawals"
    day = "contributed_on" if kind == "contribution" else "withdrawn_on"
    body = {"amount": amount, "account_id": account, day: on}
    response = await client.post(f"/v1/goals/{goal}/{path}", json=body)
    assert response.status_code == 201, response.text


async def test_lista_aportes_y_retiros_del_mas_reciente_al_mas_viejo(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    await _move(client, goal, "contribution", "300.00", account, "2026-10-01")
    await _move(client, goal, "withdrawal", "100.00", account, "2026-10-05")

    response = await client.get("/v1/goals/movements")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    assert [(m["kind"], m["amount"], m["occurred_on"]) for m in body["items"]] == [
        ("withdrawal", "100.00", "2026-10-05"),
        ("contribution", "300.00", "2026-10-01"),
    ]
    first = body["items"][0]
    assert (first["goal_id"], first["goal_name"], first["account_id"], first["currency"]) == (
        goal,
        "Viaje a Cusco",
        account,
        "BOB",
    )


async def test_filtra_por_cuenta_moneda_y_fechas(client: AsyncClient) -> None:
    cash = await _account(client)
    bank = await _account(client, name="Banco")
    goal = await _goal(client)
    await _move(client, goal, "contribution", "100.00", cash, "2026-09-10")
    await _move(client, goal, "contribution", "200.00", bank, "2026-10-10")

    by_account = (await client.get("/v1/goals/movements", params={"account_id": bank})).json()
    by_dates = (await client.get("/v1/goals/movements", params={"from": "2026-09-01", "to": "2026-09-30"})).json()
    other_currency = (await client.get("/v1/goals/movements", params={"currency": "USD"})).json()

    assert [m["amount"] for m in by_account["items"]] == ["200.00"]
    assert [m["amount"] for m in by_dates["items"]] == ["100.00"]
    assert other_currency["items"] == []


async def test_pagina_con_cursor(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        await _move(client, goal, "contribution", "10.00", account, day)

    first = (await client.get("/v1/goals/movements", params={"limit": 2})).json()
    second = (await client.get("/v1/goals/movements", params={"limit": 2, "cursor": first["next_cursor"]})).json()

    assert [m["occurred_on"] for m in first["items"]] == ["2026-10-03", "2026-10-02"]
    assert [m["occurred_on"] for m in second["items"]] == ["2026-10-01"]
    assert second["next_cursor"] is None


async def test_un_cursor_o_un_rango_invalidos_responden_422(client: AsyncClient) -> None:
    bad_cursor = await client.get("/v1/goals/movements", params={"cursor": "no-es-un-cursor"})
    bad_range = await client.get("/v1/goals/movements", params={"from": "2026-10-10", "to": "2026-10-01"})

    assert (bad_cursor.status_code, bad_cursor.json()["code"]) == (422, "invalid_cursor")
    assert (bad_range.status_code, bad_range.json()["code"]) == (422, "validation_error")


async def test_una_meta_borrada_sigue_en_la_lista(client: AsyncClient) -> None:
    """El dinero salió y volvió a la cuenta aunque la meta ya no exista."""
    account = await _account(client)
    goal = await _goal(client)
    await _move(client, goal, "contribution", "50.00", account, "2026-10-01")
    await _move(client, goal, "withdrawal", "50.00", account, "2026-10-02")
    assert (await client.delete(f"/v1/goals/{goal}")).status_code == 204

    items = (await client.get("/v1/goals/movements")).json()["items"]

    assert [(m["kind"], m["goal_name"]) for m in items] == [
        ("withdrawal", "Viaje a Cusco"),
        ("contribution", "Viaje a Cusco"),
    ]


async def test_no_muestra_los_de_otro_usuario(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    account = await _account(client)
    goal = await _goal(client)
    await _move(client, goal, "contribution", "50.00", account, "2026-10-01")
    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await client.get("/v1/goals/movements")).json()["items"] == []
