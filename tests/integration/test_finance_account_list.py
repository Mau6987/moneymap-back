"""La lista de cuentas y los errores de alta que antes eran 500 (spec 002).

RF cubiertos: RF-23, RF-24 y RF-25.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from httpx import AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app

CASH_ACCOUNT = {"name": "Efectivo Bs", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}
CARD_ACCOUNT = {
    "name": "Tarjeta BNB",
    "type": "card",
    "currency": "BOB",
    "institution_code": "bo.bnb",
    "last4": "1234",
}


async def test_lista_las_cuentas_con_la_de_por_defecto_primero_rf23(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_ACCOUNT)).status_code == 201
    assert (await client.post("/v1/accounts", json=CARD_ACCOUNT)).status_code == 201

    response = await client.get("/v1/accounts")

    assert response.status_code == 200
    cash, card = response.json()
    assert (cash["name"], cash["is_default"], cash["current_balance"]) == ("Efectivo Bs", True, "2500.00")
    assert (cash["institution_code"], cash["last4"]) == (None, None)
    assert (card["name"], card["institution_code"], card["last4"]) == ("Tarjeta BNB", "bo.bnb", "1234")


async def test_la_lista_no_muestra_las_cuentas_de_otro_usuario_rf23(
    client: AsyncClient,
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    assert (await client.post("/v1/accounts", json=CASH_ACCOUNT)).status_code == 201

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await client.get("/v1/accounts")).json() == []


async def test_un_nombre_repetido_responde_409_rf24(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_ACCOUNT)).status_code == 201

    response = await client.post("/v1/accounts", json={**CASH_ACCOUNT, "name": "EFECTIVO bs"})

    assert response.status_code == 409
    assert response.json()["code"] == "account_name_taken"


async def test_un_banco_que_no_esta_en_el_catalogo_responde_422_rf25(client: AsyncClient) -> None:
    response = await client.post("/v1/accounts", json={**CARD_ACCOUNT, "institution_code": "bo.inventado"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    # Sin cuenta a medias: la tarjeta y su cuenta se crean en la misma transacción.
    assert (await client.get("/v1/accounts")).json() == []


async def test_archivar_oculta_la_cuenta_y_libera_el_cupo(client: AsyncClient) -> None:
    cash = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()["id"]
    card = (await client.post("/v1/accounts", json=CARD_ACCOUNT)).json()["id"]

    archived = await client.patch(f"/v1/accounts/{card}", json={"archived": True})

    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert [account["id"] for account in (await client.get("/v1/accounts")).json()] == [cash]
    assert [account["id"] for account in (await client.get("/v1/accounts?archived=true")).json()] == [card]
    # El plan gratuito permite una tarjeta: archivada, libera el cupo.
    other = await client.post("/v1/accounts", json={**CARD_ACCOUNT, "name": "Otra", "last4": "9999"})
    assert other.status_code == 201
    restored = await client.patch(f"/v1/accounts/{card}", json={"archived": False})
    assert (restored.status_code, restored.json()["code"]) == (409, "plan_limit")


async def test_archivar_la_de_por_defecto_pasa_la_marca_a_otra(client: AsyncClient) -> None:
    cash = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()["id"]
    card = (await client.post("/v1/accounts", json=CARD_ACCOUNT)).json()["id"]

    await client.patch(f"/v1/accounts/{cash}", json={"archived": True})
    restored = await client.patch(f"/v1/accounts/{cash}", json={"archived": False})

    accounts = {account["id"]: account for account in (await client.get("/v1/accounts")).json()}
    assert accounts[card]["is_default"] is True
    assert (restored.status_code, restored.json()["archived_at"], restored.json()["is_default"]) == (200, None, False)
