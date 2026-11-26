"""Preferencias propias contra PostgreSQL 16 (spec 001, RF-15 y RF-16)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app

DEFAULTS = {"theme": "system", "accent_color": None, "hide_amounts": False, "week_starts_on": 1}


async def test_un_usuario_nuevo_tiene_las_preferencias_por_defecto_rf15(client: AsyncClient) -> None:
    response = await client.get("/v1/me/preferences")

    assert response.status_code == 200
    assert response.json() == DEFAULTS


async def test_cambia_solo_lo_enviado_rf15(client: AsyncClient) -> None:
    response = await client.patch("/v1/me/preferences", json={"theme": "dark", "accent_color": "#7C3AED"})
    hidden = await client.patch("/v1/me/preferences", json={"hide_amounts": True, "week_starts_on": 0})

    assert response.json() == {**DEFAULTS, "theme": "dark", "accent_color": "#7C3AED"}
    assert hidden.json() == {
        **DEFAULTS,
        "theme": "dark",
        "accent_color": "#7C3AED",
        "hide_amounts": True,
        "week_starts_on": 0,
    }
    assert (await client.get("/v1/me/preferences")).json() == hidden.json()


async def test_el_color_en_null_vuelve_al_de_la_marca_rf15(client: AsyncClient) -> None:
    await client.patch("/v1/me/preferences", json={"accent_color": "#7C3AED"})

    response = await client.patch("/v1/me/preferences", json={"accent_color": None})

    assert response.json()["accent_color"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"theme": "sepia"},
        {"accent_color": "violeta"},
        {"accent_color": "#7C3AE"},
        {"week_starts_on": 7},
        {"week_starts_on": -1},
        {"theme": None},
        {"hide_amounts": None},
    ],
    ids=["tema", "color_nombre", "color_corto", "dia_7", "dia_negativo", "tema_null", "privado_null"],
)
async def test_rechaza_lo_que_no_sirve_y_no_cambia_nada_rf16(client: AsyncClient, payload: dict) -> None:
    response = await client.patch("/v1/me/preferences", json={"hide_amounts": True, **payload})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert (await client.get("/v1/me/preferences")).json() == DEFAULTS


async def test_cada_usuario_ve_solo_las_suyas(
    client: AsyncClient, user_id: UUID, new_financial_user: Callable[[str], Awaitable[UUID]]
) -> None:
    await client.patch("/v1/me/preferences", json={"theme": "dark"})
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other_client:
        theirs = (await other_client.get("/v1/me/preferences")).json()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    assert theirs == DEFAULTS
