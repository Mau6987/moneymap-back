"""La base del simulador de What If? contra PostgreSQL 16 (spec 009, RF-20 a RF-23).

Los movimientos van el 10 y el 20 de marzo de 2026 y se pide con `on`, así las
pruebas no dependen del día en que corren. El 10 de marzo de 2026 es martes.
"""

from uuid import uuid4

from httpx import AsyncClient

CASH = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "100000.00"}
CARD = {
    "name": "Tarjeta BNB",
    "type": "card",
    "currency": "BOB",
    "institution_code": "bo.bnb",
    "last4": "1234",
    "opening_balance": "100000.00",
}
ON = "2026-03-10"


async def _account(client: AsyncClient, body: dict[str, str]) -> str:
    response = await client.post("/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def _categories(client: AsyncClient) -> dict[str, tuple[str, str]]:
    items = (await client.get("/v1/categories")).json()
    return {item["template_key"]: (item["id"], item["type"]) for item in items}


async def _move(client: AsyncClient, account: str, category: tuple[str, str], amount: str, day: str) -> None:
    category_id, kind = category
    body = {"kind": kind, "account_id": account, "category_id": category_id, "amount": amount, "occurred_on": day}
    response = await client.post("/v1/transactions", json=body)
    assert response.status_code == 201, response.text


async def _march(client: AsyncClient) -> tuple[str, str]:
    """En efectivo: salario 6000 y vivienda 1500 el 10; luz 500 el 20. Con tarjeta: suscripciones 800 el 10."""
    cash = await _account(client, CASH)
    card = await _account(client, CARD)
    categories = await _categories(client)
    await _move(client, cash, categories["salary"], "6000.00", "2026-03-10")
    await _move(client, cash, categories["housing"], "1500.00", "2026-03-10")
    await _move(client, cash, categories["utilities"], "500.00", "2026-03-20")
    await _move(client, card, categories["subscriptions"], "800.00", "2026-03-10")
    return cash, card


def _amounts(items: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(item["group"], item["amount"]) for item in items]


async def test_sin_tipo_usa_el_periodo_del_usuario_y_ordena_de_mayor_a_menor_rf20_rf21(client: AsyncClient) -> None:
    await _march(client)

    response = await client.get("/v1/what-if/baseline", params={"on": ON})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"] == "BOB"
    assert body["period_type"] == "monthly"
    assert body["periods_per_year"] == 12
    assert (body["period_starts_on"], body["period_ends_on"]) == ("2026-03-01", "2026-03-31")
    assert body["account_id"] is None
    assert _amounts(body["income"]) == [("income", "6000.00")]
    assert _amounts(body["expenses"]) == [("needs", "1500.00"), ("lifestyle", "800.00"), ("needs", "500.00")]


async def test_otro_tipo_de_periodo_que_el_configurado_rf20(client: AsyncClient) -> None:
    await _march(client)

    semi = (await client.get("/v1/what-if/baseline", params={"on": ON, "period_type": "semi_monthly"})).json()
    weekly = (await client.get("/v1/what-if/baseline", params={"on": ON, "period_type": "weekly"})).json()

    assert (semi["period_starts_on"], semi["period_ends_on"]) == ("2026-03-01", "2026-03-15")
    assert _amounts(semi["expenses"]) == [("needs", "1500.00"), ("lifestyle", "800.00")]
    assert semi["periods_per_year"] == 24
    # Sin ser su tipo, la semana empieza el lunes.
    assert (weekly["period_starts_on"], weekly["period_ends_on"]) == ("2026-03-09", "2026-03-15")
    assert weekly["periods_per_year"] == 52


async def test_el_tipo_configurado_usa_su_dia_de_inicio_rf20(client: AsyncClient) -> None:
    await _march(client)
    settings = await client.put("/v1/me/settings", json={"period_type": "weekly", "period_start_day": 3})
    assert settings.status_code == 200, settings.text

    body = (await client.get("/v1/what-if/baseline", params={"on": ON})).json()

    assert body["period_type"] == "weekly"
    assert (body["period_starts_on"], body["period_ends_on"]) == ("2026-03-04", "2026-03-10")


async def test_solo_los_movimientos_de_una_cuenta_rf21(client: AsyncClient) -> None:
    cash, card = await _march(client)

    with_card = (await client.get("/v1/what-if/baseline", params={"on": ON, "account_id": card})).json()
    with_cash = (await client.get("/v1/what-if/baseline", params={"on": ON, "account_id": cash})).json()

    assert with_card["account_id"] == card
    assert with_card["income"] == []
    assert _amounts(with_card["expenses"]) == [("lifestyle", "800.00")]
    assert _amounts(with_cash["expenses"]) == [("needs", "1500.00"), ("needs", "500.00")]


async def test_una_cuenta_ajena_o_que_no_existe_es_404_rf21(client: AsyncClient) -> None:
    await _march(client)

    response = await client.get("/v1/what-if/baseline", params={"on": ON, "account_id": str(uuid4())})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_las_metas_activas_con_su_aporte_del_periodo_rf22(client: AsyncClient) -> None:
    await _account(client, CASH)
    goal = {"name": "Fondo", "target_amount": "5000.00", "currency": "BOB", "priority": 1}
    goal_id = (await client.post("/v1/goals", json=goal)).json()["id"]
    contribution = await client.post(f"/v1/goals/{goal_id}/contributions", json={"amount": "300.00"})
    assert contribution.status_code == 201
    no_pace = {"name": "Viaje", "target_amount": "2000.00", "currency": "BOB", "priority": 2}
    assert (await client.post("/v1/goals", json=no_pace)).status_code == 201

    weekly = (await client.get("/v1/what-if/baseline", params={"period_type": "weekly"})).json()

    assert [g["name"] for g in weekly["goals"]] == ["Fondo", "Viaje"]
    fondo, viaje = weekly["goals"]
    assert (fondo["goal_id"], fondo["current_amount"], fondo["target_amount"]) == (goal_id, "300.00", "5000.00")
    assert fondo["monthly_contribution"] == "300.00"
    # 300 × 12 ÷ 52, en Decimal y a los decimales de la moneda.
    assert fondo["period_contribution"] == "69.23"
    assert (viaje["monthly_contribution"], viaje["period_contribution"]) == (None, "0.00")


async def test_tipo_de_periodo_que_no_existe_es_422_rf20(client: AsyncClient) -> None:
    response = await client.get("/v1/what-if/baseline", params={"period_type": "daily"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_sin_iniciar_sesion_es_401_rf23(api: AsyncClient) -> None:
    assert (await api.get("/v1/what-if/baseline")).status_code == 401
