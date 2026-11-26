"""Bugs de QA de la migración 0021 contra PostgreSQL 16.

BUG-027: gasto fijo sin cuenta, la cuenta se elige al pagar. BUG-028: pagar un
gasto fijo sin saldo. BUG-029: transferir sin saldo. BUG-030: metas con el
mismo nombre.
"""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

GOAL = {"target_amount": "5000.00", "currency": "BOB", "priority": 1}


async def _account(client: AsyncClient, name: str, balance: str) -> str:
    body = {"name": name, "type": "cash", "currency": "BOB", "opening_balance": balance}
    response = await client.post("/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def _balance(client: AsyncClient, account_id: str) -> str:
    balance: str = next(
        a["current_balance"] for a in (await client.get("/v1/accounts")).json() if a["id"] == account_id
    )
    return balance


async def _rule(client: AsyncClient, amount: str, **extra: str) -> dict[str, str]:
    categories = (await client.get("/v1/categories")).json()
    category = next(item["id"] for item in categories if item["template_key"] == "housing")
    body = {"category_id": category, "amount": amount, "description": "Alquiler", **extra}
    response = await client.post("/v1/recurring-rules", json=body)
    assert response.status_code == 201, response.text
    rule: dict[str, str] = response.json()
    return rule


async def test_transferir_mas_del_saldo_responde_422_bug029(client: AsyncClient) -> None:
    source = await _account(client, "Efectivo", "100.00")
    target = await _account(client, "Ahorro", "0.00")
    transfer = {"kind": "transfer", "account_id": source, "transfer_account_id": target, "occurred_on": "2026-10-20"}

    too_much = await client.post("/v1/transactions", json={**transfer, "amount": "150.00"})
    exact = await client.post("/v1/transactions", json={**transfer, "amount": "100.00"})

    assert (too_much.status_code, too_much.json()["code"]) == (422, "account_insufficient")
    assert exact.status_code == 201, exact.text
    assert (await _balance(client, source), await _balance(client, target)) == ("0.00", "100.00")


async def test_un_gasto_mayor_que_el_saldo_responde_422_bug024(client: AsyncClient) -> None:
    """Decisión del 2026-10-31: un gasto común tampoco deja la cuenta en negativo."""
    account = await _account(client, "Efectivo", "100.00")
    categories = (await client.get("/v1/categories")).json()
    expense_category = next(item["id"] for item in categories if item["template_key"] == "housing")
    income_category = next(item["id"] for item in categories if item["template_key"] == "salary")
    body = {"account_id": account, "occurred_on": "2026-10-20"}

    too_much = await client.post(
        "/v1/transactions", json={**body, "kind": "expense", "category_id": expense_category, "amount": "150.00"}
    )
    exact = await client.post(
        "/v1/transactions", json={**body, "kind": "expense", "category_id": expense_category, "amount": "100.00"}
    )
    income = await client.post(
        "/v1/transactions", json={**body, "kind": "income", "category_id": income_category, "amount": "5000.00"}
    )

    assert (too_much.status_code, too_much.json()["code"]) == (422, "account_insufficient")
    assert (exact.status_code, income.status_code) == (201, 201)
    assert await _balance(client, account) == "5000.00"


async def test_pagar_un_gasto_fijo_sin_saldo_responde_422_bug028(client: AsyncClient) -> None:
    account = await _account(client, "Efectivo", "100.00")
    rule = await _rule(client, "150.00", account_id=account)

    response = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})

    assert (response.status_code, response.json()["code"]) == (422, "account_insufficient")
    assert await _balance(client, account) == "100.00"


async def test_gasto_fijo_sin_cuenta_se_paga_con_la_que_se_elija_bug027(client: AsyncClient) -> None:
    await _account(client, "Efectivo", "100.00")
    card = await _account(client, "Tarjeta", "500.00")
    rule = await _rule(client, "150.00", currency="BOB")
    assert (rule["account_id"], rule["currency"]) == (None, "BOB")

    without = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={})
    paid = await client.post(f"/v1/recurring-rules/{rule['id']}/payments", json={"account_id": card})

    assert (without.status_code, without.json()["code"]) == (422, "account_required")
    assert paid.status_code == 201, paid.text
    assert paid.json()["transaction"]["account_id"] == card
    assert await _balance(client, card) == "350.00"


