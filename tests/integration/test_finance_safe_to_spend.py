"""Safe to Spend contra PostgreSQL 16 (spec 003).

RF cubiertos: RF-1 a RF-6 y RF-10 a RF-16. Los ajustes (RF-7 a RF-9) están en
`test_finance_period_settings.py`.

Las fechas salen del periodo que calcula la API: así las pruebas no dependen del
día en que corren (engineering §2.7).
"""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app
from tests.integration.conftest import RegisteredUser

CASH_BOB = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _period(client: AsyncClient) -> tuple[date, date]:
    body = (await client.get("/v1/safe-to-spend")).json()
    return date.fromisoformat(body["period_starts_on"]), date.fromisoformat(body["period_ends_on"])


async def _category_id(client: AsyncClient, template_key: str) -> str:
    response = await client.get("/v1/categories")
    return next(item["id"] for item in response.json() if item["template_key"] == template_key)


async def _rule(client: AsyncClient, template_key: str, amount: str, due_on: date, account_id: str) -> str:
    response = await client.post(
        "/v1/recurring-rules",
        json={
            "account_id": account_id,
            "category_id": await _category_id(client, template_key),
            "amount": amount,
            "description": template_key,
            "start_date": due_on.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    rule_id: str = response.json()["id"]
    return rule_id


async def _created_on(user_id: UUID, rule_id: str, day: date) -> None:
    """Como si el fijo se hubiera registrado ese día (la API siempre lo crea hoy)."""
    async with user_session(user_id) as session:
        await session.execute(
            text("UPDATE finance.recurring_rules SET created_at = CAST(:day AS date) + time '12:00' WHERE id = :id"),
            {"day": day, "id": rule_id},
        )


async def _goal_with_contribution(
    user_id: UUID, currency: str, amount: str, contributed_on: date, status: str = "active"
) -> None:
    """Las metas todavía no tienen API (spec 005): se crean directo, con la RLS del usuario."""
    async with user_session(user_id) as session:
        goal_id = (
            await session.execute(
                text(
                    "INSERT INTO goals.goals (user_id, name, target_amount, currency)"
                    " VALUES (:user_id, 'Viaje ' || gen_random_uuid(), 10000, :currency) RETURNING id"
                ),
                {"user_id": user_id, "currency": currency},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO goals.goal_contributions (user_id, goal_id, amount, contributed_on)"
                " VALUES (:user_id, :goal_id, :amount, :contributed_on)"
            ),
            {"user_id": user_id, "goal_id": goal_id, "amount": amount, "contributed_on": contributed_on},
        )
        if status == "achieved":
            await session.execute(
                text("UPDATE goals.goals SET status = 'achieved', achieved_at = now() WHERE id = :goal_id"),
                {"goal_id": goal_id},
            )


async def test_el_caso_del_prd_2500_menos_700_500_y_300_da_1000_rf1_rf2(client: AsyncClient, user_id: UUID) -> None:
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    starts_on, _ = await _period(client)
    await _rule(client, "housing", "700.00", starts_on, account)
    assert (await client.put("/v1/me/settings", json={"planned_savings": "500.00"})).status_code == 200
    await _goal_with_contribution(user_id, "BOB", "300.00", starts_on)

    response = await client.get("/v1/safe-to-spend")

    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "BOB"  # RF-3: sin `currency`, la principal
    assert body["amount"] == "1000.00"  # RF-13: texto, con los decimales de la moneda
    assert body["breakdown"] == {
        "current_balance": "2500.00",
        "pending_recurring": "700.00",
        "planned_savings": "500.00",
        "goal_contributions": "300.00",
    }


async def test_solo_cuenta_lo_que_vence_en_el_periodo_y_los_gastos_rf11(client: AsyncClient) -> None:
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    starts_on, ends_on = await _period(client)
    await _rule(client, "housing", "700.00", ends_on, account)  # el último día entra
    await _rule(client, "transport", "50.00", ends_on + timedelta(days=1), account)  # el próximo periodo no
    await _rule(client, "salary", "6000.00", starts_on, account)  # un ingreso no se resta

    breakdown = (await client.get("/v1/safe-to-spend")).json()["breakdown"]

    assert breakdown["pending_recurring"] == "700.00"


async def test_un_gasto_fijo_sin_pagar_suma_lo_atrasado_y_lo_de_este_periodo(
    client: AsyncClient, user_id: UUID
) -> None:
    """QA (2026-11-03): un fijo de octubre sin pagar cuenta en noviembre dos veces, la atrasada y la del mes."""
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    starts_on, ends_on = await _period(client)
    overdue = starts_on - timedelta(days=1)  # venció antes del periodo y no se pagó
    rule = await _rule(client, "housing", "350.00", overdue, account)
    await _created_on(user_id, rule, overdue - timedelta(days=5))  # se creó antes de vencer

    breakdown = (await client.get("/v1/safe-to-spend")).json()["breakdown"]

    # Mensual: la vez atrasada (el día antes del periodo) y la de este periodo.
    assert breakdown["pending_recurring"] == "700.00"
    assert Decimal((await client.get("/v1/safe-to-spend")).json()["amount"]) == Decimal("1800.00")


async def test_lo_de_antes_del_periodo_en_que_se_creo_el_fijo_no_se_debe(client: AsyncClient) -> None:
    """Revisión del #126: registrar hoy un alquiler "desde hace un año" no arranca con un año atrasado."""
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    starts_on, _ = await _period(client)
    await _rule(client, "housing", "350.00", starts_on - timedelta(days=365), account)
    await _rule(client, "subscriptions", "50.00", starts_on, account)  # vence el día que empieza el periodo

    breakdown = (await client.get("/v1/safe-to-spend")).json()["breakdown"]

    # Se crearon hoy: de cada uno cuenta solo la vez de este periodo.
    assert breakdown["pending_recurring"] == "400.00"


async def test_una_meta_cumplida_no_aporta_rf12(client: AsyncClient, user_id: UUID) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, _ = await _period(client)
    await _goal_with_contribution(user_id, "BOB", "300.00", starts_on, status="achieved")
    await _goal_with_contribution(user_id, "BOB", "120.00", starts_on - timedelta(days=1))  # periodo anterior

    assert (await client.get("/v1/safe-to-spend")).json()["breakdown"]["goal_contributions"] == "0.00"


async def test_otra_moneda_no_mezcla_nada_ni_resta_el_ahorro_rf5_rf6(
    client: AsyncClient, allow_more_currencies: None
) -> None:
    bob = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    usd = await client.post(
        "/v1/accounts", json={**CASH_BOB, "name": "Dólares", "currency": "USD", "opening_balance": "300.00"}
    )
    assert usd.status_code == 201
    starts_on, _ = await _period(client)
    await _rule(client, "housing", "700.00", starts_on, bob)
    await _rule(client, "subscriptions", "15.00", starts_on, usd.json()["id"])
    assert (await client.put("/v1/me/settings", json={"planned_savings": "500.00"})).status_code == 200

    body = (await client.get("/v1/safe-to-spend", params={"currency": "USD"})).json()

    assert body["currency"] == "USD"
    assert body["amount"] == "285.00"
    assert body["breakdown"] == {
        "current_balance": "300.00",
        "pending_recurring": "15.00",
        "planned_savings": "0.00",  # el ahorro es de la moneda principal
        "goal_contributions": "0.00",
    }


async def test_sin_cuentas_en_esa_moneda_el_desglose_sale_en_cero_rf16(client: AsyncClient) -> None:
    response = await client.get("/v1/safe-to-spend", params={"currency": "USD"})

    assert response.status_code == 200
    assert response.json()["amount"] == "0.00"
    assert set(response.json()["breakdown"].values()) == {"0.00"}


async def test_una_moneda_que_no_existe_responde_422_rf4(client: AsyncClient) -> None:
    response = await client.get("/v1/safe-to-spend", params={"currency": "XXX"})

    assert response.status_code == 422
    assert response.json()["code"] == "currency_unavailable"


async def test_el_periodo_es_el_del_usuario_rf10(client: AsyncClient) -> None:
    assert (
        await client.put("/v1/me/settings", json={"period_type": "monthly", "period_start_day": 25})
    ).status_code == 200

    starts_on, ends_on = await _period(client)

    assert starts_on.day == 25
    assert ends_on.day == 24


async def test_no_ve_el_dinero_de_otro_usuario_rf15(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await client.get("/v1/safe-to-spend")).json()["breakdown"]["current_balance"] == "0.00"


async def test_sin_moneda_principal_pide_terminar_el_onboarding_rf3(
    api: AsyncClient, registered_user: RegisteredUser
) -> None:
    response = await api.get("/v1/safe-to-spend", headers=registered_user.headers)

    assert response.status_code == 422
    assert response.json()["code"] == "onboarding_incomplete"
