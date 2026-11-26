"""Financial Forecast contra PostgreSQL 16 (spec 010) con el criterio del PRD §6.18."""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session

_RULE = text(
    """
    INSERT INTO finance.recurring_rules (user_id, account_id, category_id, amount, description, frequency, start_date)
    SELECT :user_id, accounts.id, categories.id, :amount, :description, 'monthly',
           (now() AT TIME ZONE 'America/La_Paz')::date + CAST(:in_days AS int)
    FROM finance.accounts AS accounts, finance.categories AS categories
    WHERE accounts.user_id = :user_id AND categories.user_id = :user_id AND categories.template_key = :category
    """
)

# Un gasto variable de 1500 en cada uno de los 3 meses completos anteriores.
_PAST_SPENDING = text(
    """
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)
    SELECT :user_id, 'expense', accounts.id, categories.id, 1500,
           (date_trunc('month', now() AT TIME ZONE 'America/La_Paz') - make_interval(months => months.n))::date
    FROM finance.accounts AS accounts, finance.categories AS categories, generate_series(1, 3) AS months(n)
    WHERE accounts.user_id = :user_id AND categories.user_id = :user_id AND categories.template_key = 'groceries'
    """
)


async def test_el_ejemplo_del_prd(client: AsyncClient, user_id: UUID) -> None:
    # 7000 de apertura menos 4500 de gastos pasados: 2500 de saldo hoy.
    cash = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "7000.00"}
    assert (await client.post("/v1/accounts", json=cash)).status_code == 201
    goal = {"name": "Fondo", "target_amount": "50000.00", "currency": "BOB"}
    goal_id = (await client.post("/v1/goals", json=goal)).json()["id"]
    assert (await client.post(f"/v1/goals/{goal_id}/contributions", json={"amount": "300.00"})).status_code == 201
    async with user_session(user_id) as session:
        await session.execute(_PAST_SPENDING, {"user_id": user_id})
        for description, amount, in_days, category in [
            ("Sueldo", 3000, 5, "salary"),
            ("Alquiler", 700, 10, "subscriptions"),
        ]:
            params = {
                "user_id": user_id,
                "description": description,
                "amount": amount,
                "in_days": in_days,
                "category": category,
            }
            await session.execute(_RULE, params)

    response = await client.get("/v1/forecast")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["currency"], body["balance"]) == ("BOB", "2500.00")
    assert [(point["days"], point["balance"]) for point in body["points"]] == [
        (30, "3000.00"),
        (60, "3500.00"),
        (90, "4000.00"),
    ]
    assert (body["goes_negative_on"], body["limited_history"]) == (None, False)
    assert body["assumptions"] == {
        "recurring_income": "3000.00",
        "recurring_expenses": "700.00",
        "goal_contributions": "300.00",
        "variable_spending": "1500.00",
        "history_months": 3,
    }


async def test_sin_historial_avisa(client: AsyncClient) -> None:
    cash = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "100.00"}
    assert (await client.post("/v1/accounts", json=cash)).status_code == 201

    body = (await client.get("/v1/forecast")).json()

    assert (body["limited_history"], body["goes_negative_on"]) == (True, None)
    assert [point["balance"] for point in body["points"]] == ["100.00", "100.00", "100.00"]