async def test_sin_cuenta_ni_moneda_va_a_la_cuenta_por_defecto(client: AsyncClient) -> None:
    account = await _account(client, "Efectivo", "100.00")

    rule = await _rule(client, "50.00")

    assert (rule["account_id"], rule["currency"]) == (account, "BOB")


async def test_dos_metas_no_se_llaman_igual_bug030(client: AsyncClient) -> None:
    first = await client.post("/v1/goals", json={**GOAL, "name": "Viaje"})
    assert first.status_code == 201, first.text

    same = await client.post("/v1/goals", json={**GOAL, "name": " viaje "})
    other = await client.post("/v1/goals", json={**GOAL, "name": "Laptop"})
    renamed = await client.patch(f"/v1/goals/{other.json()['id']}", json={"name": "VIAJE"})

    assert (same.status_code, same.json()["code"]) == (409, "goal_name_taken")
    assert (renamed.status_code, renamed.json()["code"]) == (409, "goal_name_taken")
    # Borrada, el nombre queda libre.
    assert (await client.delete(f"/v1/goals/{first.json()['id']}")).status_code == 204
    assert (await client.post("/v1/goals", json={**GOAL, "name": "Viaje"})).status_code == 201


async def _transfer(client: AsyncClient, source: str, target: str, amount: str) -> str:
    body = {
        "kind": "transfer",
        "account_id": source,
        "transfer_account_id": target,
        "amount": amount,
        "occurred_on": "2026-10-20",
    }
    response = await client.post("/v1/transactions", json=body)
    assert response.status_code == 201, response.text
    transaction_id: str = response.json()["id"]
    return transaction_id


async def test_editar_una_transferencia_no_pasa_el_saldo_bug029(client: AsyncClient) -> None:
    source = await _account(client, "Efectivo", "100.00")
    target = await _account(client, "Ahorro", "0.00")
    empty = await _account(client, "Vacía", "0.00")
    transfer = await _transfer(client, source, target, "10.00")

    too_much = await client.patch(f"/v1/transactions/{transfer}", json={"amount": "110.01"})
    other_account = await client.patch(f"/v1/transactions/{transfer}", json={"account_id": empty})
    all_of_it = await client.patch(f"/v1/transactions/{transfer}", json={"amount": "100.00"})

    assert (too_much.status_code, too_much.json()["code"]) == (422, "account_insufficient")
    assert (other_account.status_code, other_account.json()["code"]) == (422, "account_insufficient")
    assert all_of_it.status_code == 200, all_of_it.text
    assert (await _balance(client, source), await _balance(client, target)) == ("0.00", "100.00")


async def test_corregir_una_transferencia_con_la_cuenta_en_negativo_si_se_puede(
    client: AsyncClient, owner_connection: AsyncConnection
) -> None:
    source = await _account(client, "Efectivo", "100.00")
    target = await _account(client, "Ahorro", "0.00")
    transfer = await _transfer(client, source, target, "80.00")
    # Una cuenta que ya estaba en negativo (datos de antes de BUG-024): 20 − 50 = −30.
    await owner_connection.execute(
        text("UPDATE finance.accounts SET current_balance = current_balance - 50 WHERE id = :id"), {"id": source}
    )
    await owner_connection.commit()

    described = await client.patch(f"/v1/transactions/{transfer}", json={"description": "A la caja de ahorro"})
    smaller = await client.patch(f"/v1/transactions/{transfer}", json={"amount": "60.00"})

    # La cuenta queda en -30 por el gasto: corregir sin sacar más no se frena.
    assert (described.status_code, smaller.status_code) == (200, 200)
    assert await _balance(client, source) == "-10.00"
