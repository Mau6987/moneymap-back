"""Moneda principal, selector de monedas y Mis monedas (spec 002).

RF cubiertos: RF-1, RF-2, RF-19 y RF-20.
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from tests.integration.conftest import RegisteredUser

CASH_BOB = {"name": "Caja Bs", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


async def _account_in(api: AsyncClient, user: RegisteredUser, currency: str) -> str:
    """Una cuenta en esa moneda. Al crearla o cambiarla, la moneda entra a Mis monedas."""
    created = await api.post("/v1/accounts", json=CASH_BOB, headers=user.headers)
    assert created.status_code == 201
    account_id: str = created.json()["id"]
    if currency != "BOB":
        changed = await api.patch(f"/v1/accounts/{account_id}", json={"currency": currency}, headers=user.headers)
        assert changed.status_code == 200
    return account_id


async def test_guarda_la_moneda_principal_y_siembra_las_categorias_rf1(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    response = await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)

    assert response.status_code == 200
    assert response.json() == {
        "main_currency": "BOB",
        "period_type": "monthly",
        "period_start_day": 1,
        "planned_savings": "0.00",
    }

    async with user_session(registered_user.id) as session:
        templates = (
            await session.execute(text("SELECT count(*) FROM catalog.category_templates WHERE is_active"))
        ).scalar_one()
        categories = (
            await session.execute(
                text("SELECT count(*) FROM finance.categories WHERE user_id = :user_id"),
                {"user_id": registered_user.id},
            )
        ).scalar_one()
        mine = (
            (
                await session.execute(
                    text("SELECT currency FROM finance.user_currencies WHERE user_id = :user_id"),
                    {"user_id": registered_user.id},
                )
            )
            .scalars()
            .all()
        )
    assert categories == templates  # las categorías iniciales, copiadas una vez
    assert list(mine) == ["BOB"]  # la principal entra a Mis monedas sola


async def test_el_paso_1_se_puede_repetir_sin_duplicar_nada_rf1(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    first = await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)
    again = await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)

    assert first.status_code == 200
    assert again.status_code == 200

    async with user_session(registered_user.id) as session:
        templates = (
            await session.execute(text("SELECT count(*) FROM catalog.category_templates WHERE is_active"))
        ).scalar_one()
        settings = (
            await session.execute(
                text("SELECT count(*) FROM finance.user_settings WHERE user_id = :user_id"),
                {"user_id": registered_user.id},
            )
        ).scalar_one()
        mine = (
            await session.execute(
                text("SELECT count(*) FROM finance.user_currencies WHERE user_id = :user_id"),
                {"user_id": registered_user.id},
            )
        ).scalar_one()
        categories = (
            await session.execute(
                text("SELECT count(*) FROM finance.categories WHERE user_id = :user_id"),
                {"user_id": registered_user.id},
            )
        ).scalar_one()
    assert (settings, mine, categories) == (1, 1, templates)


async def test_cambiar_la_moneda_principal_no_convierte_ningun_monto_rf1(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)
    account = await api.post("/v1/accounts", json=CASH_BOB, headers=registered_user.headers)
    assert account.status_code == 201

    changed = await api.put("/v1/me/settings", json={"main_currency": "USD"}, headers=registered_user.headers)

    assert changed.status_code == 200
    assert changed.json()["main_currency"] == "USD"
    # La cuenta sigue en BOB y con el mismo saldo: no hay conversión (constitución §2).
    balances = (await api.get("/v1/balances", headers=registered_user.headers)).json()
    assert len(balances) == 1
    assert (balances[0]["currency"], balances[0]["total"], balances[0]["is_main_currency"]) == ("BOB", "2500.00", False)


async def test_la_moneda_principal_tiene_que_existir_y_estar_activa_rf1(
    api: AsyncClient,
    registered_user: RegisteredUser,
    deactivate_currency: Callable[[str], Awaitable[None]],
) -> None:
    unknown = await api.put("/v1/me/settings", json={"main_currency": "XXX"}, headers=registered_user.headers)
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "currency_unavailable"

    await deactivate_currency("GBP")
    retired = await api.put("/v1/me/settings", json={"main_currency": "GBP"}, headers=registered_user.headers)
    assert retired.status_code == 422
    assert retired.json()["code"] == "currency_unavailable"


async def test_devuelve_mis_monedas_primero_y_despues_las_activas_rf2(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)

    response = await api.get("/v1/currencies", headers=registered_user.headers)

    assert response.status_code == 200
    rows = response.json()
    async with user_session(registered_user.id) as session:
        active = (await session.execute(text("SELECT count(*) FROM catalog.currencies WHERE is_active"))).scalar_one()
    assert len(rows) == active  # todas las activas, ninguna retirada

    first = rows[0]
    assert (first["code"], first["name"], first["symbol"], first["decimals"]) == ("BOB", "Boliviano", "Bs", 2)
    assert first["is_mine"] is True
    assert first["is_main_currency"] is True

    # Mis monedas primero: no puede haber una ajena antes que una propia.
    mine_flags = [row["is_mine"] for row in rows]
    assert mine_flags == sorted(mine_flags, reverse=True)


async def test_una_moneda_retirada_del_catalogo_rf20(
    api: AsyncClient,
    registered_user: RegisteredUser,
    deactivate_currency: Callable[[str], Awaitable[None]],
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)
    await _account_in(api, registered_user, "GBP")

    await deactivate_currency("GBP")
    await deactivate_currency("PEN")

    rows = (await api.get("/v1/currencies", headers=registered_user.headers)).json()
    mine = [row for row in rows if row["is_mine"]]
    codes = [row["code"] for row in rows]

    # La del usuario sigue saliendo, marcada como retirada...
    assert [row["code"] for row in mine] == ["BOB", "GBP"]
    assert [row for row in mine if row["code"] == "GBP"][0]["is_active"] is False
    # ...y la que no usa no se ofrece, así que no se puede crear una cuenta nueva.
    assert "PEN" not in codes
    rejected = await api.post("/v1/accounts", json={**CASH_BOB, "currency": "PEN"}, headers=registered_user.headers)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "currency_unavailable"


async def test_quita_una_moneda_de_mis_monedas_rf19(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)
    # EUR entra a Mis monedas sin cuentas de por medio, como cuando el usuario la agrega.
    async with user_session(registered_user.id) as session:
        await session.execute(
            text("INSERT INTO finance.user_currencies (user_id, currency) VALUES (:user_id, 'EUR')"),
            {"user_id": registered_user.id},
        )

    response = await api.delete("/v1/me/currencies/EUR", headers=registered_user.headers)

    assert response.status_code == 204
    rows = (await api.get("/v1/currencies", headers=registered_user.headers)).json()
    assert [row["code"] for row in rows if row["is_mine"]] == ["BOB"]


async def test_no_quita_la_moneda_principal_rf19(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)

    response = await api.delete("/v1/me/currencies/BOB", headers=registered_user.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "currency_in_use"


async def test_no_quita_una_moneda_con_cuentas_activas_rf19(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    await api.put("/v1/me/settings", json={"main_currency": "BOB"}, headers=registered_user.headers)
    await _account_in(api, registered_user, "USD")

    response = await api.delete("/v1/me/currencies/USD", headers=registered_user.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "currency_in_use"


async def test_una_moneda_que_no_es_mia_responde_404_rf19(
    api: AsyncClient,
    registered_user: RegisteredUser,
) -> None:
    response = await api.delete("/v1/me/currencies/EUR", headers=registered_user.headers)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
