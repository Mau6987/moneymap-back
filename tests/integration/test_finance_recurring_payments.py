"""Marcar un recurrente como pagado (spec 003).

RF cubiertos: RF-11 (deja de contar como pendiente), RF-17 a RF-19, RF-21 y RF-22 (omitir una vez).
"""

from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app

CASH_BOB = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _setup(client: AsyncClient, template_key: str = "housing", amount: str = "700.00") -> dict[str, str]:
    """Una cuenta y un recurrente que vence el primer día del periodo vigente."""
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on = (await client.get("/v1/safe-to-spend")).json()["period_starts_on"]
    categories = (await client.get("/v1/categories")).json()
    category = next(item["id"] for item in categories if item["template_key"] == template_key)
    response = await client.post(
        "/v1/recurring-rules",
        json={"category_id": category, "amount": amount, "description": "Alquiler", "start_date": starts_on},
    )
    assert response.status_code == 201, response.text
    rule: dict[str, str] = response.json()
    return rule


def _months_later(day: str, months: int) -> str:
    start = date.fromisoformat(day)
    month = start.month - 1 + months
    return start.replace(year=start.year + month // 12, month=month % 12 + 1).isoformat()


async def test_registra_el_gasto_y_pasa_al_mes_siguiente_rf17(client: AsyncClient) -> None:
    rule = await _setup(client)

    response = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})

    assert response.status_code == 201
    body = response.json()
    transaction = body["transaction"]
    assert (transaction["kind"], transaction["amount"], transaction["source"]) == ("expense", "700.00", "recurring")
    assert transaction["description"] == "Alquiler"
    assert body["recurring_rule"]["next_due_on"] == _months_later(rule["next_due_on"], 1)
    accounts = (await client.get("/v1/accounts")).json()
    assert accounts[0]["current_balance"] == "1800.00"


async def test_pagado_deja_de_contar_como_pendiente_rf11(client: AsyncClient) -> None:
    rule = await _setup(client)
    before = (await client.get("/v1/safe-to-spend")).json()
    assert before["breakdown"]["pending_recurring"] == "700.00"

    assert (await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})).status_code == 201

    after = (await client.get("/v1/safe-to-spend")).json()
    assert after["breakdown"]["pending_recurring"] == "0.00"
    assert after["amount"] == before["amount"]  # el dinero salió de la cuenta: lo libre no cambia


async def test_acepta_otro_monto_y_otra_fecha_rf17(client: AsyncClient) -> None:
    rule = await _setup(client, template_key="utilities", amount="180.00")

    response = await client.post(
        f"/v1/recurring-rules/{rule['id']}/payments", json={"amount": "185.40", "occurred_on": rule["next_due_on"]}
    )

    assert response.status_code == 201
    assert response.json()["transaction"]["amount"] == "185.40"
    assert response.json()["transaction"]["occurred_on"] == rule["next_due_on"]
    assert response.json()["recurring_rule"]["amount"] == "180.00"  # el recurrente no cambia


async def test_un_ingreso_recurrente_registra_un_ingreso_rf17(client: AsyncClient) -> None:
    rule = await _setup(client, template_key="salary", amount="6000.00")

    response = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})

    assert response.json()["transaction"]["kind"] == "income"
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "8500.00"


async def test_ajeno_o_inexistente_responde_404_rf18(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    rule = await _setup(client)
    assert (await client.post(f"/v1/recurring-rules/{uuid4()}/payments", json={})).status_code == 404

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other
    assert (await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})).status_code == 404


async def test_dado_de_baja_responde_404_rf18(client: AsyncClient) -> None:
    rule = await _setup(client)
    assert (await client.delete(f"/v1/recurring-rules/{rule['id']}")).status_code == 204

    response = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})

    assert (response.status_code, response.json()["code"]) == (404, "not_found")


async def test_la_misma_clave_no_registra_dos_pagos_rf18(client: AsyncClient) -> None:
    rule = await _setup(client)
    headers = {"Idempotency-Key": str(uuid4())}

    first = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={}, headers=headers)
    again = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={}, headers=headers)

    assert again.json() == first.json()
    assert len((await client.get("/v1/transactions")).json()["items"]) == 1


async def test_pasada_la_fecha_de_fin_deja_de_vencer_rf19(client: AsyncClient, user_id: UUID) -> None:
    rule = await _setup(client)
    async with user_session(user_id) as session:  # la API todavía no expone end_date
        await session.execute(
            text("UPDATE finance.recurring_rules SET end_date = next_due_on WHERE id = :rule_id"),
            {"rule_id": rule["id"]},
        )

    assert (await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})).status_code == 201

    assert (await client.get("/v1/recurring-rules")).json() == []
    assert (await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})).status_code == 404


async def test_los_recurrentes_son_recordatorios_y_auto_post_se_ignora(client: AsyncClient) -> None:
    rule = await _setup(client)
    assert rule["auto_post"] is False

    response = await client.patch(f"/v1/recurring-rules/{rule['id']}", json={"auto_post": True})

    assert response.status_code == 200
    assert response.json()["auto_post"] is False


async def test_omitir_una_vez_avanza_sin_registrar_nada_rf22(client: AsyncClient) -> None:
    rule = await _setup(client)
    assert (await client.get("/v1/safe-to-spend")).json()["breakdown"]["pending_recurring"] == "700.00"

    response = await client.post(f"/v1/recurring-rules/{rule['id']}/skip")

    assert response.status_code == 200, response.text
    assert response.json()["next_due_on"] == _months_later(rule["next_due_on"], 1)
    assert (await client.get("/v1/transactions")).json()["items"] == []
    assert (await client.get("/v1/accounts")).json()[0]["current_balance"] == "2500.00"
    assert (await client.get("/v1/safe-to-spend")).json()["breakdown"]["pending_recurring"] == "0.00"


async def test_omitir_uno_dado_de_baja_o_ajeno_responde_404_rf22(client: AsyncClient) -> None:
    rule = await _setup(client)
    assert (await client.delete(f"/v1/recurring-rules/{rule['id']}")).status_code == 204

    assert (await client.post(f"/v1/recurring-rules/{rule['id']}/skip")).status_code == 404
    assert (await client.post(f"/v1/recurring-rules/{uuid4()}/skip")).status_code == 404
