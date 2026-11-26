"""Presupuestos por categoría (spec 009, RF-1 a RF-9) contra la base real."""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session


async def _category(user_id: UUID, template_key: str) -> str:
    async with user_session(user_id) as session:
        category_id = (
            await session.execute(
                text("SELECT id FROM finance.categories WHERE user_id = :user_id AND template_key = :key"),
                {"user_id": user_id, "key": template_key},
            )
        ).scalar_one()
    return str(category_id)


async def _expense(user_id: UUID, amount: str, months_ago: int = 0) -> None:
    """Un gasto en Supermercado en Bs; con `months_ago`, el día 1 de ese mes."""
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)"
                " SELECT :user_id, 'Efectivo', 'cash', 'BOB', 100000"
                " WHERE NOT EXISTS (SELECT 1 FROM finance.accounts WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        await session.execute(
            text(
                "INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)"
                " SELECT :user_id, 'expense', accounts.id, categories.id, CAST(:amount AS numeric),"
                "  CASE WHEN CAST(:months_ago AS int) = 0 THEN (now() AT TIME ZONE 'America/La_Paz')::date"
                "  ELSE (date_trunc('month', now() AT TIME ZONE 'America/La_Paz')"
                "        - make_interval(months => CAST(:months_ago AS int)))::date END"
                " FROM finance.accounts AS accounts, finance.categories AS categories"
                " WHERE accounts.user_id = :user_id AND categories.user_id = :user_id"
                " AND categories.template_key = 'groceries'"
            ),
            {"user_id": user_id, "amount": amount, "months_ago": months_ago},
        )


async def test_lo_gastado_del_mes_en_la_moneda_del_presupuesto_rf3_rf4(client: AsyncClient, user_id: UUID) -> None:
    groceries = await _category(user_id, "groceries")
    await _expense(user_id, "240")
    await _expense(user_id, "999", months_ago=1)  # el mes pasado no cuenta

    created = await client.post("/v1/budgets", json={"category_id": groceries, "amount": "400"})
    usd = await client.post("/v1/budgets", json={"category_id": groceries, "amount": "50", "currency": "USD"})

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["currency"], body["amount"], body["spent"], body["remaining"], body["percent_used"]) == (
        "BOB",
        "400.00",
        "240.00",
        "160.00",
        60,
    )
    assert set(body["pace"]) == {"status", "projected_total"}
    assert usd.status_code == 201, usd.text
    assert usd.json()["spent"] == "0.00"  # un gasto en Bs no suma al de USD
    listed = (await client.get("/v1/budgets")).json()
    assert [(item["currency"], item["spent"]) for item in listed] == [("BOB", "240.00"), ("USD", "0.00")]


async def test_el_gasto_dia_por_dia_para_la_linea_del_mes(client: AsyncClient, user_id: UUID) -> None:
    groceries = await _category(user_id, "groceries")
    await _expense(user_id, "240")
    await _expense(user_id, "10.50")
    await _expense(user_id, "999", months_ago=1)

    body = (await client.post("/v1/budgets", json={"category_id": groceries, "amount": "400"})).json()

    [today] = body["daily"]
    assert (today["spent"], today["cumulative"]) == ("250.50", "250.50")
    assert body["period_starts_on"] <= today["on"] <= body["period_ends_on"]


async def test_errores_rf1(client: AsyncClient, user_id: UUID) -> None:
    groceries = await _category(user_id, "groceries")
    await client.post("/v1/budgets", json={"category_id": groceries, "amount": "400"})

    repeated = await client.post("/v1/budgets", json={"category_id": groceries, "amount": "100"})
    income = await client.post("/v1/budgets", json={"category_id": await _category(user_id, "salary"), "amount": "1"})
    decimals = await client.post(
        "/v1/budgets", json={"category_id": await _category(user_id, "transport"), "amount": "1.001"}
    )

    assert (repeated.status_code, repeated.json()["code"]) == (409, "budget_exists")
    assert (income.status_code, income.json()["code"]) == (422, "validation_error")
    assert (decimals.status_code, decimals.json()["code"]) == (422, "invalid_amount")


async def test_el_gratuito_permite_3_rf8(client: AsyncClient, user_id: UUID) -> None:
    for key in ("groceries", "transport", "restaurants"):
        response = await client.post("/v1/budgets", json={"category_id": await _category(user_id, key), "amount": "1"})
        assert response.status_code == 201, response.text

    fourth = await client.post("/v1/budgets", json={"category_id": await _category(user_id, "gifts"), "amount": "1"})

    assert (fourth.status_code, fourth.json()["code"], fourth.json()["feature"]) == (
        409,
        "plan_limit",
        "planning.budgets",
    )


async def test_corregir_y_borrar_rf2(client: AsyncClient, user_id: UUID) -> None:
    created = (
        await client.post("/v1/budgets", json={"category_id": await _category(user_id, "groceries"), "amount": "400"})
    ).json()

    updated = await client.patch(f"/v1/budgets/{created['id']}", json={"amount": "500"})
    deleted = await client.delete(f"/v1/budgets/{created['id']}")

    assert (updated.status_code, updated.json()["amount"]) == (200, "500.00")
    assert deleted.status_code == 204
    assert (await client.get("/v1/budgets")).json() == []
    assert (await client.delete(f"/v1/budgets/{created['id']}")).status_code == 404


async def test_los_avisos_se_apagan_por_presupuesto_rf18(client: AsyncClient, user_id: UUID) -> None:
    groceries = await _category(user_id, "groceries")
    created = (await client.post("/v1/budgets", json={"category_id": groceries, "amount": "400"})).json()

    updated = await client.patch(f"/v1/budgets/{created['id']}", json={"alert_at_100": False})
    empty = await client.patch(f"/v1/budgets/{created['id']}", json={})

    assert (created["alert_at_80"], created["alert_at_100"]) == (True, True)
    assert updated.status_code == 200, updated.text
    assert (updated.json()["amount"], updated.json()["alert_at_80"], updated.json()["alert_at_100"]) == (
        "400.00",
        True,
        False,
    )
    assert (empty.status_code, empty.json()["code"]) == (422, "validation_error")


async def test_borrar_la_categoria_borra_su_presupuesto_rf9(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/categories", json={"name": "Mascota", "type": "expense", "money_flow_group": "needs"}
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]
    await client.post("/v1/budgets", json={"category_id": category_id, "amount": "100"})

    assert (await client.delete(f"/v1/categories/{category_id}")).status_code == 204
    assert (await client.get("/v1/budgets")).json() == []
    again = await client.post("/v1/budgets", json={"category_id": category_id, "amount": "100"})
    assert again.status_code == 404  # en una categoría borrada no se crea
