"""Cuentas y totales contra PostgreSQL 16 (spec 002).

RF cubiertos: RF-3, RF-4, RF-5, RF-9, RF-15 y RF-19.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app
from tests.integration.conftest import RegisterBody

CASH_ACCOUNT = {"name": "Efectivo Bs", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}
CARD_ACCOUNT = {
    "name": "Tarjeta BNB",
    "type": "card",
    "currency": "BOB",
    "institution_code": "bo.bnb",
    "last4": "1234",
}


async def test_crea_una_cuenta_en_efectivo_con_su_saldo_inicial_rf3(client: AsyncClient) -> None:
    response = await client.post("/v1/accounts", json=CASH_ACCOUNT)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Efectivo Bs"
    assert body["type"] == "cash"
    assert body["currency"] == "BOB"
    assert body["current_balance"] == "2500.00"  # los decimales de la moneda, como texto
    assert body["is_default"] is True  # la primera cuenta lo es sola


async def test_guarda_el_banco_y_los_ultimos_cuatro_digitos_de_la_tarjeta_rf3(
    client: AsyncClient, user_id: UUID
) -> None:
    response = await client.post("/v1/accounts", json=CARD_ACCOUNT)

    assert response.status_code == 201
    async with user_session(user_id) as session:
        card = (
            await session.execute(
                text("SELECT institution_code, last4 FROM finance.cards WHERE account_id = :account_id"),
                {"account_id": response.json()["id"]},
            )
        ).one()
    assert card == ("bo.bnb", "1234")


async def test_rechaza_una_tarjeta_sin_los_ultimos_cuatro_rf3(client: AsyncClient) -> None:
    """QA BUG-052: una tarjeta no se crea sin sus últimos 4 dígitos."""
    response = await client.post("/v1/accounts", json={**CARD_ACCOUNT, "last4": None})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_rechaza_una_moneda_que_no_esta_en_el_catalogo_rf4(client: AsyncClient) -> None:
    response = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "currency": "XXX"})

    assert response.status_code == 422
    assert response.json()["code"] == "currency_unavailable"


async def test_respeta_el_limite_de_tarjetas_del_plan_rf5(client: AsyncClient) -> None:
    first = await client.post("/v1/accounts", json=CARD_ACCOUNT)
    assert first.status_code == 201

    second = await client.post("/v1/accounts", json={**CARD_ACCOUNT, "name": "Tarjeta BCP", "last4": "5678"})

    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "plan_limit"
    assert body["feature"] == "finance.cards"


async def test_respeta_el_limite_de_monedas_del_plan_rf9(client: AsyncClient) -> None:
    first = await client.post("/v1/accounts", json=CASH_ACCOUNT)
    assert first.status_code == 201

    second = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "name": "Caja USD", "currency": "USD"})

    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "plan_limit"
    assert body["feature"] == "finance.currencies"


async def test_devuelve_una_fila_por_moneda_con_la_principal_primero_rf15(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_ACCOUNT)).status_code == 201
    assert (await client.post("/v1/accounts", json=CARD_ACCOUNT)).status_code == 201

    response = await client.get("/v1/balances")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1  # las dos cuentas están en BOB: una sola fila
    assert rows[0] == {
        "currency": "BOB",
        "is_main_currency": True,
        "total": "2500.00",
        "cash_total": "2500.00",
        "card_total": "0.00",
        "accounts": 2,
    }


async def test_no_expone_las_cuentas_de_otro_usuario_rf19(
    client: AsyncClient,
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    assert (await client.post("/v1/accounts", json=CASH_ACCOUNT)).status_code == 201
    assert len((await client.get("/v1/balances")).json()) == 1

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await client.get("/v1/balances")).json() == []


async def test_rechaza_lo_que_no_cumple_el_contrato(client: AsyncClient) -> None:
    """Constitución §2: el monto viaja como texto y la moneda es un código ISO 4217."""
    as_number = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "opening_balance": 2500.0})
    assert as_number.status_code == 422
    assert as_number.json()["code"] == "validation_error"

    lowercase = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "currency": "bob"})
    assert lowercase.status_code == 422
    assert lowercase.json()["errors"][0]["field"] == "currency"

    unknown_type = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "type": "credit"})
    assert unknown_type.status_code == 422
    assert unknown_type.json()["errors"][0]["field"] == "type"


async def test_el_endpoint_autenticado_usa_el_token_de_verdad(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    """La identidad de la spec 001 ya existe: el 501 de `get_current_user_id` ya no está."""
    registered = await api.post("/v1/auth/register", json=await register_body())
    assert registered.status_code == 201
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    response = await api.post("/v1/accounts", json=CASH_ACCOUNT, headers=headers)

    assert response.status_code == 201
    assert response.json()["currency"] == "BOB"


async def test_corrige_el_nombre_sin_tocar_el_saldo_rf14(client: AsyncClient) -> None:
    created = await client.post("/v1/accounts", json=CASH_ACCOUNT)
    account_id = created.json()["id"]

    response = await client.patch(f"/v1/accounts/{account_id}", json={"name": "Caja nueva"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Caja nueva"
    assert body["currency"] == "BOB"
    assert body["current_balance"] == "2500.00"


async def test_corrige_el_saldo_inicial_y_el_saldo_se_mueve_por_la_diferencia_bug036(client: AsyncClient) -> None:
    created = await client.post("/v1/accounts", json=CASH_ACCOUNT)
    account_id = created.json()["id"]
    expense = {"kind": "expense", "account_id": account_id, "amount": "500.00", "occurred_on": "2026-10-20"}
    categories = (await client.get("/v1/categories")).json()
    expense["category_id"] = next(c["id"] for c in categories if c["type"] == "expense")
    expense["description"] = "Almuerzo"
    expense["source"] = "manual"
    assert (await client.post("/v1/transactions", json=expense)).status_code == 201

    response = await client.patch(f"/v1/accounts/{account_id}", json={"opening_balance": "3000.00"})

    assert response.status_code == 200
    # 2500 - 500 = 2000; el saldo inicial sube 500, el saldo también: 2500.
    assert response.json()["current_balance"] == "2500.00"


async def test_un_saldo_inicial_con_decimales_de_mas_responde_422_bug036(client: AsyncClient) -> None:
    created = await client.post("/v1/accounts", json=CASH_ACCOUNT)

    response = await client.patch(f"/v1/accounts/{created.json()['id']}", json={"opening_balance": "10.001"})

    assert response.status_code == 422


async def test_corrige_la_moneda_mientras_la_cuenta_no_se_haya_usado_rf14(client: AsyncClient) -> None:
    created = await client.post("/v1/accounts", json=CASH_ACCOUNT)
    account_id = created.json()["id"]

    response = await client.patch(f"/v1/accounts/{account_id}", json={"currency": "USD"})

    assert response.status_code == 200
    assert response.json()["currency"] == "USD"


async def test_no_cambia_la_moneda_de_una_cuenta_ya_usada_rf14(client: AsyncClient, user_id: UUID) -> None:
    created = await client.post("/v1/accounts", json=CASH_ACCOUNT)
    account_id = created.json()["id"]
    async with user_session(user_id) as session:
        category_id = (
            await session.execute(
                text("SELECT id FROM finance.categories WHERE user_id = :user_id AND kind = 'expense' LIMIT 1"),
                {"user_id": user_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO finance.transactions"
                " (user_id, kind, account_id, category_id, amount, currency, occurred_on)"
                " VALUES (:user_id, 'expense', :account_id, :category_id, '10.00', 'BOB', current_date)"
            ),
            {"user_id": user_id, "account_id": account_id, "category_id": category_id},
        )

    response = await client.patch(f"/v1/accounts/{account_id}", json={"currency": "USD"})

    assert response.status_code == 409
    assert response.json()["code"] == "account_currency_locked"
    # Y queda como estaba.
    still = await client.get("/v1/balances")
    assert still.json()[0]["currency"] == "BOB"


async def test_una_cuenta_que_no_existe_o_no_es_del_usuario_responde_404_rf14(client: AsyncClient) -> None:
    response = await client.patch(f"/v1/accounts/{uuid4()}", json={"name": "Caja"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
