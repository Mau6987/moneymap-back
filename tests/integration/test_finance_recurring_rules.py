"""Listar, corregir y dar de baja recurrentes (spec 002).

RF cubiertos: RF-21 (al editar), RF-29, RF-30 y RF-31; de la spec 003, RF-23.
"""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app

CASH_BOB = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _category_id(client: AsyncClient, template_key: str) -> str:
    response = await client.get("/v1/categories")
    return next(item["id"] for item in response.json() if item["template_key"] == template_key)


async def _rule(client: AsyncClient, template_key: str, amount: str, start_date: str) -> dict[str, str]:
    response = await client.post(
        "/v1/recurring-rules",
        json={
            "category_id": await _category_id(client, template_key),
            "amount": amount,
            "description": template_key,
            "start_date": start_date,
        },
    )
    assert response.status_code == 201, response.text
    rule: dict[str, str] = response.json()
    return rule


async def test_lista_los_recurrentes_con_el_que_vence_primero_arriba_rf29(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    rent = await _rule(client, "housing", "1500.00", "2026-11-05")
    salary = await _rule(client, "salary", "6000.00", "2026-11-01")

    response = await client.get("/v1/recurring-rules")

    assert response.status_code == 200
    assert [(rule["id"], rule["type"], rule["amount"]) for rule in response.json()] == [
        (salary["id"], "income", "6000.00"),
        (rent["id"], "expense", "1500.00"),
    ]


async def test_corrige_solo_lo_que_se_envia_rf30(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    rent = await _rule(client, "housing", "1500.00", "2026-11-05")

    response = await client.patch(
        f"/v1/recurring-rules/{rent['id']}", json={"amount": "1650.00", "frequency": "yearly"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["amount"], body["frequency"], body["description"]) == ("1650.00", "yearly", "housing")
    assert body["next_due_on"] == "2026-11-05"


async def test_no_pasa_un_recurrente_a_una_cuenta_de_otra_moneda_rf21(
    client: AsyncClient, allow_more_currencies: None
) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    usd = await client.post("/v1/accounts", json={**CASH_BOB, "name": "Dólares", "currency": "USD"})
    assert usd.status_code == 201
    rent = await _rule(client, "housing", "1500.00", "2026-11-05")

    response = await client.patch(f"/v1/recurring-rules/{rent['id']}", json={"account_id": usd.json()["id"]})

    assert response.status_code == 422
    assert response.json()["code"] == "currency_mismatch"


async def test_una_cuenta_o_un_recurrente_ajenos_responden_404_rf30(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    rent = await _rule(client, "housing", "1500.00", "2026-11-05")

    unknown_account = await client.patch(f"/v1/recurring-rules/{rent['id']}", json={"account_id": str(uuid4())})
    assert unknown_account.status_code == 404

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other
    foreign = await client.patch(f"/v1/recurring-rules/{rent['id']}", json={"amount": "1.00"})
    assert foreign.status_code == 404
    assert (await client.get("/v1/recurring-rules")).json() == []


async def test_dar_de_baja_lo_saca_de_la_lista_rf31(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    rent = await _rule(client, "housing", "1500.00", "2026-11-05")

    assert (await client.delete(f"/v1/recurring-rules/{rent['id']}")).status_code == 204

    assert (await client.get("/v1/recurring-rules")).json() == []
    assert (await client.delete(f"/v1/recurring-rules/{rent['id']}")).status_code == 404


async def test_el_nombre_necesita_letras_o_numeros_bug003(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    category = await _category_id(client, "housing")
    body = {"category_id": category, "amount": "20.00"}

    for bad in ["-", "...", "🐶", "🐶🐱"]:
        response = await client.post("/v1/recurring-rules", json={**body, "description": bad})
        assert (response.status_code, response.json()["code"]) == (422, "validation_error"), bad

    for ok in ["wifi casa", "Luz 2", "Veterinario 🐶"]:
        response = await client.post("/v1/recurring-rules", json={**body, "description": ok})
        assert response.status_code == 201, ok

    rule = (await client.get("/v1/recurring-rules")).json()[0]
    patched = await client.patch(f"/v1/recurring-rules/{rule['id']}", json={"description": "🐱"})
    assert patched.status_code == 422


async def test_no_repite_el_mismo_recurrente_bug012(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    category_id = await _category_id(client, "groceries")
    coke = {"category_id": category_id, "amount": "12.00", "description": "Coca Cola", "frequency": "weekly"}
    first = await client.post("/v1/recurring-rules", json=coke)
    assert first.status_code == 201, first.text

    same = await client.post("/v1/recurring-rules", json={**coke, "description": " coca cola "})
    other_amount = await client.post("/v1/recurring-rules", json={**coke, "amount": "10.00", "frequency": "monthly"})
    edited_into_same = await client.patch(
        f"/v1/recurring-rules/{other_amount.json()['id']}", json={"amount": "12.00", "frequency": "weekly"}
    )

    assert (same.status_code, same.json()["code"]) == (409, "recurring_duplicate")
    assert other_amount.status_code == 201
    assert (edited_into_same.status_code, edited_into_same.json()["code"]) == (409, "recurring_duplicate")
    # Al borrar el primero, el mismo vuelve a poder crearse.
    assert (await client.delete(f"/v1/recurring-rules/{first.json()['id']}")).status_code == 204
    assert (await client.post("/v1/recurring-rules", json=coke)).status_code == 201


async def _period(client: AsyncClient) -> tuple[date, date]:
    body = (await client.get("/v1/safe-to-spend")).json()
    return date.fromisoformat(body["period_starts_on"]), date.fromisoformat(body["period_ends_on"])


async def _pending(client: AsyncClient, rule_id: str) -> list[str]:
    rules = (await client.get("/v1/recurring-rules")).json()
    dates: list[str] = next(rule["pending_dates"] for rule in rules if rule["id"] == rule_id)
    return dates


async def _created_before(user_id: UUID, rule_id: str, day: date) -> None:
    """Como si el fijo se hubiera registrado antes de vencer (la API siempre lo crea hoy)."""
    async with user_session(user_id) as session:
        await session.execute(
            text("UPDATE finance.recurring_rules SET created_at = CAST(:day AS date) + time '12:00' WHERE id = :id"),
            {"day": day - timedelta(days=5), "id": rule_id},
        )


async def test_un_gasto_sin_pagar_lista_lo_atrasado_y_lo_del_periodo_como_cuentas_por_pagar_rf23(
    client: AsyncClient, user_id: UUID
) -> None:
    """QA (2026-11-03): la lista de gastos fijos muestra octubre sin pagar y también noviembre."""
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, ends_on = await _period(client)
    overdue = starts_on - timedelta(days=1)
    rule = await _rule(client, "housing", "350.00", overdue.isoformat())
    await _created_before(user_id, rule["id"], overdue)

    dates = await _pending(client, rule["id"])

    assert dates[0] == overdue.isoformat()
    assert len(dates) == 2
    assert starts_on <= date.fromisoformat(dates[1]) <= ends_on
    # Lo mismo que suma Cuentas por pagar.
    pending = (await client.get("/v1/safe-to-spend")).json()["breakdown"]["pending_recurring"]
    assert Decimal(pending) == Decimal("350.00") * len(dates)


async def test_pagar_saca_la_mas_vieja_y_deja_la_siguiente_rf23(client: AsyncClient, user_id: UUID) -> None:
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    starts_on, _ = await _period(client)
    overdue = starts_on - timedelta(days=1)
    rule = await _rule(client, "housing", "350.00", overdue.isoformat())
    await _created_before(user_id, rule["id"], overdue)
    before = await _pending(client, rule["id"])

    paid = await client.post(
        f"/v1/recurring-rules/{rule['id']}/payments",
        json={"account_id": account},
        headers={"Idempotency-Key": str(uuid4())},
    )

    assert paid.status_code == 201, paid.text
    assert await _pending(client, rule["id"]) == before[1:]


async def test_un_gasto_al_dia_muestra_solo_su_proximo_vencimiento_rf23(client: AsyncClient) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    _, ends_on = await _period(client)
    next_period = ends_on + timedelta(days=10)
    rule = await _rule(client, "housing", "350.00", next_period.isoformat())

    assert await _pending(client, rule["id"]) == [next_period.isoformat()]


async def test_un_ingreso_fijo_tiene_una_sola_vez_rf23(client: AsyncClient, user_id: UUID) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, _ = await _period(client)
    overdue = starts_on - timedelta(days=1)
    rule = await _rule(client, "salary", "6000.00", overdue.isoformat())
    await _created_before(user_id, rule["id"], overdue)

    assert await _pending(client, rule["id"]) == [overdue.isoformat()]


async def test_un_gasto_viejo_recien_registrado_no_lista_todo_el_anio_rf23(client: AsyncClient) -> None:
    """Como en Cuentas por pagar: lo de antes de registrarlo no se debe, salvo la vez que toca pagar."""
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, ends_on = await _period(client)
    old = starts_on - timedelta(days=365)
    rule = await _rule(client, "housing", "350.00", old.isoformat())

    dates = await _pending(client, rule["id"])

    assert dates[0] == old.isoformat()
    assert all(starts_on <= date.fromisoformat(day) <= ends_on for day in dates[1:])
    assert len(dates) <= 2


async def test_no_lista_veces_despues_de_su_fecha_final_rf23(client: AsyncClient, user_id: UUID) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, _ = await _period(client)
    overdue = starts_on - timedelta(days=1)
    rule = await _rule(client, "housing", "350.00", overdue.isoformat())
    await _created_before(user_id, rule["id"], overdue)
    async with user_session(user_id) as session:
        await session.execute(
            text("UPDATE finance.recurring_rules SET end_date = :day WHERE id = :id"),
            {"day": overdue, "id": rule["id"]},
        )

    assert await _pending(client, rule["id"]) == [overdue.isoformat()]


async def test_un_gasto_semanal_lista_cada_semana_del_periodo_rf23(client: AsyncClient, user_id: UUID) -> None:
    assert (await client.post("/v1/accounts", json=CASH_BOB)).status_code == 201
    starts_on, ends_on = await _period(client)
    overdue = starts_on - timedelta(days=7)
    created = await client.post(
        "/v1/recurring-rules",
        json={
            "category_id": await _category_id(client, "transport"),
            "amount": "10.00",
            "description": "Pasajes",
            "frequency": "weekly",
            "start_date": overdue.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()["id"]
    await _created_before(user_id, rule, overdue)

    dates = [date.fromisoformat(day) for day in await _pending(client, rule)]

    assert dates[0] == overdue
    assert all(later - earlier == timedelta(days=7) for earlier, later in pairwise(dates))
    assert dates[-1] <= ends_on < dates[-1] + timedelta(days=7)
    pending = (await client.get("/v1/safe-to-spend")).json()["breakdown"]["pending_recurring"]
    assert Decimal(pending) == Decimal("10.00") * len(dates)


async def test_un_fijo_del_31_vuelve_al_31_despues_de_un_mes_corto_rf23(user_id: UUID) -> None:
    """La fórmula de `finance.next_occurrence`: cada fecha sale de `start_date`."""
    async with user_session(user_id) as session:
        rows = await session.execute(
            text(
                "SELECT due_on FROM finance.recurring_occurrences("
                "DATE '2026-01-31', 'monthly', DATE '2026-02-28', DATE '2026-03-31') AS occurrence(due_on)"
                " ORDER BY due_on"
            )
        )
        assert [row[0] for row in rows] == [date(2026, 2, 28), date(2026, 3, 31)]
