"""Categorías del usuario contra PostgreSQL 16 (spec 007).

RF cubiertos: RF-7 a RF-12 y RF-16. El RF-12 en los reportes está en
`test_reports_money_flow.py`.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app

PETS = {"name": "Mascotas", "type": "expense", "money_flow_group": "lifestyle"}
CASH_ACCOUNT = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _create(client: AsyncClient, **overrides: object) -> dict:
    response = await client.post("/v1/categories", json={**PETS, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def _expense(client: AsyncClient, category_id: str) -> None:
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    response = await client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": account["id"],
            "category_id": category_id,
            "amount": "35.00",
            "occurred_on": "2026-10-15",
            "description": "Croquetas",
        },
    )
    assert response.status_code == 201, response.text


async def test_crea_un_gasto_con_su_grupo_y_lo_lista_rf7(client: AsyncClient) -> None:
    created = await _create(client, name="  Mascotas  ", icon="pets", color="#F59E0B")

    assert created["name"] == "Mascotas"
    assert (created["type"], created["money_flow_group"]) == ("expense", "lifestyle")
    assert (created["icon"], created["color"], created["template_key"]) == ("pets", "#F59E0B", None)
    listed = (await client.get("/v1/categories", params={"type": "expense"})).json()
    assert created in listed


async def test_un_ingreso_va_sin_grupo_y_con_el_icono_por_defecto_rf7(client: AsyncClient) -> None:
    created = await _create(client, name="Ventas", type="income", money_flow_group=None)

    assert (created["type"], created["money_flow_group"]) == ("income", None)
    assert (created["icon"], created["color"]) == ("label", "#6B7280")


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Mascotas", "type": "expense"},
        {"name": "Ventas", "type": "income", "money_flow_group": "needs"},
        {"name": "   ", "type": "expense", "money_flow_group": "needs"},
        {"name": "x" * 61, "type": "expense", "money_flow_group": "needs"},
        {**PETS, "color": "rojo"},
    ],
    ids=["gasto_sin_grupo_rf8", "ingreso_con_grupo_rf8", "nombre_vacio_rf9", "nombre_largo_rf9", "color"],
)
async def test_rechaza_una_categoria_mal_armada(client: AsyncClient, payload: dict) -> None:
    response = await client.post("/v1/categories", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_el_mismo_nombre_en_el_mismo_tipo_responde_409(client: AsyncClient) -> None:
    await _create(client)

    repeated = await client.post("/v1/categories", json={**PETS, "name": "mascotas"})
    other_type = await client.post("/v1/categories", json={"name": "Mascotas", "type": "income"})

    assert repeated.status_code == 409
    assert repeated.json()["code"] == "category_name_taken"
    assert other_type.status_code == 201


async def test_corrige_solo_lo_que_se_envia_rf10(client: AsyncClient) -> None:
    created = await _create(client, icon="pets")

    response = await client.patch(f"/v1/categories/{created['id']}", json={"name": "Perro"})

    assert response.status_code == 200
    assert response.json() == {**created, "name": "Perro"}


async def test_cambia_de_tipo_si_no_la_usa_nadie_rf10(client: AsyncClient) -> None:
    created = await _create(client)

    to_income = await client.patch(f"/v1/categories/{created['id']}", json={"type": "income"})
    without_group = await client.patch(f"/v1/categories/{created['id']}", json={"type": "expense"})
    to_expense = await client.patch(
        f"/v1/categories/{created['id']}", json={"type": "expense", "money_flow_group": "needs"}
    )

    assert (to_income.json()["type"], to_income.json()["money_flow_group"]) == ("income", None)
    assert without_group.status_code == 422
    assert without_group.json()["code"] == "validation_error"
    assert (to_expense.json()["type"], to_expense.json()["money_flow_group"]) == ("expense", "needs")


async def test_con_movimientos_no_cambia_de_tipo_rf11(client: AsyncClient) -> None:
    created = await _create(client)
    await _expense(client, created["id"])

    response = await client.patch(f"/v1/categories/{created['id']}", json={"type": "income"})

    assert response.status_code == 409
    assert response.json()["code"] == "category_type_in_use"
    unchanged = await client.patch(f"/v1/categories/{created['id']}", json={"type": "expense", "name": "Perro"})
    assert unchanged.status_code == 200


async def test_con_un_recurrente_no_cambia_de_tipo_rf11(client: AsyncClient) -> None:
    created = await _create(client)
    await client.post("/v1/accounts", json=CASH_ACCOUNT)
    rule = await client.post(
        "/v1/recurring-rules", json={"category_id": created["id"], "amount": "50.00", "description": "Veterinario"}
    )
    assert rule.status_code == 201, rule.text

    response = await client.patch(f"/v1/categories/{created['id']}", json={"type": "income"})

    assert response.status_code == 409


async def test_borra_la_categoria_y_el_movimiento_queda_rf12(client: AsyncClient) -> None:
    created = await _create(client)
    await _expense(client, created["id"])

    response = await client.delete(f"/v1/categories/{created['id']}")

    assert response.status_code == 204
    assert created["id"] not in {item["id"] for item in (await client.get("/v1/categories")).json()}
    history = (await client.get("/v1/transactions")).json()["items"]
    assert [item["category_id"] for item in history] == [created["id"]]
    assert (await client.delete(f"/v1/categories/{created['id']}")).status_code == 404
    assert (await client.patch(f"/v1/categories/{created['id']}", json={"name": "X"})).status_code == 404


async def test_la_categoria_de_otro_usuario_responde_404_rf16(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other_client:
        foreign = await _create(other_client)
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    patched = await client.patch(f"/v1/categories/{foreign['id']}", json={"name": "Mía"})
    deleted = await client.delete(f"/v1/categories/{foreign['id']}")

    assert (patched.status_code, deleted.status_code) == (404, 404)
    assert patched.json()["code"] == "not_found"


async def test_no_registra_en_una_categoria_borrada_pero_lo_viejo_se_edita_rf12(client: AsyncClient) -> None:
    created = await _create(client)
    await _expense(client, created["id"])
    other = await _create(client, name="Veterinario")
    await client.delete(f"/v1/categories/{created['id']}")
    await client.delete(f"/v1/categories/{other['id']}")
    old = (await client.get("/v1/transactions")).json()["items"][0]

    new = await client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": old["account_id"],
            "category_id": created["id"],
            "amount": "10.00",
            "occurred_on": "2026-10-16",
        },
    )
    moved = await client.patch(f"/v1/transactions/{old['id']}", json={"category_id": other["id"]})
    rule = await client.post(
        "/v1/recurring-rules", json={"category_id": created["id"], "amount": "50.00", "description": "Veterinario"}
    )
    edited = await client.patch(f"/v1/transactions/{old['id']}", json={"amount": "40.00"})

    assert (new.status_code, moved.status_code, rule.status_code) == (404, 404, 404)
    assert new.json()["code"] == "not_found"
    assert edited.status_code == 200


async def test_con_recurrentes_no_se_borra_hasta_quitarlos(client: AsyncClient) -> None:
    created = await _create(client)
    await client.post("/v1/accounts", json=CASH_ACCOUNT)
    rule = (
        await client.post(
            "/v1/recurring-rules", json={"category_id": created["id"], "amount": "50.00", "description": "Veterinario"}
        )
    ).json()

    blocked = await client.delete(f"/v1/categories/{created['id']}")
    await client.delete(f"/v1/recurring-rules/{rule['id']}")
    allowed = await client.delete(f"/v1/categories/{created['id']}")

    assert blocked.status_code == 409
    assert blocked.json()["code"] == "category_in_use"
    assert "1 recurrente" in blocked.json()["detail"]
    assert allowed.status_code == 204


async def test_el_nombre_de_una_categoria_va_sin_emojis_bug010_bug011(client: AsyncClient) -> None:
    for name in ["zapatos 👟", "🐶", "⌚ Reloj", "-"]:
        for kind, group in [("expense", "lifestyle"), ("income", None)]:
            body = {"name": name, "type": kind, "money_flow_group": group, "icon": "redeem", "color": "#3E4BD2"}
            response = await client.post("/v1/categories", json=body)
            assert (response.status_code, response.json()["code"]) == (422, "validation_error"), (name, kind)
    ok = {"name": "Zapatos", "type": "expense", "money_flow_group": "lifestyle", "icon": "redeem", "color": "#3E4BD2"}
    assert (await client.post("/v1/categories", json=ok)).status_code == 201
