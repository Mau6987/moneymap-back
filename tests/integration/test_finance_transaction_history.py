"""El historial de movimientos y el borrado (spec 002).

RF cubiertos: RF-26 y RF-27.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.core.dependencies import get_current_user_id
from app.main import app

CASH_BOB = {"type": "cash", "currency": "BOB"}


@dataclass(frozen=True)
class Ledger:
    """Dos cuentas en Bs y una categoría de gasto."""

    client: AsyncClient
    account: str
    other_account: str
    category: str

    async def spend(self, amount: str, occurred_on: str, account: str | None = None) -> str:
        response = await self.client.post(
            "/v1/transactions",
            json={
                "kind": "expense",
                "account_id": account or self.account,
                "category_id": self.category,
                "amount": amount,
                "occurred_on": occurred_on,
            },
        )
        assert response.status_code == 201
        return str(response.json()["id"])


@pytest.fixture
async def ledger(client: AsyncClient, user_id: UUID) -> Ledger:
    first = await client.post("/v1/accounts", json={**CASH_BOB, "name": "Efectivo", "opening_balance": "1000.00"})
    second = await client.post("/v1/accounts", json={**CASH_BOB, "name": "Ahorro", "opening_balance": "500.00"})
    async with user_session(user_id) as session:
        category = (
            await session.execute(
                text("SELECT id FROM finance.categories WHERE user_id = :user_id AND kind = 'expense' LIMIT 1"),
                {"user_id": user_id},
            )
        ).scalar_one()
    return Ledger(client, str(first.json()["id"]), str(second.json()["id"]), str(category))


async def test_pagina_del_mas_reciente_al_mas_viejo_rf26(ledger: Ledger) -> None:
    oldest = await ledger.spend("10.00", "2026-10-01")
    middle = await ledger.spend("20.00", "2026-10-05")
    newest = await ledger.spend("30.00", "2026-10-09")

    first = await ledger.client.get("/v1/transactions", params={"limit": 2})
    assert first.status_code == 200
    page = first.json()
    assert [item["id"] for item in page["items"]] == [newest, middle]
    assert page["items"][0]["amount"] == "30.00"
    assert page["items"][0]["currency"] == "BOB"

    second = (await ledger.client.get("/v1/transactions", params={"limit": 2, "cursor": page["next_cursor"]})).json()
    assert [item["id"] for item in second["items"]] == [oldest]
    assert second["next_cursor"] is None


async def test_dos_movimientos_del_mismo_dia_no_se_repiten_ni_se_pierden_rf26(ledger: Ledger) -> None:
    created = {await ledger.spend("5.00", "2026-10-03") for _ in range(3)}

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, str | int] = {"limit": 1} if cursor is None else {"limit": 1, "cursor": cursor}
        page = (await ledger.client.get("/v1/transactions", params=params)).json()
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == 3
    assert set(seen) == created


async def test_por_cuenta_incluye_las_transferencias_que_llegan_rf26(ledger: Ledger) -> None:
    await ledger.spend("10.00", "2026-10-01")
    other_expense = await ledger.spend("15.00", "2026-10-02", account=ledger.other_account)
    transfer = await ledger.client.post(
        "/v1/transactions",
        json={
            "kind": "transfer",
            "account_id": ledger.account,
            "transfer_account_id": ledger.other_account,
            "amount": "100.00",
            "occurred_on": "2026-10-03",
        },
    )
    assert transfer.status_code == 201

    page = (await ledger.client.get("/v1/transactions", params={"account_id": ledger.other_account})).json()

    assert [item["id"] for item in page["items"]] == [transfer.json()["id"], other_expense]


async def test_no_muestra_los_movimientos_de_otro_usuario_rf26(
    ledger: Ledger, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    await ledger.spend("10.00", "2026-10-01")

    other = await new_financial_user()
    app.dependency_overrides[get_current_user_id] = lambda: other

    assert (await ledger.client.get("/v1/transactions")).json() == {"items": [], "next_cursor": None}


async def test_un_cursor_inventado_responde_422_rf26(ledger: Ledger) -> None:
    response = await ledger.client.get("/v1/transactions", params={"cursor": "no-es-un-cursor"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cursor"


async def test_borrar_devuelve_el_saldo_y_lo_saca_del_historial_rf27(ledger: Ledger) -> None:
    expense = await ledger.spend("250.00", "2026-10-01")

    response = await ledger.client.delete(f"/v1/transactions/{expense}")

    assert response.status_code == 204
    accounts = {account["id"]: account for account in (await ledger.client.get("/v1/accounts")).json()}
    assert accounts[ledger.account]["current_balance"] == "1000.00"
    assert (await ledger.client.get("/v1/transactions")).json()["items"] == []


async def test_borrar_dos_veces_o_uno_ajeno_responde_404_rf27(ledger: Ledger) -> None:
    expense = await ledger.spend("10.00", "2026-10-01")
    assert (await ledger.client.delete(f"/v1/transactions/{expense}")).status_code == 204

    assert (await ledger.client.delete(f"/v1/transactions/{expense}")).status_code == 404
    assert (await ledger.client.delete(f"/v1/transactions/{uuid4()}")).status_code == 404
