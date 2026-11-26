"""Sumar una moneda a Mis monedas sin crear una cuenta (spec 002).

RF cubierto: RF-28.
"""

import pytest
from httpx import AsyncClient

# Mis monedas respeta el límite del plan desde MM-186 (lo prueba test_billing_plans.py):
# acá se sube el del gratuito para probar RF-28 con más de una moneda.
pytestmark = pytest.mark.usefixtures("allow_more_currencies")


async def test_suma_una_moneda_a_mis_monedas_sin_crear_cuentas_rf28(client: AsyncClient) -> None:
    response = await client.put("/v1/me/currencies/USD")

    assert response.status_code == 200
    assert response.json()["code"] == "USD"
    assert response.json()["is_mine"] is True
    assert response.json()["is_main_currency"] is False
    mine = [currency["code"] for currency in (await client.get("/v1/currencies")).json() if currency["is_mine"]]
    assert mine == ["BOB", "USD"]
    assert (await client.get("/v1/accounts")).json() == []
    assert (await client.get("/v1/balances")).json() == []  # sin cuentas, no aparece en los totales


async def test_repetirlo_no_cambia_nada_rf28(client: AsyncClient) -> None:
    assert (await client.put("/v1/me/currencies/USD")).status_code == 200

    again = await client.put("/v1/me/currencies/USD")

    assert again.status_code == 200
    mine = [currency["code"] for currency in (await client.get("/v1/currencies")).json() if currency["is_mine"]]
    assert mine == ["BOB", "USD"]


async def test_una_moneda_que_no_esta_disponible_responde_422_rf28(client: AsyncClient) -> None:
    response = await client.put("/v1/me/currencies/XXX")

    assert response.status_code == 422
    assert response.json()["code"] == "currency_unavailable"


async def test_la_que_se_sumo_se_puede_quitar_rf19_rf28(client: AsyncClient) -> None:
    assert (await client.put("/v1/me/currencies/USD")).status_code == 200

    assert (await client.delete("/v1/me/currencies/USD")).status_code == 204
