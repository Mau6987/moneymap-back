"""Can I Afford It? contra PostgreSQL 16 (spec 005, RF-11 a RF-19).

El dinero disponible es Safe to Spend más los ingresos que faltan llegar en el
periodo, menos el gasto variable que falta gastar. El tiempo sale del sobrante
mensual, no solo de los aportes a metas.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient

CASH = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}


async def _check(client: AsyncClient, amount: str, **extra: object) -> dict[str, Any]:
    response = await client.post("/v1/affordability-checks", json={"amount": amount, "currency": "BOB", **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _account(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/v1/accounts", json=CASH)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


async def _category_id(client: AsyncClient, template_key: str) -> str:
    response = await client.get("/v1/categories")
    return next(item["id"] for item in response.json() if item["template_key"] == template_key)


async def _rule(client: AsyncClient, account_id: str, template_key: str, amount: str) -> dict[str, Any]:
    """Un recurrente mensual que vence hoy, dentro del periodo vigente."""
    response = await client.post(
        "/v1/recurring-rules",
        json={
            "account_id": account_id,
            "category_id": await _category_id(client, template_key),
            "amount": amount,
            "description": template_key,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _two_goals(client: AsyncClient) -> None:
    """Safe to Spend de 500: 1000 menos 300 al Fondo (prioridad 1) y 200 al Viaje (3)."""
    for name, priority, amount in [("Fondo", 1, "300.00"), ("Viaje", 3, "200.00")]:
        goal = {"name": name, "target_amount": "5000.00", "currency": "BOB", "priority": priority}
        created = (await client.post("/v1/goals", json=goal)).json()
        contribution = await client.post(f"/v1/goals/{created['id']}/contributions", json={"amount": amount})
        assert contribution.status_code == 201


async def test_si_entra_en_el_disponible_es_affordable_y_no_guarda_nada_rf12_rf15(client: AsyncClient) -> None:
    await _account(client)

    # PRD §6.13: con 1000 libres, una compra de 800 deja 200.
    body = await _check(client, "800.00")

    assert (body["verdict"], body["available"], body["available_after"]) == ("affordable", "1000.00", "200.00")
    assert (body["income_in_period"], body["remaining_variable_spending"]) == ("0.00", "0.00")
    assert (body["goal_impacts"], body["estimated_on"]) == ([], None)
    assert (await client.get("/v1/transactions")).json()["items"] == []
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "1000.00"


async def test_el_sueldo_que_falta_llegar_cuenta_para_la_compra_rf12(client: AsyncClient) -> None:
    account = await _account(client)
    await _rule(client, account["id"], "salary", "3000.00")

    body = await _check(client, "3500.00")

    # 1000 de saldo + 3000 del sueldo: alcanza y quedan 500.
    assert (body["verdict"], body["safe_to_spend"], body["income_in_period"]) == ("affordable", "1000.00", "3000.00")
    assert (body["available"], body["available_after"]) == ("4000.00", "500.00")


async def test_sin_metas_estima_la_fecha_con_el_sobrante_mensual_rf14(client: AsyncClient) -> None:
    account = await _account(client)
    await _rule(client, account["id"], "salary", "3000.00")

    body = await _check(client, "5000.00")

    # Faltan 1000 y el sobrante es de 3000 al mes: hay fecha aunque no haya metas.
    assert (body["verdict"], body["goal_impacts"]) == ("not_yet", [])
    assert body["estimated_on"] is not None
    assert Decimal(body["assumptions"]["monthly_surplus"]) > 0
    assert Decimal(body["assumptions"]["monthly_income"]) >= 3000
    assert body["assumptions"]["monthly_goals"] == "0.00"
    assert len(body["projection"]) >= 2
    assert body["projection"][0]["balance"] == "4000.00"


async def test_el_excedente_se_informa_por_meta_pero_el_veredicto_sigue_siendo_no_rf13(
    client: AsyncClient,
) -> None:
    await _account(client)
    await _two_goals(client)

    body = await _check(client, "750.00")

    # 250 por encima del disponible: saldrían del Viaje (200) y del Fondo (50),
    # pero las metas son una obligación y el veredicto no las usa para pagar.
    assert (body["verdict"], body["available"], body["available_after"]) == ("not_yet", "500.00", "-250.00")
    impacts = [(impact["name"], impact["amount"]) for impact in body["goal_impacts"]]
    assert impacts == [("Viaje", "200.00"), ("Fondo", "50.00")]
    assert body["estimated_on"] is None  # las metas consumen todo el sobrante


async def test_sin_metas_en_la_moneda_responde_igual_rf16_rf19(client: AsyncClient) -> None:
    await _account(client)

    in_usd = await _check(client, "10.00", currency="USD")

    # Sin cuentas en dólares: disponible en cero de esa moneda, nunca convertido.
    assert (in_usd["currency"], in_usd["available"], in_usd["verdict"]) == ("USD", "0.00", "not_yet")
    assert (in_usd["goal_impacts"], in_usd["estimated_on"]) == ([], None)


async def test_la_categoria_tiene_que_ser_de_gasto(client: AsyncClient) -> None:
    await _account(client)
    income = (await client.get("/v1/categories", params={"type": "income"})).json()[0]["id"]
    expense = (await client.get("/v1/categories", params={"type": "expense"})).json()[0]["id"]

    wrong = await client.post(
        "/v1/affordability-checks", json={"amount": "10.00", "currency": "BOB", "category_id": income}
    )

    assert (wrong.status_code, wrong.json()["code"]) == (422, "validation_error")
    assert (await _check(client, "10.00", category_id=expense))["verdict"] == "affordable"


async def test_monto_invalido_responde_422_rf17(client: AsyncClient) -> None:
    too_precise = await client.post("/v1/affordability-checks", json={"amount": "10.005", "currency": "BOB"})
    zero = await client.post("/v1/affordability-checks", json={"amount": "0", "currency": "BOB"})

    assert (too_precise.status_code, too_precise.json()["code"]) == (422, "invalid_amount")
    assert (zero.status_code, zero.json()["code"]) == (422, "validation_error")


async def test_la_fecha_estimada_es_futura(client: AsyncClient) -> None:
    account = await _account(client)
    await _rule(client, account["id"], "salary", "3000.00")

    body = await _check(client, "5000.00")

    assert date.fromisoformat(body["estimated_on"]) > date.today()
