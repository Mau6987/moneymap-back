"""What If? contra PostgreSQL 16 (spec 009, RF-12 a RF-16).

Sin recurrentes ni ahorro planificado, Safe to Spend es el saldo menos los
aportes a metas del periodo, como en `test_planning_affordability.py`.
"""

from uuid import uuid4

from httpx import AsyncClient

CASH = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}


async def _two_goals(client: AsyncClient) -> dict[str, str]:
    """Safe to Spend de 500: 1000 menos 300 al Fondo (prioridad 1) y 200 al Viaje (3)."""
    assert (await client.post("/v1/accounts", json=CASH)).status_code == 201
    ids = {}
    for name, priority, amount in [("Fondo", 1, "300.00"), ("Viaje", 3, "200.00")]:
        goal = {"name": name, "target_amount": "5000.00", "currency": "BOB", "priority": priority}
        ids[name] = (await client.post("/v1/goals", json=goal)).json()["id"]
        contribution = await client.post(f"/v1/goals/{ids[name]}/contributions", json={"amount": amount})
        assert contribution.status_code == 201
    return ids


async def test_un_gasto_fijo_nuevo_y_las_metas_que_atrasa_rf12_a_rf14(client: AsyncClient) -> None:
    await _two_goals(client)
    goals_before = (await client.get("/v1/goals")).json()

    change = {"type": "recurring_expense", "monthly_change": "700.00"}
    response = await client.post("/v1/what-if", json={"changes": [change]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["currency"], body["safe_to_spend"], body["safe_to_spend_after"]) == ("BOB", "500.00", "-200.00")
    # Faltan 200: salen del Viaje (prioridad 3), que se queda sin ritmo. El Fondo sigue igual.
    outcomes = {goal["name"]: goal for goal in body["goals"]}
    assert (outcomes["Viaje"]["estimated_completion_after"], outcomes["Viaje"]["delay_months"]) == (None, None)
    assert outcomes["Fondo"]["delay_months"] == 0
    assert (body["assumptions"]["monthly_savings"], body["assumptions"]["monthly_savings_after"]) == (
        "500.00",
        "300.00",
    )
    # El Forecast a 30 días: 1000 − 500 de aportes; con el cambio, 1000 − 700 − 300 al Fondo.
    assert (body["forecast"][0]["days"], body["forecast"][0]["balance"], body["forecast"][0]["balance_after"]) == (
        30,
        "500.00",
        "0.00",
    )
    assert body["goes_negative_on_after"] is not None
    # RF-12: no cambia nada.
    assert (await client.get("/v1/goals")).json() == goals_before
    assert (await client.get("/v1/recurring-rules")).json() == []


async def test_subir_el_aporte_a_una_meta_la_adelanta_rf13(client: AsyncClient) -> None:
    ids = await _two_goals(client)

    change = {"type": "goal_contribution", "goal_id": ids["Fondo"], "monthly_amount": "600.00"}
    body = (await client.post("/v1/what-if", json={"changes": [change]})).json()

    assert body["safe_to_spend_after"] == "200.00"  # 300 más al Fondo
    fondo = next(goal for goal in body["goals"] if goal["name"] == "Fondo")
    assert fondo["delay_months"] < 0


async def test_gastar_mas_en_una_categoria_rf19(client: AsyncClient) -> None:
    await _two_goals(client)
    categories = {item["template_key"]: item["id"] for item in (await client.get("/v1/categories")).json()}

    spend = {"type": "category_spending", "category_id": categories["restaurants"], "monthly_change": "100.00"}
    body = (await client.post("/v1/what-if", json={"changes": [spend]})).json()
    income = {**spend, "category_id": categories["salary"]}
    wrong = await client.post("/v1/what-if", json={"changes": [income]})

    assert body["safe_to_spend_after"] == "400.00"
    assert body["forecast"][0]["balance_after"] == "400.00"  # 100 menos a 30 días
    assert (wrong.status_code, wrong.json()["code"]) == (422, "validation_error")


async def test_errores_rf12(client: AsyncClient) -> None:
    await _two_goals(client)
    income = {"type": "income", "monthly_change": "100.00"}

    too_many = await client.post("/v1/what-if", json={"changes": [income, income, income]})
    foreign = await client.post(
        "/v1/what-if",
        json={"changes": [{"type": "goal_contribution", "goal_id": str(uuid4()), "monthly_amount": "1.00"}]},
    )
    decimals = await client.post("/v1/what-if", json={"changes": [{"type": "income", "monthly_change": "1.001"}]})

    assert (too_many.status_code, too_many.json()["code"]) == (422, "validation_error")
    assert foreign.status_code == 404
    assert (decimals.status_code, decimals.json()["code"]) == (422, "invalid_amount")
