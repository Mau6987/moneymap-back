"""Dispositivos para avisos contra PostgreSQL 16 (spec 006, RF-8 a RF-10 y RF-21)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.dependencies import get_current_user_id
from app.main import app

PHONE = {"platform": "android", "push_token": "fcm-token-de-prueba", "app_version": "1.0.0", "os_version": "14"}


async def _active_owners(token: str) -> list[UUID]:
    async with SessionLocal() as session:
        rows = await session.execute(
            text("SELECT user_id FROM iam.devices WHERE push_token = :token AND revoked_at IS NULL"), {"token": token}
        )
        return list(rows.scalars())


async def _as(user_id: UUID) -> AsyncClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_registra_sin_devolver_el_token_y_reactiva_el_mismo_rf8(client: AsyncClient, user_id: UUID) -> None:
    first = await client.post("/v1/me/devices", json=PHONE)
    again = await client.post("/v1/me/devices", json={**PHONE, "app_version": "1.0.1"})

    assert first.status_code == again.status_code == 201
    assert "push_token" not in first.json()
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["app_version"] == "1.0.1"
    assert await _active_owners(PHONE["push_token"]) == [user_id]


async def test_el_token_de_otra_cuenta_pasa_a_la_actual_rf9(
    client: AsyncClient, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    await client.post("/v1/me/devices", json=PHONE)
    other = await new_financial_user("BOB")

    async with await _as(other) as other_client:
        response = await other_client.post("/v1/me/devices", json=PHONE)

    assert response.status_code == 201
    assert await _active_owners(PHONE["push_token"]) == [other]


async def test_da_de_baja_y_el_de_otro_es_404_rf10_rf21(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    device_id = (await client.post("/v1/me/devices", json=PHONE)).json()["id"]
    other = await new_financial_user("BOB")

    async with await _as(other) as other_client:
        theirs = await other_client.delete(f"/v1/me/devices/{device_id}")
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    mine = await client.delete(f"/v1/me/devices/{device_id}")
    twice = await client.delete(f"/v1/me/devices/{device_id}")

    assert (theirs.status_code, mine.status_code, twice.status_code) == (404, 204, 404)
    assert await _active_owners(PHONE["push_token"]) == []


async def test_rechaza_una_plataforma_que_no_es_movil(client: AsyncClient) -> None:
    response = await client.post("/v1/me/devices", json={**PHONE, "platform": "web"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
