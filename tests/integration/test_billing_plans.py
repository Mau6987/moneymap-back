"""Los planes y el plan propio (spec 011). Desde la migración 0028 solo quedan Gratuito y Premium."""

from httpx import AsyncClient

CARD = {"name": "Tarjeta BNB", "type": "card", "currency": "BOB", "institution_code": "bo.bnb", "last4": "1234"}


async def test_lista_los_planes_con_precios_y_limites_rf1(client: AsyncClient) -> None:
    response = await client.get("/v1/plans")

    assert response.status_code == 200
    plans = {plan["code"]: plan for plan in response.json()}
    assert [plan["code"] for plan in response.json()] == ["free", "paid_3"]
    assert plans["free"]["prices"] == []
    [price] = plans["paid_3"]["prices"]
    assert (price["currency"], price["monthly"], price["yearly"], price["purchasable"]) == (
        "BOB",
        "79.00",
        "790.00",
        False,
    )
    cards = {plan: next(f for f in plans[plan]["features"] if f["key"] == "finance.cards") for plan in plans}
    assert [cards[plan]["limit"] for plan in ("free", "paid_3")] == [1, None]
    goals = {plan: next(f for f in plans[plan]["features"] if f["key"] == "goals.active") for plan in plans}
    assert [goals[plan]["limit"] for plan in ("free", "paid_3")] == [None, None]


async def test_el_plan_propio_es_el_gratuito_con_lo_usado_rf2(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CARD)).status_code == 201

    response = await client.get("/v1/me/plan")

    assert response.status_code == 200
    body = response.json()
    assert (body["code"], body["status"], body["has_paid_access"]) == ("free", "free", False)
    cards = next(feature for feature in body["features"] if feature["key"] == "finance.cards")
    assert (cards["limit"], cards["used"], cards["period"]) == (1, 1, "total")


async def _feature(client: AsyncClient, key: str) -> dict[str, object]:
    body = (await client.get("/v1/me/plan")).json()
    feature: dict[str, object] = next(f for f in body["features"] if f["key"] == key)
    return feature


async def test_elige_un_plan_de_pago_sin_cobro_y_sube_los_limites_rf5(client: AsyncClient) -> None:
    response = await client.put("/v1/me/plan", json={"code": "paid_3"})

    assert response.status_code == 200
    body = response.json()
    assert (body["code"], body["status"], body["has_paid_access"]) == ("paid_3", "active", True)
    assert (await _feature(client, "finance.cards"))["limit"] is None
    for last4 in ("1111", "2222"):
        card = {**CARD, "name": f"Tarjeta {last4}", "last4": last4}
        assert (await client.post("/v1/accounts", json=card)).status_code == 201


async def test_al_bajar_al_gratuito_lo_que_existe_queda_y_no_se_crea_mas_rf5(client: AsyncClient) -> None:
    assert (await client.put("/v1/me/plan", json={"code": "paid_3"})).status_code == 200
    for last4 in ("1111", "2222"):
        card = {**CARD, "name": f"Tarjeta {last4}", "last4": last4}
        assert (await client.post("/v1/accounts", json=card)).status_code == 201

    response = await client.put("/v1/me/plan", json={"code": "free"})

    assert response.status_code == 200
    assert (response.json()["code"], response.json()["status"]) == ("free", "free")
    assert len((await client.get("/v1/accounts")).json()) == 2  # nada se borra
    third = await client.post("/v1/accounts", json={**CARD, "name": "Tarjeta 3333", "last4": "3333"})
    assert (third.status_code, third.json()["code"], third.json()["feature"]) == (409, "plan_limit", "finance.cards")


async def test_los_planes_retirados_ya_no_se_pueden_elegir_rf5(client: AsyncClient) -> None:
    for retired in ("paid_1", "paid_2"):
        response = await client.put("/v1/me/plan", json={"code": retired})
        assert (response.status_code, response.json()["code"]) == (404, "not_found")

    assert (await client.get("/v1/me/plan")).json()["code"] == "free"


async def test_un_plan_que_no_existe_responde_404_rf5(client: AsyncClient) -> None:
    response = await client.put("/v1/me/plan", json={"code": "no_existe"})

    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert (await client.get("/v1/me/plan")).json()["code"] == "free"


async def test_mis_monedas_respeta_el_limite_del_plan(client: AsyncClient) -> None:
    refused = await client.put("/v1/me/currencies/USD")

    assert (refused.status_code, refused.json()["code"], refused.json()["feature"]) == (
        409,
        "plan_limit",
        "finance.currencies",
    )
    assert (await client.put("/v1/me/currencies/BOB")).status_code == 200  # la que ya está, siempre
    assert (await client.put("/v1/me/plan", json={"code": "paid_3"})).status_code == 200
    assert (await client.put("/v1/me/currencies/USD")).status_code == 200


async def test_can_i_afford_it_cuenta_las_consultas_del_mes(client: AsyncClient) -> None:
    cash = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}
    assert (await client.post("/v1/accounts", json=cash)).status_code == 201
    check = {"amount": "10.00", "currency": "BOB"}
    for _ in range(10):
        assert (await client.post("/v1/affordability-checks", json=check)).status_code == 200

    eleventh = await client.post("/v1/affordability-checks", json=check)

    assert (eleventh.status_code, eleventh.json()["code"], eleventh.json()["feature"]) == (
        409,
        "plan_limit",
        "planning.affordability_checks",
    )
    assert (await _feature(client, "planning.affordability_checks"))["used"] == 10
    assert (await client.put("/v1/me/plan", json={"code": "paid_3"})).status_code == 200
    assert (await client.post("/v1/affordability-checks", json=check)).status_code == 200
