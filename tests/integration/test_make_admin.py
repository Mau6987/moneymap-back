"""El script que nombra al administrador (MM-189): crea la cuenta o le pone la contraseña."""

from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.scripts.make_admin import AdminError, make_admin
from tests.integration.conftest import TEST_EMAIL_DOMAIN, VALID_PASSWORD


@pytest.fixture
async def previous_admin(owner_connection: AsyncConnection) -> AsyncIterator[None]:
    """Al terminar, vuelve el administrador que había antes de la prueba."""
    previous = (await owner_connection.execute(text("SELECT id FROM iam.users WHERE is_admin"))).scalar_one_or_none()
    await owner_connection.commit()
    yield
    await owner_connection.execute(text("UPDATE iam.users SET is_admin = false WHERE is_admin"))
    if previous is not None:
        await owner_connection.execute(text("UPDATE iam.users SET is_admin = true WHERE id = :id"), {"id": previous})
    await owner_connection.commit()


async def _login(api: AsyncClient, email: str, password: str) -> int:
    response = await api.post("/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


@pytest.mark.usefixtures("previous_admin")
async def test_crea_la_cuenta_y_entra_como_admin(
    api: AsyncClient, owner_connection: AsyncConnection, cleanup_users: Callable[[UUID], None]
) -> None:
    email = f"admin.{uuid4().hex}@{TEST_EMAIL_DOMAIN}"

    result = await make_admin(owner_connection, email, VALID_PASSWORD, "Ana")
    cleanup_users(result.id)

    assert result.created
    assert await _login(api, email, VALID_PASSWORD) == 200
    admins = (await owner_connection.execute(text("SELECT id FROM iam.users WHERE is_admin"))).scalars().all()
    await owner_connection.commit()
    assert admins == [result.id]


@pytest.mark.usefixtures("previous_admin")
async def test_a_una_cuenta_que_existe_le_cambia_la_contrasena_y_le_saca_el_rol_al_anterior(
    api: AsyncClient, owner_connection: AsyncConnection, cleanup_users: Callable[[UUID], None]
) -> None:
    first = await make_admin(owner_connection, f"a.{uuid4().hex}@{TEST_EMAIL_DOMAIN}", VALID_PASSWORD, "Ana")
    cleanup_users(first.id)
    email = f"b.{uuid4().hex}@{TEST_EMAIL_DOMAIN}"
    second = await make_admin(owner_connection, email, VALID_PASSWORD, "Luis")
    cleanup_users(second.id)

    again = await make_admin(owner_connection, email, "otra-clave-456", "Luis")

    assert again == (second.id, False)
    assert await _login(api, email, VALID_PASSWORD) == 401
    assert await _login(api, email, "otra-clave-456") == 200
    admins = (await owner_connection.execute(text("SELECT id FROM iam.users WHERE is_admin"))).scalars().all()
    await owner_connection.commit()
    assert admins == [second.id]


async def test_rechaza_una_contrasena_corta_sin_tocar_la_base(owner_connection: AsyncConnection) -> None:
    with pytest.raises(AdminError):
        await make_admin(owner_connection, f"c.{uuid4().hex}@{TEST_EMAIL_DOMAIN}", "corta", "Ana")
