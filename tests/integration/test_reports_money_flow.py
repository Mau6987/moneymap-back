"""Map y Money Flow contra PostgreSQL 16 (spec 004).

RF cubiertos: RF-1 a RF-13, RF-15 y RF-16. RF-14 (`GET /v1/balances`) está en
`test_finance_accounts.py`. Los movimientos van en un mes fijo (`period=2026-03`),
así las pruebas no dependen del día en que corren.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app

MARCH = {"period": "2026-03"}


async def _account(client: AsyncClient, currency: str = "BOB", name: str = "Efectivo") -> str:
    body = {"name": name, "type": "cash", "currency": currency, "opening_balance": "1000.00"}
    response = await client.post("/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def _categories(client: AsyncClient) -> dict[str, tuple[str, str]]:
    """Por clave de plantilla: (id, ingreso o gasto)."""
    items = (await client.get("/v1/categories")).json()
    return {item["template_key"]: (item["id"], item["type"]) for item in items}


async def _move(client: AsyncClient, account: str, category: tuple[str, str], amount: str) -> None:
    """Un movimiento del 10 de marzo."""
    category_id, kind = category
    body = {"kind": kind, "account_id": account, "category_id": category_id, "amount": amount}
    response = await client.post("/v1/transactions", json={**body, "occurred_on": "2026-03-10"})
    assert response.status_code == 201, response.text


async def _contribution(user_id: UUID, amount: str) -> None:
    """Las metas todavía no tienen API (spec 005): se crean directo, con la RLS del usuario."""
    async with user_session(user_id) as session:
        goal_id = (
            await session.execute(
                text(
                    "INSERT INTO goals.goals (user_id, name, target_amount, currency)"
                    " VALUES (:user_id, 'Viaje', 10000, 'BOB') RETURNING id"
                ),
                {"user_id": user_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO goals.goal_contributions (user_id, goal_id, amount, contributed_on)"
                " VALUES (:user_id, :goal_id, :amount, '2026-03-12')"
            ),
            {"user_id": user_id, "goal_id": goal_id, "amount": amount},
        )


async def _march(client: AsyncClient, user_id: UUID) -> str:
    """Ingreso 6000; Necesidades 1500 + 500; Estilo de vida 800; Metas 1000."""
    account = await _account(client)
    categories = await _categories(client)
    await _move(client, account, categories["salary"], "6000.00")
    await _move(client, account, categories["housing"], "1500.00")
    await _move(client, account, categories["utilities"], "500.00")
    await _move(client, account, categories["subscriptions"], "800.00")
    await _contribution(user_id, "1000.00")
    return account


async def test_los_cuatro_grupos_suman_los_ingresos_rf6_rf7(client: AsyncClient, user_id: UUID) -> None:
    await _march(client, user_id)

    response = await client.get("/v1/reports/money-flow", params=MARCH)

    assert response.status_code == 200
    body = response.json()
    assert (body["currency"], body["period_starts_on"], body["period_ends_on"]) == ("BOB", "2026-03-01", "2026-03-31")
    assert body["nodes"] == {
        "income": "6000.00",
        "needs": "2000.00",
        "lifestyle": "800.00",
        "goals": "1000.00",
        "available": "2200.00",
    }


async def test_la_posicion_del_mes_rf1_rf12(client: AsyncClient, user_id: UUID) -> None:
    await _march(client, user_id)

    body = (await client.get("/v1/reports/position", params=MARCH)).json()

    assert body["income"] == "6000.00"
    assert body["expenses"] == "2800.00"
    assert body["saved"] == "1000.00"
    assert body["available_balance"] == "4200.00"  # 1000 de apertura + 6000 − 2800


async def test_el_detalle_de_un_grupo_va_de_mayor_a_menor_rf8(client: AsyncClient, user_id: UUID) -> None:
    await _march(client, user_id)
    categories = await _categories(client)

    body = (await client.get("/v1/reports/money-flow/categories", params={**MARCH, "group": "needs"})).json()

    assert body["group"] == "needs"
    assert [(item["category_id"], item["amount"]) for item in body["items"]] == [
        (categories["housing"][0], "1500.00"),
        (categories["utilities"][0], "500.00"),
    ]


async def test_una_transferencia_no_es_ingreso_ni_gasto_rf9(client: AsyncClient) -> None:
    first = await _account(client)
    second = await _account(client, name="Ahorro")
    transfer = {"kind": "transfer", "account_id": first, "transfer_account_id": second, "amount": "300.00"}
    assert (await client.post("/v1/transactions", json={**transfer, "occurred_on": "2026-03-05"})).status_code == 201

    nodes = (await client.get("/v1/reports/money-flow", params=MARCH)).json()["nodes"]

    assert (nodes["income"], nodes["needs"], nodes["lifestyle"]) == ("0.00", "0.00", "0.00")


async def test_una_categoria_borrada_va_a_sin_categoria_y_sigue_sumando_rf10(
    client: AsyncClient, user_id: UUID
) -> None:
    await _march(client, user_id)
    categories = await _categories(client)
    deleted = await client.delete(f"/v1/categories/{categories['utilities'][0]}")
    assert deleted.status_code == 204

    body = (await client.get("/v1/reports/money-flow/categories", params={**MARCH, "group": "needs"})).json()

    assert body["items"][-1] == {"category_id": None, "name": None, "amount": "500.00"}
    nodes = (await client.get("/v1/reports/money-flow", params=MARCH)).json()["nodes"]
    assert nodes["needs"] == "2000.00"


async def test_cada_moneda_va_por_separado_rf11_rf13(
    client: AsyncClient, user_id: UUID, allow_more_currencies: None
) -> None:
    await _march(client, user_id)
    usd = await _account(client, currency="USD", name="Dólares")
    await _move(client, usd, (await _categories(client))["salary"], "100.00")

    bob = (await client.get("/v1/reports/position", params=MARCH)).json()
    dollars = (await client.get("/v1/reports/position", params={**MARCH, "currency": "USD"})).json()

    assert (bob["currency"], bob["income"]) == ("BOB", "6000.00")
    assert (dollars["currency"], dollars["income"], dollars["saved"]) == ("USD", "100.00", "0.00")
    assert dollars["available_balance"] == "1100.00"


async def test_un_mes_sin_movimientos_da_cero_rf16(client: AsyncClient) -> None:
    response = await client.get("/v1/reports/position", params={"period": "2025-01", "currency": "USD"})

    assert response.status_code == 200
    body = response.json()
    assert (body["income"], body["expenses"], body["saved"], body["available_balance"]) == ("0.00",) * 4


async def test_sin_periodo_usa_el_vigente_rf2_rf3(client: AsyncClient) -> None:
    current = (await client.get("/v1/safe-to-spend")).json()

    body = (await client.get("/v1/reports/money-flow")).json()

    assert body["currency"] == "BOB"
    assert body["period_starts_on"] == current["period_starts_on"]
    assert body["period_ends_on"] == current["period_ends_on"]


async def test_con_on_usa_la_semana_del_usuario_rf17(client: AsyncClient, user_id: UUID) -> None:
    await _march(client, user_id)
    await client.put("/v1/me/settings", json={"period_type": "weekly", "period_start_day": 1})  # de lunes

    week = (await client.get("/v1/reports/money-flow", params={"on": "2026-03-10"})).json()
    next_week = (await client.get("/v1/reports/money-flow", params={"on": "2026-03-17"})).json()
    both = await client.get("/v1/reports/money-flow", params={"on": "2026-03-10", **MARCH})

    assert (week["period_starts_on"], week["period_ends_on"]) == ("2026-03-09", "2026-03-15")
    assert week["nodes"]["income"] == "6000.00"
    assert next_week["nodes"]["income"] == "0.00"
    assert (both.status_code, both.json()["code"]) == (422, "validation_error")


async def test_moneda_inexistente_o_periodo_mal_escrito_responde_422_rf4_rf5(client: AsyncClient) -> None:
    unavailable = await client.get("/v1/reports/position", params={"currency": "XXX"})
    malformed = await client.get("/v1/reports/money-flow", params={"period": "2026-13"})
    wrong_group = await client.get("/v1/reports/money-flow/categories", params={"group": "goals"})

    assert (unavailable.status_code, unavailable.json()["code"]) == (422, "currency_unavailable")
    assert (malformed.status_code, malformed.json()["code"]) == (422, "validation_error")
    assert wrong_group.status_code == 422


async def test_los_movimientos_de_otro_usuario_no_aparecen_rf15(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    await _march(client, user_id)
    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    nodes = (await client.get("/v1/reports/money-flow", params=MARCH)).json()["nodes"]

    assert set(nodes.values()) == {"0.00"}
