"""Metas y aportes contra PostgreSQL 16 (spec 005).

RF cubiertos: RF-1 a RF-10, RF-17, RF-18, RF-20, RF-21 y RF-23, y las metas sin
límite en el plan gratuito (migración 0028).
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app
from app.modules.goals.domain.suggested_contribution import add_months

TRIP = {"name": "Viaje a Cusco", "target_amount": "5000.00", "currency": "BOB", "priority": 1}


async def _goal(client: AsyncClient, **changes: object) -> dict[str, object]:
    response = await client.post("/v1/goals", json={**TRIP, **changes})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def test_crea_la_meta_en_cero_rf1_rf17(client: AsyncClient) -> None:
    goal = await _goal(client, target_date="2027-06-30")

    assert goal["current_amount"] == "0.00"
    assert (goal["target_amount"], goal["currency"], goal["target_date"]) == ("5000.00", "BOB", "2027-06-30")
    assert (goal["status"], goal["progress_percent"], goal["priority"]) == ("active", 0, 1)


async def test_moneda_o_monto_invalidos_responden_422_rf2_rf3(client: AsyncClient) -> None:
    unavailable = await client.post("/v1/goals", json={**TRIP, "currency": "XXX"})
    zero = await client.post("/v1/goals", json={**TRIP, "target_amount": "0"})
    too_precise = await client.post("/v1/goals", json={**TRIP, "target_amount": "5000.001"})

    assert (unavailable.status_code, unavailable.json()["code"]) == (422, "currency_unavailable")
    assert (zero.status_code, zero.json()["code"]) == (422, "invalid_amount")
    assert (too_precise.status_code, too_precise.json()["code"]) == (422, "invalid_amount")


async def test_corrige_solo_lo_enviado_rf4(client: AsyncClient) -> None:
    goal = await _goal(client)

    response = await client.patch(f"/v1/goals/{goal['id']}", json={"name": "Viaje a Uyuni"})

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["target_amount"]) == ("Viaje a Uyuni", "5000.00")
    assert (await client.patch(f"/v1/goals/{goal['id']}", json={})).status_code == 422


async def test_borrar_la_saca_de_la_lista_y_no_toca_las_cuentas_rf5(client: AsyncClient) -> None:
    account = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}
    assert (await client.post("/v1/accounts", json=account)).status_code == 201
    goal = await _goal(client)

    assert (await client.delete(f"/v1/goals/{goal['id']}")).status_code == 204

    assert (await client.get("/v1/goals")).json() == []
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "1000.00"
    assert (await client.delete(f"/v1/goals/{goal['id']}")).status_code == 404


async def test_borrar_una_meta_con_saldo_responde_409_y_no_la_borra(client: AsyncClient) -> None:
    """QA BUG-055: el saldo tiene que volver a una cuenta antes de borrar."""
    account = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}
    created = await client.post("/v1/accounts", json=account)
    assert created.status_code == 201
    account_id = created.json()["id"]
    goal = await _goal(client)
    assert (
        await client.post(
            f"/v1/goals/{goal['id']}/contributions",
            json={"amount": "300.00", "account_id": account_id},
        )
    ).status_code == 201

    blocked = await client.delete(f"/v1/goals/{goal['id']}")

    assert (blocked.status_code, blocked.json()["code"]) == (409, "goal_has_saved")
    assert len((await client.get("/v1/goals")).json()) == 1

    # Con el saldo retirado, la meta se puede borrar y la cuenta recupera el dinero.
    assert (
        await client.post(
            f"/v1/goals/{goal['id']}/withdrawals",
            json={"amount": "300.00", "account_id": account_id},
        )
    ).status_code == 201
    assert (await client.delete(f"/v1/goals/{goal['id']}")).status_code == 204
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "1000.00"


async def test_el_aporte_lo_suma_la_base_y_da_el_avance_rf6_rf9(client: AsyncClient) -> None:
    goal = await _goal(client)

    response = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "2500.00", "contributed_on": "2026-10-01"}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["contribution"]["amount"], body["contribution"]["contributed_on"]) == ("2500.00", "2026-10-01")
    assert (body["goal"]["current_amount"], body["goal"]["progress_percent"]) == ("2500.00", 50)
    listed = (await client.get("/v1/goals")).json()
    assert (listed[0]["current_amount"], listed[0]["progress_percent"]) == ("2500.00", 50)


async def test_llegar_justo_al_objetivo_la_deja_cumplida_rf7(client: AsyncClient) -> None:
    goal = await _goal(client)
    await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "4000.00"})

    response = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "1000.00"})

    assert response.status_code == 201
    assert response.json()["goal"]["status"] == "achieved"
    assert response.json()["goal"]["progress_percent"] == 100


async def test_un_retiro_por_debajo_del_objetivo_la_reabre(client: AsyncClient) -> None:
    """QA BUG-051: una meta cumplida que baja del objetivo vuelve a activa."""
    account = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "5000.00"}
    created = await client.post("/v1/accounts", json=account)
    assert created.status_code == 201
    account_id = created.json()["id"]
    goal = await _goal(client)
    assert (
        await client.post(
            f"/v1/goals/{goal['id']}/contributions",
            json={"amount": "5000.00", "account_id": account_id},
        )
    ).status_code == 201

    response = await client.post(
        f"/v1/goals/{goal['id']}/withdrawals",
        json={"amount": "100.00", "account_id": account_id},
    )

    assert response.status_code == 201
    body = response.json()["goal"]
    assert (body["status"], body["current_amount"], body["progress_percent"]) == ("active", "4900.00", 98)
    assert body["estimated_completion"] is not None
    assert (await client.get("/v1/goals")).json()[0]["status"] == "active"
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "100.00"


async def test_subir_el_objetivo_de_una_cumplida_tambien_la_reabre(client: AsyncClient) -> None:
    goal = await _goal(client)
    assert (await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "5000.00"})).status_code == 201

    response = await client.patch(f"/v1/goals/{goal['id']}", json={"target_amount": "6000.00"})

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["current_amount"]) == ("active", "5000.00")


async def test_un_aporte_que_pasa_lo_que_falta_responde_422_bug049(client: AsyncClient) -> None:
    goal = await _goal(client)
    await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "4000.00"})

    response = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "1000.01"})

    assert response.status_code == 422
    assert response.json()["code"] == "contribution_exceeds_remaining"
    assert "1000.00" in response.json()["detail"]
    # Nada cambió: la meta sigue en 4000 y activa.
    listed = (await client.get("/v1/goals")).json()[0]
    assert (listed["current_amount"], listed["status"]) == ("4000.00", "active")


async def test_una_meta_cumplida_no_recibe_mas_aportes_pero_se_puede_retirar_bug049(client: AsyncClient) -> None:
    account = (
        await client.post(
            "/v1/accounts", json={"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "0.00"}
        )
    ).json()["id"]
    goal = await _goal(client)
    await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "5000.00"})

    more = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "1.00"})
    withdrawal = await client.post(
        f"/v1/goals/{goal['id']}/withdrawals", json={"amount": "200.00", "account_id": account}
    )

    assert more.status_code == 422
    assert more.json()["code"] == "goal_closed"
    assert withdrawal.status_code == 201, withdrawal.text


async def test_un_aporte_negativo_o_con_decimales_de_mas_responde_422_rf8(client: AsyncClient) -> None:
    goal = await _goal(client)

    negative = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "-100.00"})
    too_precise = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "10.001"})

    assert (negative.status_code, negative.json()["code"]) == (422, "invalid_amount")
    assert (too_precise.status_code, too_precise.json()["code"]) == (422, "invalid_amount")


async def test_la_misma_clave_no_aporta_dos_veces(client: AsyncClient) -> None:
    goal = await _goal(client)
    headers = {"Idempotency-Key": str(uuid4())}

    first = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "100.00"}, headers=headers)
    again = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "100.00"}, headers=headers)

    assert again.json() == first.json()
    assert (await client.get("/v1/goals")).json()[0]["current_amount"] == "100.00"


def _months_ahead(months: int) -> str:
    """El "YYYY-MM" de hoy en La Paz (la zona por defecto) más `months` meses."""
    today = datetime.now(ZoneInfo("America/La_Paz")).date()
    index = today.year * 12 + today.month - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


async def _contribute(client: AsyncClient, goal_id: object, amount: str, contributed_on: str) -> None:
    body = {"amount": amount, "contributed_on": contributed_on}
    assert (await client.post(f"/v1/goals/{goal_id}/contributions", json=body)).status_code == 201


async def test_estima_la_fecha_al_ritmo_de_sus_aportes_rf10(client: AsyncClient) -> None:
    goal = await _goal(client)
    assert goal["estimated_completion"] is None
    for month in range(5, 10):
        await _contribute(client, goal["id"], "500.00", f"2026-{month:02d}-15")

    # PRD §6.12: faltan 2500 a 500 por mes, son 5 meses.
    estimated = (await client.get("/v1/goals")).json()[0]["estimated_completion"]

    assert estimated[:7] == _months_ahead(5)


async def test_el_promedio_cuenta_solo_los_meses_con_aporte_rf10(client: AsyncClient) -> None:
    goal = await _goal(client)
    await _contribute(client, goal["id"], "300.00", "2026-01-10")
    await _contribute(client, goal["id"], "300.00", "2026-01-20")
    await _contribute(client, goal["id"], "400.00", "2026-06-05")

    # 1000 en dos meses con aporte son 500 por mes; con objetivo 3500 faltan 2500.
    patched = await client.patch(f"/v1/goals/{goal['id']}", json={"target_amount": "3500.00"})

    assert patched.json()["estimated_completion"][:7] == _months_ahead(5)
    assert (await client.get("/v1/goals")).json()[0]["estimated_completion"][:7] == _months_ahead(5)


async def test_la_cumplida_ya_no_estima_rf10(client: AsyncClient) -> None:
    goal = await _goal(client)

    response = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "5000.00"})

    assert (response.json()["goal"]["status"], response.json()["goal"]["estimated_completion"]) == ("achieved", None)


async def test_la_meta_de_otro_usuario_responde_404_rf18(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    goal = await _goal(client)
    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await client.patch(f"/v1/goals/{goal['id']}", json={"name": "Mía"})).status_code == 404
    assert (await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "1.00"})).status_code == 404
    assert (await client.delete(f"/v1/goals/{goal['id']}")).status_code == 404
    assert (await client.get("/v1/goals")).json() == []


async def test_el_plan_gratuito_no_limita_las_metas_activas(client: AsyncClient) -> None:
    for number in range(5):
        await _goal(client, name=f"Meta {number}")

    assert len((await client.get("/v1/goals")).json()) == 5


async def _set_period(client: AsyncClient, period_type: str, start_day: int) -> None:
    body = {"period_type": period_type, "period_start_day": start_day}
    response = await client.put("/v1/me/settings", json=body)
    assert response.status_code == 200, response.text


async def test_el_aporte_sugerido_reparte_lo_que_falta_entre_los_periodos_rf23(client: AsyncClient) -> None:
    await _set_period(client, "semi_monthly", 1)
    target = add_months(datetime.now(ZoneInfo("America/La_Paz")).date(), 2)

    goal = await _goal(client, target_amount="1000.00", target_date=target.isoformat())

    assert (goal["suggested_contribution"], goal["period_type"]) == ("250.00", "semi_monthly")

    contribution = await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "400.00"})
    assert contribution.status_code == 201
    [listed] = (await client.get("/v1/goals")).json()
    assert listed["suggested_contribution"] == "150.00"


async def test_sin_fecha_o_con_la_fecha_vencida_no_hay_aporte_sugerido_rf23(client: AsyncClient) -> None:
    no_date = await _goal(client, name="Sin fecha")
    assert no_date["suggested_contribution"] is None

    overdue = await _goal(client, name="Vencida", target_date="2030-01-01")
    response = await client.patch(f"/v1/goals/{overdue['id']}", json={"target_date": "2000-01-01"})
    assert response.status_code == 200, response.text
    assert response.json()["suggested_contribution"] is None


async def _account(client: AsyncClient, currency: str = "BOB", name: str = "Efectivo") -> dict[str, object]:
    body = {"name": name, "type": "cash", "currency": currency, "opening_balance": "1000.00"}
    response = await client.post("/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


async def _balance(client: AsyncClient, account_id: object) -> str:
    accounts = (await client.get("/v1/accounts")).json()
    balance: str = next(a["current_balance"] for a in accounts if a["id"] == account_id)
    return balance


async def test_el_aporte_sale_de_la_cuenta_y_no_se_resta_dos_veces_rf6_rf21(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    before = (await client.get("/v1/safe-to-spend")).json()

    response = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "300.00", "account_id": account["id"]}
    )

    assert response.status_code == 201, response.text
    assert response.json()["goal"]["current_amount"] == "300.00"
    assert await _balance(client, account["id"]) == "700.00"
    after = (await client.get("/v1/safe-to-spend")).json()
    # Safe to Spend baja 300 una sola vez: por el saldo, no también por el aporte.
    assert Decimal(before["amount"]) - Decimal(after["amount"]) == Decimal(300)
    assert after["breakdown"]["goal_contributions"] == "0.00"


async def test_el_retiro_vuelve_a_la_cuenta_rf20(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    contribution = {"amount": "500.00", "account_id": account["id"]}
    assert (await client.post(f"/v1/goals/{goal['id']}/contributions", json=contribution)).status_code == 201

    response = await client.post(
        f"/v1/goals/{goal['id']}/withdrawals", json={"amount": "200.00", "account_id": account["id"]}
    )

    assert response.status_code == 201, response.text
    assert (response.json()["contribution"]["amount"], response.json()["goal"]["current_amount"]) == (
        "-200.00",
        "300.00",
    )
    assert await _balance(client, account["id"]) == "700.00"


async def test_no_se_saca_mas_de_lo_acumulado_rf20(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    await _contribute(client, goal["id"], "100.00", "2026-10-01")

    too_much = await client.post(
        f"/v1/goals/{goal['id']}/withdrawals", json={"amount": "100.01", "account_id": account["id"]}
    )
    zero = await client.post(f"/v1/goals/{goal['id']}/withdrawals", json={"amount": "0", "account_id": account["id"]})

    assert (too_much.status_code, too_much.json()["code"]) == (422, "goal_insufficient")
    assert (zero.status_code, zero.json()["code"]) == (422, "invalid_amount")
    assert await _balance(client, account["id"]) == "1000.00"


async def test_la_cuenta_va_en_la_moneda_de_la_meta_y_es_del_usuario_rf21(client: AsyncClient) -> None:
    goal = await _goal(client, currency="USD")
    bolivianos = await _account(client)

    mismatch = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "10.00", "account_id": bolivianos["id"]}
    )
    missing = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "10.00", "account_id": str(uuid4())}
    )

    assert (mismatch.status_code, mismatch.json()["code"]) == (422, "currency_mismatch")
    assert missing.status_code == 404
    assert (await client.get("/v1/goals")).json()[0]["current_amount"] == "0.00"


async def test_una_cuenta_archivada_no_aporta_ni_recibe_retiros_rf21(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    await _contribute(client, goal["id"], "100.00", "2026-10-01")
    assert (await client.patch(f"/v1/accounts/{account['id']}", json={"archived": True})).status_code == 200

    contribution = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "10.00", "account_id": account["id"]}
    )
    withdrawal = await client.post(
        f"/v1/goals/{goal['id']}/withdrawals", json={"amount": "10.00", "account_id": account["id"]}
    )

    assert (contribution.status_code, withdrawal.status_code) == (404, 404)
    assert (await client.get("/v1/goals")).json()[0]["current_amount"] == "100.00"


async def test_una_cuenta_con_aportes_no_cambia_de_moneda_rf21(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    contribution = {"amount": "200.00", "account_id": account["id"]}
    assert (await client.post(f"/v1/goals/{goal['id']}/contributions", json=contribution)).status_code == 201

    response = await client.patch(f"/v1/accounts/{account['id']}", json={"currency": "USD"})

    assert (response.status_code, response.json()["code"]) == (409, "account_currency_locked")


async def test_dos_retiros_a_la_vez_no_sacan_mas_de_lo_acumulado_rf20(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)
    await _contribute(client, goal["id"], "100.00", "2026-10-01")
    withdrawal = {"amount": "100.00", "account_id": account["id"]}

    responses = await asyncio.gather(
        client.post(f"/v1/goals/{goal['id']}/withdrawals", json=withdrawal),
        client.post(f"/v1/goals/{goal['id']}/withdrawals", json=withdrawal),
    )

    assert sorted(r.status_code for r in responses) == [201, 422]
    assert (await client.get("/v1/goals")).json()[0]["current_amount"] == "0.00"
    assert await _balance(client, account["id"]) == "1100.00"


async def test_no_se_aporta_mas_de_lo_que_tiene_la_cuenta_rf21(client: AsyncClient) -> None:
    account = await _account(client)
    goal = await _goal(client)

    too_much = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "1000.01", "account_id": account["id"]}
    )
    all_of_it = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "1000.00", "account_id": account["id"]}
    )
    from_zero = await client.post(
        f"/v1/goals/{goal['id']}/contributions", json={"amount": "0.01", "account_id": account["id"]}
    )

    assert (too_much.status_code, too_much.json()["code"]) == (422, "account_insufficient")
    assert all_of_it.status_code == 201
    assert (from_zero.status_code, from_zero.json()["code"]) == (422, "account_insufficient")
    assert await _balance(client, account["id"]) == "0.00"
    # Sin cuenta no hay saldo que mirar.
    assert (await client.post(f"/v1/goals/{goal['id']}/contributions", json={"amount": "50.00"})).status_code == 201


async def test_dos_aportes_a_la_vez_no_dejan_la_cuenta_en_negativo_rf21(client: AsyncClient) -> None:
    # A metas distintas: a la misma ya los ordena el bloqueo de la meta.
    account = await _account(client)
    trip = await _goal(client)
    laptop = await _goal(client, name="Laptop")
    contribution = {"amount": "600.00", "account_id": account["id"]}

    responses = await asyncio.gather(
        client.post(f"/v1/goals/{trip['id']}/contributions", json=contribution),
        client.post(f"/v1/goals/{laptop['id']}/contributions", json=contribution),
    )

    assert sorted(r.status_code for r in responses) == [201, 422]
    assert await _balance(client, account["id"]) == "400.00"


async def test_un_emoji_solo_no_es_nombre_de_meta_bug006(client: AsyncClient) -> None:
    for name in ["🏠", "-", "..."]:
        response = await client.post("/v1/goals", json={**TRIP, "name": name})
        assert (response.status_code, response.json()["code"]) == (422, "validation_error"), name
    assert (await client.post("/v1/goals", json={**TRIP, "name": "Casa 🏠"})).status_code == 201
