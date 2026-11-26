"""Registro, sesión y perfil contra PostgreSQL 16 (spec 001).

RF cubiertos: RF-1 a RF-5, RF-9, RF-17 a RF-20 y RF-27.
"""

from collections.abc import Callable
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import user_session
from app.modules.iam import router as iam_router
from app.modules.iam.router import REGISTER_WINDOW_SECONDS
from tests.integration.conftest import CURRENT_TERMS_VERSION, VALID_PASSWORD, RegisterBody


async def test_registra_a_una_persona_mayor_y_le_da_tokens_rf1(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    response = await api.post(
        "/v1/auth/register",
        json=await register_body(email="Ana.Nueva@Example.com", first_name="  María   José  "),
    )

    assert response.status_code == 201
    body = response.json()
    cleanup_users(UUID(body["profile"]["id"]))

    assert body["token_type"] == "bearer"  # noqa: S105 — el tipo del token, no un secreto
    assert body["expires_in"] == 900  # el token de acceso corto de la spec
    assert body["access_token"] and body["refresh_token"]

    profile = body["profile"]
    assert profile["email"] == "ana.nueva@example.com"  # se normaliza
    assert profile["display_name"] == "María José"  # los espacios de sobra se van
    assert profile["locale"] == "es-BO"
    assert profile["timezone"] == "America/La_Paz"

    # RF-1: el registro también crea sus preferencias por defecto.
    async with user_session(UUID(profile["id"])) as session:
        preferences = (
            await session.execute(
                text("SELECT theme, hide_amounts, week_starts_on FROM iam.user_preferences WHERE user_id = :user_id"),
                {"user_id": UUID(profile["id"])},
            )
        ).one()
    assert preferences == ("system", False, 1)


async def test_rechaza_el_nombre_vacio_o_faltante_diciendo_el_campo_rf3(
    api: AsyncClient,
    register_body: RegisterBody,
) -> None:
    blank = await api.post("/v1/auth/register", json=await register_body(first_name="   "))
    assert blank.status_code == 422
    assert blank.json()["code"] == "validation_error"
    assert blank.json()["errors"][0]["field"] == "first_name"

    incomplete = {key: value for key, value in (await register_body()).items() if key != "last_name"}
    missing = await api.post("/v1/auth/register", json=incomplete)
    assert missing.status_code == 422
    assert missing.json()["errors"][0]["field"] == "last_name"


async def test_rechaza_el_correo_repetido_sin_distinguir_mayusculas_rf4(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    first = await api.post("/v1/auth/register", json=await register_body(email="ana.repetida@example.com"))
    assert first.status_code == 201
    cleanup_users(UUID(first.json()["profile"]["id"]))

    second = await api.post("/v1/auth/register", json=await register_body(email="  ANA.Repetida@Example.COM  "))

    assert second.status_code == 409
    assert second.json()["code"] == "email_taken"


async def test_rechaza_los_terminos_que_no_son_los_vigentes_rf5(
    api: AsyncClient,
    register_body: RegisterBody,
) -> None:
    response = await api.post("/v1/auth/register", json=await register_body(terms_version="2020-01"))

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "terms_outdated"
    assert CURRENT_TERMS_VERSION in body["detail"]


async def test_inicia_sesion_y_no_revela_si_el_correo_existe_rf20(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body(email="ana.login@example.com"))
    cleanup_users(UUID(registered.json()["profile"]["id"]))

    logged_in = await api.post("/v1/auth/login", json={"email": "ANA.Login@Example.com", "password": VALID_PASSWORD})
    assert logged_in.status_code == 200
    assert logged_in.json()["access_token"]

    wrong_password = await api.post(
        "/v1/auth/login", json={"email": "ana.login@example.com", "password": "otra-clave-larga"}
    )
    unknown_email = await api.post("/v1/auth/login", json={"email": "nadie@example.com", "password": VALID_PASSWORD})
    assert (wrong_password.status_code, wrong_password.json()["code"]) == (401, "invalid_credentials")
    assert unknown_email.status_code == 401
    assert unknown_email.json()["detail"] == wrong_password.json()["detail"]


async def test_no_deja_entrar_si_el_correo_no_esta_verificado_rf27(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    """MM-88: la cuenta existe y la contraseña es buena, pero el correo no se confirmó."""
    email = "ana.sin-verificar@example.com"
    registered = await api.post("/v1/auth/register", json=await register_body(email=email))
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    await owner_connection.execute(
        text("UPDATE iam.users SET email_verified_at = NULL WHERE email = :email"), {"email": email}
    )
    await owner_connection.commit()

    response = await api.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})

    assert response.status_code == 409
    assert response.json()["code"] == "email_not_verified"
    assert "access_token" not in response.json()


async def test_la_contrasena_mala_no_delata_que_el_correo_no_esta_verificado_rf27(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    """RF-27: primero la contraseña y después la verificación, para no delatar la cuenta."""
    email = "ana.sin-verificar.mal@example.com"
    registered = await api.post("/v1/auth/register", json=await register_body(email=email))
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    await owner_connection.execute(
        text("UPDATE iam.users SET email_verified_at = NULL WHERE email = :email"), {"email": email}
    )
    await owner_connection.commit()

    response = await api.post("/v1/auth/login", json={"email": email, "password": "otra-clave-larga"})

    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")


async def test_rota_el_refresh_token_rf17(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    first = registered.json()["refresh_token"]

    rotated = await api.post("/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first

    again = await api.post("/v1/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
    assert again.status_code == 200
    assert again.json()["refresh_token"] != rotated.json()["refresh_token"]


async def test_reusar_un_refresh_token_corta_la_cadena_y_deja_la_traza_rf18(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    user_id = UUID(registered.json()["profile"]["id"])
    cleanup_users(user_id)
    first = registered.json()["refresh_token"]
    second = (await api.post("/v1/auth/refresh", json={"refresh_token": first})).json()["refresh_token"]
    # El par nuevo ya se usó: el viejo no puede ser una respuesta perdida (BUG-053).
    rotated = (await api.post("/v1/auth/refresh", json={"refresh_token": second})).json()["refresh_token"]

    reused = await api.post("/v1/auth/refresh", json={"refresh_token": first})

    assert reused.status_code == 401
    assert reused.json()["code"] == "refresh_token_reused"
    # La cadena queda cortada: el token que había quedado vigente tampoco sirve.
    dead = await api.post("/v1/auth/refresh", json={"refresh_token": rotated})
    assert dead.status_code == 401

    logged = (
        await owner_connection.execute(
            text("SELECT count(*) FROM ops.logs WHERE event_code = 'auth.refresh.reused' AND user_id = :user_id"),
            {"user_id": user_id},
        )
    ).scalar_one()
    assert logged >= 1
    category = (
        await owner_connection.execute(
            text(
                "SELECT category FROM ops.logs WHERE event_code = 'auth.refresh.reused' AND user_id = :user_id LIMIT 1"
            ),
            {"user_id": user_id},
        )
    ).scalar_one()
    assert category == "security"


async def test_una_respuesta_de_refresh_perdida_no_corta_la_sesion_bug053(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    first = registered.json()["refresh_token"]
    lost = await api.post("/v1/auth/refresh", json={"refresh_token": first})  # la respuesta no llega a la app
    assert lost.status_code == 200

    retry = await api.post("/v1/auth/refresh", json={"refresh_token": first})

    assert retry.status_code == 200, retry.text
    # El par perdido ya no sirve; el del reintento, sí.
    after = await api.post("/v1/auth/refresh", json={"refresh_token": retry.json()["refresh_token"]})
    assert after.status_code == 200


async def test_pasado_el_margen_el_token_viejo_es_reuso_bug053(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    user_id = UUID(registered.json()["profile"]["id"])
    cleanup_users(user_id)
    first = registered.json()["refresh_token"]
    assert (await api.post("/v1/auth/refresh", json={"refresh_token": first})).status_code == 200
    await owner_connection.execute(
        text(
            "UPDATE iam.sessions SET revoked_at = revoked_at - interval '2 minutes' WHERE user_id = :user_id"
            " AND revoked_at IS NOT NULL"
        ),
        {"user_id": user_id},
    )
    await owner_connection.commit()

    reused = await api.post("/v1/auth/refresh", json={"refresh_token": first})

    assert (reused.status_code, reused.json()["code"]) == (401, "refresh_token_reused")


async def test_devuelve_el_perfil_con_el_token_rf9(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    body = registered.json()
    cleanup_users(UUID(body["profile"]["id"]))

    response = await api.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})

    assert response.status_code == 200
    assert response.json() == body["profile"]


async def test_sin_token_valido_no_hay_perfil_rf19(api: AsyncClient) -> None:
    without = await api.get("/v1/me")
    assert without.status_code == 401
    assert without.json()["code"] == "unauthorized"
    assert without.headers["www-authenticate"] == "Bearer"

    invalid = await api.get("/v1/me", headers={"Authorization": "Bearer esto-no-es-un-token"})
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "unauthorized"


async def test_cada_token_devuelve_su_propio_perfil_rf19(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    first = await api.post("/v1/auth/register", json=await register_body(email="ana.uno@example.com"))
    second = await api.post("/v1/auth/register", json=await register_body(email="beto.dos@example.com"))
    cleanup_users(UUID(first.json()["profile"]["id"]))
    cleanup_users(UUID(second.json()["profile"]["id"]))

    one = await api.get("/v1/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"})
    two = await api.get("/v1/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"})

    assert one.json()["email"] == "ana.uno@example.com"
    assert two.json()["email"] == "beto.dos@example.com"
    assert one.json()["id"] != two.json()["id"]


async def test_limita_los_registros_por_ip(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El límite real es 100: con 3 se prueba lo mismo sin registrar 100 personas.
    monkeypatch.setattr(iam_router, "REGISTER_LIMIT", 3)
    for _ in range(3):
        registered = await api.post("/v1/auth/register", json=await register_body())
        assert registered.status_code == 201
        cleanup_users(UUID(registered.json()["profile"]["id"]))

    blocked = await api.post("/v1/auth/register", json=await register_body())

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_requests"
    # El TTL ya corrió al menos un segundo desde que se abrió la ventana.
    assert 0 < int(blocked.headers["retry-after"]) <= REGISTER_WINDOW_SECONDS


async def test_cerrar_sesion_revoca_el_refresh_de_ese_dispositivo_rf32(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    body = registered.json()
    other_device = await api.post(
        "/v1/auth/login",
        json={"email": body["profile"]["email"], "password": VALID_PASSWORD},
    )

    response = await api.post("/v1/auth/logout", json={"refresh_token": body["refresh_token"]})

    assert response.status_code == 204
    assert response.content == b""
    dead = await api.post("/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert dead.status_code == 401
    # Las sesiones de otros dispositivos siguen.
    alive = await api.post("/v1/auth/refresh", json={"refresh_token": other_device.json()["refresh_token"]})
    assert alive.status_code == 200


async def test_cerrar_sesion_corta_la_cadena_ya_rotada_rf32(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    rotated = (await api.post("/v1/auth/refresh", json={"refresh_token": registered.json()["refresh_token"]})).json()[
        "refresh_token"
    ]

    response = await api.post("/v1/auth/logout", json={"refresh_token": rotated})

    assert response.status_code == 204
    dead = await api.post("/v1/auth/refresh", json={"refresh_token": rotated})
    assert dead.status_code == 401


async def test_cerrar_sesion_con_un_token_que_no_sirve_responde_igual_rf32(api: AsyncClient) -> None:
    response = await api.post("/v1/auth/logout", json={"refresh_token": "no-existe"})

    assert response.status_code == 204


async def test_cerrar_sesion_sin_token_es_un_error_de_forma_rf32(api: AsyncClient) -> None:
    response = await api.post("/v1/auth/logout", json={"refresh_token": ""})

    assert (response.status_code, response.json()["code"]) == (422, "validation_error")
