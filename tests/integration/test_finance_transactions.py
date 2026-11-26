"""Registrar, transferir y corregir movimientos (spec 002).

RF cubiertos: RF-6 a RF-8, RF-10 a RF-13, y el requisito no funcional de
idempotencia de `POST /v1/transactions`.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session

CASH_BOB = {"type": "cash", "currency": "BOB"}
EXPENSE = {"amount": "25.50", "occurred_on": "2026-10-15", "description": "Almuerzo"}


@dataclass(frozen=True)
class MoneyEnv:
    """El usuario de la prueba con dos cuentas en Bs y una categoría de cada tipo."""

    client: AsyncClient
    user_id: UUID
    account: str
    other_account: str
    expense_category: str
    income_category: str


@pytest.fixture
async def money(client: AsyncClient, user_id: UUID) -> MoneyEnv:
    first = await client.post("/v1/accounts", json={**CASH_BOB, "name": "Efectivo", "opening_balance": "1000.00"})
    second = await client.post("/v1/accounts", json={**CASH_BOB, "name": "Ahorro", "opening_balance": "500.00"})
    assert (first.status_code, second.status_code) == (201, 201)
    async with user_session(user_id) as session:
        expense = (
            await session.execute(
                text("SELECT id FROM finance.categories WHERE user_id = :user_id AND kind = 'expense' LIMIT 1"),
                {"user_id": user_id},
            )
        ).scalar_one()
        income = (
            await session.execute(
                text("SELECT id FROM finance.categories WHERE user_id = :user_id AND kind = 'income' LIMIT 1"),
                {"user_id": user_id},
            )
        ).scalar_one()
    return MoneyEnv(
        client=client,
        user_id=user_id,
        account=str(first.json()["id"]),
        other_account=str(second.json()["id"]),
        expense_category=str(expense),
        income_category=str(income),
    )


async def _amount_of_movements(user_id: UUID) -> int:
    async with user_session(user_id) as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM finance.transactions WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
        ).scalar_one()


async def test_registra_un_gasto_en_la_moneda_de_su_cuenta_rf6(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "expense"
    assert body["currency"] == "BOB"  # la puso la cuenta, no la petición
    assert body["amount"] == "25.50"
    assert body["description"] == "Almuerzo"
    assert body["source"] == "manual"
    assert body["account_balance"] == "974.50"  # 1000 menos el gasto
    assert body["transfer_account_balance"] is None


async def test_registra_un_ingreso_y_sube_el_saldo_rf6(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "income",
            "account_id": money.account,
            "category_id": money.income_category,
            "amount": "800.00",
            "occurred_on": "2026-10-15",
        },
    )

    assert response.status_code == 201
    assert response.json()["account_balance"] == "1800.00"


async def test_rechaza_una_moneda_distinta_a_la_de_la_cuenta_rf7(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": money.account,
            "category_id": money.expense_category,
            "currency": "USD",
            **EXPENSE,
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "currency_mismatch"
    assert "BOB" in body["detail"]
    assert await _amount_of_movements(money.user_id) == 0


async def test_rechaza_un_monto_con_mas_decimales_que_la_moneda_rf8(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": money.account,
            "category_id": money.expense_category,
            "amount": "10.005",
            "occurred_on": "2026-10-15",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_amount"


async def test_rechaza_un_monto_que_no_es_positivo_rf8(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": money.account,
            "category_id": money.expense_category,
            "amount": "0",
            "occurred_on": "2026-10-15",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_amount"


async def test_una_cuenta_que_no_es_del_usuario_responde_404(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": str(uuid4()), "category_id": money.expense_category, **EXPENSE},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_una_categoria_de_otro_tipo_se_rechaza(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, "category_id": money.income_category, **EXPENSE},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_valida_que_campos_van_juntos(money: MoneyEnv) -> None:
    sin_categoria = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, **EXPENSE},
    )
    assert sin_categoria.status_code == 422
    assert sin_categoria.json()["code"] == "validation_error"

    transfer_sin_destino = await money.client.post(
        "/v1/transactions",
        json={"kind": "transfer", "account_id": money.account, **EXPENSE},
    )
    assert transfer_sin_destino.status_code == 422

    gasto_con_destino = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": money.account,
            "category_id": money.expense_category,
            "transfer_account_id": money.other_account,
            **EXPENSE,
        },
    )
    assert gasto_con_destino.status_code == 422

    transfer_con_categoria = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "transfer",
            "account_id": money.account,
            "transfer_account_id": money.other_account,
            "category_id": money.expense_category,
            **EXPENSE,
        },
    )
    assert transfer_con_categoria.status_code == 422

    assert await _amount_of_movements(money.user_id) == 0


async def test_una_transferencia_mueve_las_dos_cuentas_rf10(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "transfer",
            "account_id": money.account,
            "transfer_account_id": money.other_account,
            "amount": "100.00",
            "occurred_on": "2026-10-15",
            "description": "Al ahorro",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["account_balance"] == "900.00"  # sale de la de origen
    assert body["transfer_account_balance"] == "600.00"  # entra en la de destino
    assert body["category_id"] is None


async def test_no_transfiere_entre_monedas_distintas_rf11(money: MoneyEnv, allow_more_currencies: None) -> None:
    # La segunda cuenta se corrige a USD mientras no se usó (RF-14).
    changed = await money.client.patch(f"/v1/accounts/{money.other_account}", json={"currency": "USD"})
    assert changed.status_code == 200

    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "transfer",
            "account_id": money.account,
            "transfer_account_id": money.other_account,
            "amount": "100.00",
            "occurred_on": "2026-10-15",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "transfer_currency_mismatch"


async def test_no_transfiere_a_la_misma_cuenta_rf12(money: MoneyEnv) -> None:
    response = await money.client.post(
        "/v1/transactions",
        json={
            "kind": "transfer",
            "account_id": money.account,
            "transfer_account_id": money.account,
            "amount": "100.00",
            "occurred_on": "2026-10-15",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_transfer_target"


async def test_corrige_el_monto_y_reajusta_el_saldo_rf13(money: MoneyEnv) -> None:
    created = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE},
    )
    movement = created.json()["id"]

    response = await money.client.patch(f"/v1/transactions/{movement}", json={"amount": "30.00"})

    assert response.status_code == 200
    assert response.json()["amount"] == "30.00"
    assert response.json()["account_balance"] == "970.00"  # el saldo se reajustó

    only_description = await money.client.patch(
        f"/v1/transactions/{movement}", json={"description": "Almuerzo con Ana"}
    )
    assert only_description.status_code == 200
    assert only_description.json()["description"] == "Almuerzo con Ana"
    assert only_description.json()["account_balance"] == "970.00"


async def test_no_cambia_un_movimiento_a_una_cuenta_de_otra_moneda_rf13(
    money: MoneyEnv, allow_more_currencies: None
) -> None:
    changed = await money.client.patch(f"/v1/accounts/{money.other_account}", json={"currency": "USD"})
    assert changed.status_code == 200
    created = await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE},
    )

    response = await money.client.patch(
        f"/v1/transactions/{created.json()['id']}", json={"account_id": money.other_account}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "currency_mismatch"
    # El movimiento queda como estaba: el gasto sigue descontado de su cuenta.
    balances = {row["currency"]: row["total"] for row in (await money.client.get("/v1/balances")).json()}
    assert balances == {"BOB": "974.50", "USD": "500.00"}


async def test_corrige_un_movimiento_que_no_existe_responde_404(money: MoneyEnv) -> None:
    response = await money.client.patch(f"/v1/transactions/{uuid4()}", json={"amount": "5.00"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_la_misma_clave_de_idempotencia_no_duplica_el_movimiento(money: MoneyEnv) -> None:
    body = {
        "kind": "expense",
        "account_id": money.account,
        "category_id": money.expense_category,
        **EXPENSE,
    }
    headers = {"Idempotency-Key": "cafe-de-la-manana"}

    first = await money.client.post("/v1/transactions", json=body, headers=headers)
    second = await money.client.post("/v1/transactions", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["account_balance"] == second.json()["account_balance"]
    assert await _amount_of_movements(money.user_id) == 1  # una sola fila

    other_key = await money.client.post("/v1/transactions", json=body, headers={"Idempotency-Key": "otra-clave"})
    assert other_key.json()["id"] != first.json()["id"]
    assert await _amount_of_movements(money.user_id) == 2

    without_key = await money.client.post("/v1/transactions", json=body)
    assert without_key.status_code == 201
    assert await _amount_of_movements(money.user_id) == 3


async def test_el_saldo_de_los_totales_sigue_al_movimiento_rf6(money: MoneyEnv) -> None:
    await money.client.post(
        "/v1/transactions",
        json={"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE},
    )

    balances = (await money.client.get("/v1/balances")).json()

    assert len(balances) == 1  # las dos cuentas están en Bs
    assert balances[0]["total"] == "1474.50"  # 1000 + 500 menos el gasto


@pytest.mark.parametrize("description", ["-", "...", "🐶", "🐶🐱", "$%&"])
async def test_una_descripcion_sin_texto_responde_422_bug050(money: MoneyEnv, description: str) -> None:
    body = {"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE}

    response = await money.client.post("/v1/transactions", json={**body, "description": description})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert await _amount_of_movements(money.user_id) == 0


async def test_la_descripcion_es_opcional_y_se_guarda_sin_espacios_de_mas_bug050(money: MoneyEnv) -> None:
    body = {"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE}

    spaced = await money.client.post("/v1/transactions", json={**body, "description": "  Almuerzo   con\tAna  "})
    blank = await money.client.post("/v1/transactions", json={**body, "description": "   "})
    emoji = await money.client.post("/v1/transactions", json={**body, "description": "Netflix 🎬"})

    assert spaced.json()["description"] == "Almuerzo con Ana"
    assert blank.status_code == 201
    assert blank.json()["description"] == ""
    assert emoji.json()["description"] == "Netflix 🎬"


async def test_editar_con_una_descripcion_sin_texto_responde_422_bug050(money: MoneyEnv) -> None:
    body = {"kind": "expense", "account_id": money.account, "category_id": money.expense_category, **EXPENSE}
    movement = (await money.client.post("/v1/transactions", json=body)).json()["id"]

    bad = await money.client.patch(f"/v1/transactions/{movement}", json={"description": "🐶"})
    too_long = await money.client.patch(f"/v1/transactions/{movement}", json={"description": "a" * 201})

    assert (bad.status_code, too_long.status_code) == (422, 422)
    listed = (await money.client.get("/v1/transactions")).json()["items"]
    assert listed[0]["description"] == "Almuerzo"
