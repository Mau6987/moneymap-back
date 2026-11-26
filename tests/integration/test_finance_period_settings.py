"""El periodo financiero y el ahorro planificado (spec 003, RF-7 a RF-9)."""

from httpx import AsyncClient

from tests.integration.conftest import RegisteredUser


async def test_guarda_el_periodo_y_el_ahorro_sin_tocar_la_moneda_rf7(client: AsyncClient) -> None:
    response = await client.put(
        "/v1/me/settings",
        json={"period_type": "semi_monthly", "period_start_day": 1, "planned_savings": "250.50"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "main_currency": "BOB",
        "period_type": "semi_monthly",
        "period_start_day": 1,
        "planned_savings": "250.50",
    }


async def test_un_ahorro_negativo_o_con_decimales_de_mas_es_invalid_amount_rf8(client: AsyncClient) -> None:
    negative = await client.put("/v1/me/settings", json={"planned_savings": "-1.00"})
    too_precise = await client.put("/v1/me/settings", json={"planned_savings": "10.555"})

    assert (negative.status_code, negative.json()["code"]) == (422, "invalid_amount")
    assert (too_precise.status_code, too_precise.json()["code"]) == (422, "invalid_amount")


async def test_un_periodo_o_un_dia_que_no_sirven_son_validation_error_rf9(client: AsyncClient) -> None:
    unknown = await client.put("/v1/me/settings", json={"period_type": "daily"})
    weekly_day = await client.put("/v1/me/settings", json={"period_type": "weekly", "period_start_day": 7})
    monthly_day = await client.put("/v1/me/settings", json={"period_type": "monthly", "period_start_day": 0})

    for response in (unknown, weekly_day, monthly_day):
        assert (response.status_code, response.json()["code"]) == (422, "validation_error")
    settings = (await client.put("/v1/me/settings", json={"planned_savings": "0"})).json()
    assert (settings["period_type"], settings["period_start_day"]) == ("monthly", 1)  # quedó como estaba


async def test_sin_moneda_principal_no_hay_donde_guardar_el_periodo_rf7(
    api: AsyncClient, registered_user: RegisteredUser
) -> None:
    response = await api.put("/v1/me/settings", json={"planned_savings": "100.00"}, headers=registered_user.headers)

    assert response.status_code == 422
    assert response.json()["code"] == "onboarding_incomplete"


async def test_get_devuelve_la_configuracion_guardada_rf1(client: AsyncClient) -> None:
    await client.put("/v1/me/settings", json={"period_type": "weekly", "period_start_day": 1})
    stored = await client.get("/v1/me/settings")

    assert stored.status_code == 200
    assert (stored.json()["period_type"], stored.json()["period_start_day"]) == ("weekly", 1)


async def test_get_sin_moneda_principal_es_onboarding_incomplete_rf1(
    api: AsyncClient, registered_user: RegisteredUser
) -> None:
    missing = await api.get("/v1/me/settings", headers=registered_user.headers)

    assert (missing.status_code, missing.json()["code"]) == (422, "onboarding_incomplete")


async def test_un_cuerpo_vacio_es_validation_error(client: AsyncClient) -> None:
    response = await client.put("/v1/me/settings", json={})

    assert (response.status_code, response.json()["code"]) == (422, "validation_error")
