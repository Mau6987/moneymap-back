"""Onboarding, categorías y recurrentes contra PostgreSQL 16 (spec 007).

RF cubiertos: RF-3 a RF-6, RF-16, RF-17 y RF-19; y el RF-21 de la spec 002.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app
from tests.integration.conftest import RegisteredUser

CASH_ACCOUNT = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _category_id(client: AsyncClient, template_key: str) -> str:
    response = await client.get("/v1/categories")
    return next(item["id"] for item in response.json() if item["template_key"] == template_key)


async def _rule(client: AsyncClient, account_id: str, template_key: str, amount: str, description: str) -> dict:
    response = await client.post(
        "/v1/recurring-rules",
        json={
            "account_id": account_id,
            "category_id": await _category_id(client, template_key),
            "amount": amount,
            "description": description,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_lista_las_categorias_de_gasto_con_su_grupo_icono_y_color_rf6(client: AsyncClient) -> None:
    response = await client.get("/v1/categories", params={"type": "expense"})

    assert response.status_code == 200
    body = response.json()
    assert body
    assert {item["type"] for item in body} == {"expense"}
    assert {item["money_flow_group"] for item in body} == {"needs", "lifestyle"}
    housing = next(item for item in body if item["template_key"] == "housing")
    assert housing["icon"] == "home"
    assert housing["color"].startswith("#")


async def test_distingue_salario_independiente_y_mesada_entre_los_ingresos_rf17(client: AsyncClient) -> None:
    response = await client.get("/v1/categories", params={"type": "income"})

    keys = {item["template_key"] for item in response.json()}
    assert {"salary", "freelance", "family_support"} <= keys
    assert {item["money_flow_group"] for item in response.json()} == {None}


async def test_rechaza_un_tipo_de_categoria_inventado(client: AsyncClient) -> None:
    response = await client.get("/v1/categories", params={"type": "transfer"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_crea_un_gasto_recurrente_en_la_moneda_de_su_cuenta(client: AsyncClient) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()

    rule = await _rule(client, account["id"], "housing", "450.00", "Alquiler")

    assert rule["type"] == "expense"
    assert rule["currency"] == "BOB"
    assert rule["amount"] == "450.00"
    assert rule["frequency"] == "monthly"


async def test_la_cuenta_de_otro_usuario_responde_404_rf16(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    category_id = await _category_id(client, "housing")
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other_client:
        foreign_account = (await other_client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    response = await client.post(
        "/v1/recurring-rules",
        json={
            "account_id": foreign_account["id"],
            "category_id": category_id,
            "amount": "10.00",
            "description": "Ajeno",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_sin_cuenta_va_a_la_cuenta_por_defecto(client: AsyncClient) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()

    response = await client.post(
        "/v1/recurring-rules",
        json={"category_id": await _category_id(client, "salary"), "amount": "3000.00", "description": "Salario"},
    )

    assert response.status_code == 201
    assert response.json()["account_id"] == account["id"]
    assert response.json()["type"] == "income"


async def test_sin_cuenta_y_sin_cuentas_creadas_responde_404(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/recurring-rules",
        json={"category_id": await _category_id(client, "salary"), "amount": "3000.00", "description": "Salario"},
    )

    assert response.status_code == 404


async def test_una_categoria_que_no_existe_responde_404(client: AsyncClient) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()

    response = await client.post(
        "/v1/recurring-rules",
        json={"account_id": account["id"], "category_id": str(uuid4()), "amount": "10.00", "description": "X"},
    )

    assert response.status_code == 404


async def test_el_estado_dice_que_pasos_ya_se_guardaron_rf3(client: AsyncClient) -> None:
    before = (await client.get("/v1/onboarding")).json()
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    await _rule(client, account["id"], "salary", "3000.00", "Salario")
    after = (await client.get("/v1/onboarding")).json()

    assert before == {
        "completed": False,
        "completed_at": None,
        "main_currency": "BOB",
        "accounts": 0,
        "income_rules": 0,
        "expense_rules": 0,
    }
    assert after["accounts"] == 1
    assert after["income_rules"] == 1
    assert after["expense_rules"] == 0
    assert after["completed"] is False


async def test_cierra_el_onboarding_con_ingresos_comprometido_y_safe_to_spend_rf4_rf19(
    client: AsyncClient,
) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    await _rule(client, account["id"], "salary", "3000.00", "Salario")
    await _rule(client, account["id"], "housing", "450.00", "Alquiler")
    await _rule(client, account["id"], "utilities", "130.00", "Servicios")
    await _rule(client, account["id"], "transport", "120.00", "Transporte")

    response = await client.post("/v1/onboarding/complete")

    assert response.status_code == 201
    body = response.json()
    assert body["currency"] == "BOB"
    assert body["income"] == "3000.00"  # texto, nunca número
    assert body["committed"] == "700.00"
    assert body["balance"] == "2500.00"
    assert body["safe_to_spend"] == "1800.00"
    assert body["period_starts_on"] <= body["period_ends_on"]
    assert (await client.get("/v1/onboarding")).json()["completed"] is True


async def test_sin_ingreso_ni_recurrentes_comprometido_queda_en_cero(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)

    body = (await client.post("/v1/onboarding/complete")).json()

    assert body["income"] == "0.00"
    assert body["committed"] == "0.00"
    assert body["safe_to_spend"] == "2500.00"


async def test_cerrar_dos_veces_es_idempotente_rf4(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)

    first = await client.post("/v1/onboarding/complete")
    completed_at = (await client.get("/v1/onboarding")).json()["completed_at"]
    second = await client.post("/v1/onboarding/complete")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert (await client.get("/v1/onboarding")).json()["completed_at"] == completed_at


async def test_sin_cuentas_responde_onboarding_incomplete_rf5(client: AsyncClient) -> None:
    response = await client.post("/v1/onboarding/complete")

    assert response.status_code == 422
    assert response.json()["code"] == "onboarding_incomplete"
    assert response.json()["missing_step"] == "accounts"


async def test_sin_moneda_principal_responde_onboarding_incomplete_rf5(
    api: AsyncClient, registered_user: RegisteredUser
) -> None:
    status = await api.get("/v1/onboarding", headers=registered_user.headers)
    response = await api.post("/v1/onboarding/complete", headers=registered_user.headers)

    assert status.json()["main_currency"] is None
    assert response.status_code == 422
    assert response.json()["missing_step"] == "currency"


async def test_los_paises_traen_su_moneda_y_los_bancos_se_filtran_por_pais(client: AsyncClient) -> None:
    countries = (await client.get("/v1/countries")).json()
    banks = (await client.get("/v1/institutions", params={"country": "BO"})).json()

    assert {"code": "BO", "name": "Bolivia", "currency": "BOB"} in countries
    assert banks
    assert all(bank["code"].startswith("bo.") for bank in banks)
    assert any(bank["short_name"] == "BNB" for bank in banks)


async def test_el_catalogo_pide_token(api: AsyncClient) -> None:
    response = await api.get("/v1/countries")

    assert response.status_code == 401


async def test_el_saldo_inicial_respeta_los_decimales_de_la_moneda(
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    clp_user = await new_financial_user("CLP")
    app.dependency_overrides[get_current_user_id] = lambda: clp_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as clp_client:
        rejected = await clp_client.post(
            "/v1/accounts", json={**CASH_ACCOUNT, "currency": "CLP", "opening_balance": "1000.5"}
        )
        accepted = await clp_client.post(
            "/v1/accounts", json={**CASH_ACCOUNT, "currency": "CLP", "opening_balance": "850000"}
        )
    app.dependency_overrides.clear()

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "invalid_amount"
    assert accepted.status_code == 201
    assert accepted.json()["current_balance"] == "850000"


async def test_un_recurrente_respeta_los_decimales_de_su_cuenta(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)

    response = await client.post(
        "/v1/recurring-rules",
        json={"category_id": await _category_id(client, "housing"), "amount": "10.555", "description": "Alquiler"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_amount"


async def test_rechaza_montos_en_cero_negativos_enormes_o_como_numero(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)
    category_id = await _category_id(client, "housing")

    for amount in ("0", "-10.00", "123456789012345678901", 10.5):
        response = await client.post(
            "/v1/recurring-rules",
            json={"category_id": category_id, "amount": amount, "description": "Alquiler"},
        )
        assert response.status_code == 422, amount
        assert response.json()["code"] == "validation_error"


async def test_rechaza_una_descripcion_vacia_o_demasiado_larga(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)
    category_id = await _category_id(client, "housing")

    for description in ("   ", "x" * 121):
        response = await client.post(
            "/v1/recurring-rules",
            json={"category_id": category_id, "amount": "10.00", "description": description},
        )
        assert response.status_code == 422, description


async def test_limpia_los_espacios_de_la_descripcion(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)

    response = await client.post(
        "/v1/recurring-rules",
        json={
            "category_id": await _category_id(client, "housing"),
            "amount": "10.00",
            "description": "  Mi   alquiler ",
        },
    )

    assert response.json()["description"] == "Mi alquiler"


async def test_rechaza_una_frecuencia_inventada_y_un_pais_mal_escrito(client: AsyncClient) -> None:
    await client.post("/v1/accounts", json=CASH_ACCOUNT)

    rule = await client.post(
        "/v1/recurring-rules",
        json={
            "category_id": await _category_id(client, "housing"),
            "amount": "10.00",
            "description": "Alquiler",
            "frequency": "daily",
        },
    )
    banks = await client.get("/v1/institutions", params={"country": "bolivia"})

    assert rule.status_code == 422
    assert banks.status_code == 422


async def test_un_pais_sin_bancos_devuelve_la_lista_vacia(client: AsyncClient) -> None:
    response = await client.get("/v1/institutions", params={"country": "ZZ"})

    assert response.status_code == 200
    assert response.json() == []


async def test_el_resumen_respeta_una_moneda_sin_decimales(
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    pyg_user = await new_financial_user("PYG")
    app.dependency_overrides[get_current_user_id] = lambda: pyg_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as pyg_client:
        await pyg_client.post("/v1/accounts", json={**CASH_ACCOUNT, "currency": "PYG", "opening_balance": "850000"})
        body = (await pyg_client.post("/v1/onboarding/complete")).json()
    app.dependency_overrides.clear()

    assert body["currency"] == "PYG"
    assert body["balance"] == "850000"
    assert body["safe_to_spend"] == "850000"


async def test_solo_cuentan_los_recurrentes_de_la_moneda_principal(client: AsyncClient) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    await _rule(client, account["id"], "housing", "300.00", "Alquiler")
    switched = await client.put("/v1/me/settings", json={"main_currency": "USD"})

    body = (await client.post("/v1/onboarding/complete")).json()

    # Nunca se suman monedas distintas: lo que está en BOB no entra al resumen en USD.
    assert switched.status_code == 200
    assert body["currency"] == "USD"
    assert body["committed"] == "0.00"
    assert body["balance"] == "0.00"
