"""El panel de administrador de los planes (MM-189, spec 013).

Cambia datos de todos (límites y precios de los planes), así que cada prueba
deja todo como estaba. El índice único de `is_admin` permite un solo
administrador: si ya hay uno en la base, se lo saca mientras dura la prueba.
"""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.fixture
async def admin(user_id: UUID, owner_connection: AsyncConnection) -> AsyncIterator[UUID]:
    """El usuario de la prueba pasa a ser el administrador; al terminar, vuelve el de antes."""
    previous = (await owner_connection.execute(text("SELECT id FROM iam.users WHERE is_admin"))).scalar_one_or_none()
    await owner_connection.execute(text("UPDATE iam.users SET is_admin = false WHERE is_admin"))
    await owner_connection.execute(text("UPDATE iam.users SET is_admin = true WHERE id = :id"), {"id": user_id})
    await owner_connection.commit()
    yield user_id
    await owner_connection.execute(text("UPDATE iam.users SET is_admin = false WHERE id = :id"), {"id": user_id})
    if previous is not None:
        await owner_connection.execute(text("UPDATE iam.users SET is_admin = true WHERE id = :id"), {"id": previous})
    await owner_connection.commit()


def _feature(plan: dict[str, object], key: str) -> dict[str, object]:
    features = plan["features"]
    assert isinstance(features, list)
    found: dict[str, object] = next(f for f in features if f["key"] == key)
    return found


async def test_para_cualquier_otro_usuario_el_panel_no_existe(client: AsyncClient) -> None:
    assert (await client.get("/v1/admin/plans")).status_code == 404
    refused = await client.put("/v1/admin/plans/free/features/goals.active", json={"enabled": True, "limit": 99})
    assert refused.status_code == 404
    assert (await client.get("/v1/me")).json()["is_admin"] is False


async def test_el_admin_ve_los_dos_planes_con_todo_lo_editable(client: AsyncClient, admin: UUID) -> None:
    response = await client.get("/v1/admin/plans")

    assert response.status_code == 200
    plans = response.json()
    assert [p["code"] for p in plans] == ["free", "paid_3"]
    free = plans[0]
    assert free["subscribers"] >= 1  # el admin de la prueba no paga
    assert _feature(free, "goals.active") | {"description": ""} == {
        "key": "goals.active",
        "description": "",
        "kind": "limit",
        "period": "total",
        "enabled": True,
        "limit": None,
    }
    assert {(p["period"], p["currency"], p["amount"]) for p in plans[1]["prices"]} == {
        ("month", "BOB", "79.00"),
        ("year", "BOB", "790.00"),
    }
    assert (await client.get("/v1/me")).json()["is_admin"] is True


async def test_cambia_el_limite_de_una_funcionalidad_y_vale_al_instante(client: AsyncClient, admin: UUID) -> None:
    try:
        response = await client.put("/v1/admin/plans/free/features/goals.active", json={"enabled": True, "limit": 3})
        assert response.status_code == 204

        goals = next(f for f in (await client.get("/v1/me/plan")).json()["features"] if f["key"] == "goals.active")
        assert goals["limit"] == 3
    finally:
        await client.put("/v1/admin/plans/free/features/goals.active", json={"enabled": True, "limit": None})


async def test_reglas_de_las_funcionalidades(client: AsyncClient, admin: UUID) -> None:
    on_off = await client.put("/v1/admin/plans/free/features/notify.push", json={"enabled": True, "limit": 5})
    negative = await client.put("/v1/admin/plans/free/features/goals.active", json={"enabled": True, "limit": -1})
    missing = await client.put("/v1/admin/plans/free/features/no.existe", json={"enabled": True, "limit": None})

    assert (on_off.status_code, on_off.json()["code"]) == (422, "invalid_limit")
    assert negative.status_code == 422
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")


async def test_edita_nombre_y_el_gratuito_no_se_oculta(client: AsyncClient, admin: UUID) -> None:
    premium = next(p for p in (await client.get("/v1/admin/plans")).json() if p["code"] == "paid_3")
    try:
        renamed = await client.patch(
            "/v1/admin/plans/paid_3", json={"name": "Premium+", "description": "Más de todo", "is_public": True}
        )
        assert renamed.status_code == 204
        assert next(p for p in (await client.get("/v1/plans")).json() if p["code"] == "paid_3")["name"] == "Premium+"
    finally:
        await client.patch(
            "/v1/admin/plans/paid_3",
            json={"name": premium["name"], "description": premium["description"], "is_public": premium["is_public"]},
        )

    hidden = await client.patch("/v1/admin/plans/free", json={"name": "Gratuito", "is_public": False})
    assert (hidden.status_code, hidden.json()["code"]) == (409, "free_plan_required")


async def test_un_precio_nuevo_cierra_el_anterior_y_queda_en_el_historial(client: AsyncClient, admin: UUID) -> None:
    try:
        response = await client.put("/v1/admin/plans/paid_3/prices/month/BOB", json={"amount": "85.00"})
        assert response.status_code == 204

        premium = next(p for p in (await client.get("/v1/admin/plans")).json() if p["code"] == "paid_3")
        assert ("month", "BOB", "85.00") in {(p["period"], p["currency"], p["amount"]) for p in premium["prices"]}
        changes = (await client.get("/v1/admin/plan-changes", params={"limit": 5})).json()
        assert any(c["entity"] == "billing.plan_prices" and c["action"] == "insert" for c in changes)
    finally:
        await client.put("/v1/admin/plans/paid_3/prices/month/BOB", json={"amount": "79.00"})

    free_price = await client.put("/v1/admin/plans/free/prices/month/BOB", json={"amount": "1.00"})
    assert (free_price.status_code, free_price.json()["code"]) == (409, "free_plan_required")
