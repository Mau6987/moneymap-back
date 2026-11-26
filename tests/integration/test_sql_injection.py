"""Que un texto con SQL siga siendo texto.

Todo el SQL va con `text()` y parámetros de enlace: ningún dato se concatena, ni
siquiera para un nombre de tabla o de columna. Ruff lo verifica con `S608`, que
marca cualquier consulta armada con f-strings o concatenación; estas pruebas lo
comprueban desde el borde HTTP, que es por donde entra el texto.
"""

from collections.abc import Callable
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import VALID_PASSWORD, RegisterBody

# Un nombre que, si se concatenara, cerraría la consulta y borraría una tabla.
SQL_IN_NAME = "Ana'); DROP TABLE iam.users; --"
SQL_IN_ACCOUNT = "Caja 'principal' ; SELECT 1"


async def test_un_nombre_con_sql_se_guarda_como_texto(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    response = await api.post("/v1/auth/register", json=await register_body(first_name=SQL_IN_NAME))

    assert response.status_code == 201
    cleanup_users(UUID(response.json()["profile"]["id"]))
    assert response.json()["profile"]["first_name"] == SQL_IN_NAME

    # La tabla sigue existiendo y guardó el texto tal cual.
    stored = (
        await owner_connection.execute(
            text("SELECT count(*) FROM iam.users WHERE first_name = :first_name"),
            {"first_name": SQL_IN_NAME},
        )
    ).scalar_one()
    assert stored == 1


async def test_un_correo_con_sql_no_autentica(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body(email="ana.inyeccion@example.com"))
    cleanup_users(UUID(registered.json()["profile"]["id"]))

    # El patrón del correo lo rechaza antes de llegar a la base.
    bypass = await api.post("/v1/auth/login", json={"email": "' OR '1'='1' --", "password": VALID_PASSWORD})
    assert bypass.status_code == 422

    quoted = await api.post(
        "/v1/auth/login",
        json={"email": "ana.inyeccion@example.com' OR '1'='1", "password": VALID_PASSWORD},
    )
    assert quoted.status_code == 422

    # Un SQL en la contraseña solo puede fallar la verificación: no hay forma de
    # que una comparación lo dé por buena.
    as_password = await api.post(
        "/v1/auth/login",
        json={"email": "ana.inyeccion@example.com", "password": "' OR '1'='1"},
    )
    assert as_password.status_code == 401
    assert as_password.json()["code"] == "invalid_credentials"


async def test_un_refresh_token_con_sql_no_sirve(api: AsyncClient) -> None:
    response = await api.post("/v1/auth/refresh", json={"refresh_token": "' OR 1=1 --"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_refresh_token"


async def test_el_nombre_de_una_cuenta_con_comillas_se_guarda_como_texto(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> None:
    registered = await api.post("/v1/auth/register", json=await register_body())
    cleanup_users(UUID(registered.json()["profile"]["id"]))
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    response = await api.post(
        "/v1/accounts",
        json={"name": SQL_IN_ACCOUNT, "type": "cash", "currency": "BOB", "opening_balance": "10.00"},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["name"] == SQL_IN_ACCOUNT
    assert response.json()["current_balance"] == "10.00"
