"""Corregir el perfil propio contra PostgreSQL 16 (spec 001, RF-10 a RF-12)."""

import pytest
from httpx import AsyncClient


async def test_corrige_solo_lo_enviado_y_devuelve_lo_guardado_rf10(client: AsyncClient) -> None:
    before = (await client.get("/v1/me")).json()

    response = await client.patch(
        "/v1/me",
        json={
            "last_name": "  Mamani   Quispe ",
            "country_code": "bo",
            "city": " La Paz ",
            "occupation": "self_employed",
            "timezone": "America/Lima",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        **before,
        "last_name": "Mamani Quispe",
        "country_code": "BO",
        "city": "La Paz",
        "occupation": "self_employed",
        "timezone": "America/Lima",
    }
    assert (await client.get("/v1/me")).json() == response.json()


async def test_null_borra_los_datos_opcionales_rf10(client: AsyncClient) -> None:
    await client.patch("/v1/me", json={"city": "La Paz", "occupation": "student"})

    response = await client.patch("/v1/me", json={"city": None, "occupation": None})

    assert (response.json()["city"], response.json()["occupation"]) == (None, None)


@pytest.mark.parametrize("display_name", ["", "   ", None])
async def test_el_nombre_visible_vacio_vuelve_al_nombre_rf11(client: AsyncClient, display_name: str | None) -> None:
    await client.patch("/v1/me", json={"display_name": "Anita"})

    response = await client.patch("/v1/me", json={"first_name": "Ana María", "display_name": display_name})

    assert response.status_code == 200
    assert response.json()["display_name"] == "Ana María"


@pytest.mark.parametrize(
    "payload",
    [
        {"occupation": "astronauta"},
        {"country_code": "XX"},
        {"first_name": "   "},
        {"first_name": None},
        {"timezone": "Marte/Base"},
        {"locale": "español"},
    ],
    ids=["ocupacion", "pais", "nombre_vacio", "nombre_null", "zona", "locale"],
)
async def test_rechaza_lo_que_no_sirve_y_no_cambia_nada_rf12(client: AsyncClient, payload: dict) -> None:
    before = (await client.get("/v1/me")).json()

    response = await client.patch("/v1/me", json={**payload, "city": "Cochabamba"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert (await client.get("/v1/me")).json() == before


async def test_sin_token_responde_401(api: AsyncClient) -> None:
    response = await api.patch("/v1/me", json={"city": "La Paz"})

    assert response.status_code == 401
