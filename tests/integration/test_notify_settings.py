"""Ajustes de aviso contra PostgreSQL 16 (spec 006, RF-11 y RF-12)."""

import pytest
from httpx import AsyncClient


async def _enabled(client: AsyncClient) -> dict[str, bool]:
    response = await client.get("/v1/me/notification-settings")
    assert response.status_code == 200, response.text
    return {item["type"]: item["enabled"] for item in response.json()["items"]}


async def test_todos_encendidos_por_defecto_y_los_de_seguridad_no_se_apagan_rf11(client: AsyncClient) -> None:
    items = (await client.get("/v1/me/notification-settings")).json()["items"]

    by_type = {item["type"]: item for item in items}
    assert all(item["enabled"] for item in items)
    assert by_type["goal.milestone"]["can_disable"] is True
    assert by_type["security.new_login"]["can_disable"] is False
    assert by_type["money_story.ready"]["description"] == "Tu Monthly Money Story está lista"


async def test_apaga_y_vuelve_a_encender_solo_lo_enviado_rf11(client: AsyncClient) -> None:
    off = await client.put(
        "/v1/me/notification-settings", json={"items": [{"type": "goal.milestone", "enabled": False}]}
    )
    on = await client.put("/v1/me/notification-settings", json={"items": [{"type": "goal.milestone", "enabled": True}]})

    assert off.status_code == 200
    assert {item["type"]: item["enabled"] for item in off.json()["items"]}["goal.milestone"] is False
    assert {item["type"]: item["enabled"] for item in on.json()["items"]}["goal.milestone"] is True
    assert all((await _enabled(client)).values())


@pytest.mark.parametrize("type_key", ["budget.alert", "security.new_login"], ids=["no_existe", "transaccional"])
async def test_rechaza_lo_que_no_sirve_y_no_cambia_nada_rf12(client: AsyncClient, type_key: str) -> None:
    response = await client.put(
        "/v1/me/notification-settings",
        json={"items": [{"type": "goal.milestone", "enabled": False}, {"type": type_key, "enabled": False}]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert all((await _enabled(client)).values())
