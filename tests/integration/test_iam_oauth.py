"""El ingreso con Google y Apple: vinculación, registro pendiente y completar (spec 001).

El verificador del proveedor se reemplaza por uno de mentira: acá no se llama a
Google ni a Apple. Lo que se prueba de verdad es el flujo —a quién deja entrar, a
quién vincula y a quién le pide los datos— y la verificación del token tiene sus
propias pruebas unitarias (`tests/unit/test_google_identity.py` y
`tests/unit/test_apple_identity.py`).
"""

from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import app
from app.modules.iam.deps import get_identity_provider
from app.modules.iam.domain.errors import InvalidProviderToken
from app.modules.iam.domain.models import SocialIdentity
from tests.integration.conftest import CURRENT_TERMS_VERSION, RegisterBody

OAUTH_URL = "/v1/auth/oauth/google"


class FakeGoogle:
    """Dice que es quien le pidamos; con el token "malo" lo rechaza como Google."""

    def __init__(self, identity: SocialIdentity) -> None:
        self.identity = identity
        self.questions: list[str] = []

    async def verify(self, id_token: str) -> SocialIdentity:
        self.questions.append(id_token)
        if id_token.startswith("invalido"):
            raise InvalidProviderToken("El token de Google no es válido")
        return self.identity


@pytest.fixture
def google() -> Iterator[Callable[[SocialIdentity], FakeGoogle]]:
    """Instala el proveedor de mentira para la prueba."""
    holder: dict[str, FakeGoogle] = {}

    def use(identity: SocialIdentity) -> FakeGoogle:
        fake = FakeGoogle(identity)
        holder["fake"] = fake
        app.dependency_overrides[get_identity_provider] = lambda provider="google": holder["fake"]
        return fake

    yield use

    app.dependency_overrides.pop(get_identity_provider, None)


def identity_for(email: str, subject: str = "google-sub-1") -> SocialIdentity:
    return SocialIdentity(
        provider="google",
        subject=subject,
        email=email,
        first_name="Ana",
        last_name="Quispe",
    )


async def _register_with_password(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    email: str,
) -> UUID:
    response = await api.post("/v1/auth/register", json=await register_body(email=email))
    assert response.status_code == 201
    user_id = UUID(response.json()["profile"]["id"])
    cleanup_users(user_id)
    return user_id


async def _identities(connection: AsyncConnection, user_id: UUID) -> list[str]:
    rows = await connection.execute(
        text("SELECT provider FROM iam.auth_identities WHERE user_id = :user_id ORDER BY provider"),
        {"user_id": user_id},
    )
    return [row[0] for row in rows]


async def test_vincula_google_a_una_cuenta_que_ya_existe(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    google: Callable[[SocialIdentity], FakeGoogle],
    owner_connection: AsyncConnection,
) -> None:
    """Si el correo ya tiene cuenta, Google entra a esa cuenta y queda vinculada."""
    email = "ana.vinculada@example.com"
    user_id = await _register_with_password(api, register_body, cleanup_users, email)
    assert await _identities(owner_connection, user_id) == ["password"]

    google(identity_for(email))
    response = await api.post(OAUTH_URL, json={"id_token": "token-bueno"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert "registration_required" not in body
    # Quedó vinculada y no se creó otra cuenta.
    assert await _identities(owner_connection, user_id) == ["google", "password"]


async def test_la_segunda_vez_entra_por_la_identidad_vinculada(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    google: Callable[[SocialIdentity], FakeGoogle],
) -> None:
    email = "ana.repetida.google@example.com"
    await _register_with_password(api, register_body, cleanup_users, email)
    google(identity_for(email))
    assert (await api.post(OAUTH_URL, json={"id_token": "token-bueno"})).status_code == 200

    again = await api.post(OAUTH_URL, json={"id_token": "otro-token-bueno"})

    assert again.status_code == 200
    assert again.json()["access_token"]


async def test_sin_cuenta_pide_completar_el_registro_y_no_crea_nada(
    api: AsyncClient,
    google: Callable[[SocialIdentity], FakeGoogle],
    owner_connection: AsyncConnection,
) -> None:
    email = "nueva.con.google@example.com"
    google(identity_for(email))

    response = await api.post(OAUTH_URL, json={"id_token": "token-bueno"})

    assert response.status_code == 200
    body = response.json()
    assert body["registration_required"] is True
    assert body["registration_token"]
    assert (body["email"], body["first_name"], body["last_name"]) == (email, "Ana", "Quispe")
    # No se creó la cuenta todavía (RF-7): sin tokens y sin fila.
    assert "access_token" not in body
    users = (
        await owner_connection.execute(text("SELECT count(*) FROM iam.users WHERE email = :email"), {"email": email})
    ).scalar_one()
    assert users == 0


async def test_completa_el_registro_con_el_token_del_proveedor(
    api: AsyncClient,
    google: Callable[[SocialIdentity], FakeGoogle],
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    email = "completa.google@example.com"
    google(identity_for(email))
    started = (await api.post(OAUTH_URL, json={"id_token": "token-bueno"})).json()

    response = await api.post(
        "/v1/auth/oauth/complete",
        json={
            "registration_token": started["registration_token"],
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
        },
    )

    assert response.status_code == 201
    body = response.json()
    cleanup_users(UUID(body["profile"]["id"]))
    assert body["profile"]["email"] == email
    assert body["access_token"]
    # El correo lo verificó Google: la cuenta nace verificada y con su identidad.
    row = (
        await owner_connection.execute(
            text("SELECT email_verified_at IS NOT NULL FROM iam.users WHERE email = :email"),
            {"email": email},
        )
    ).scalar_one()
    assert row is True
    assert await _identities(owner_connection, UUID(body["profile"]["id"])) == ["google"]


async def test_completar_pide_el_correo_si_el_proveedor_no_lo_dio(
    api: AsyncClient,
    google: Callable[[SocialIdentity], FakeGoogle],
    cleanup_users: Callable[[UUID], None],
) -> None:
    sin_correo = SocialIdentity(provider="google", subject="google-sub-2", email=None)
    google(sin_correo)
    started = (await api.post(OAUTH_URL, json={"id_token": "token-bueno"})).json()
    assert started["email"] is None

    faltante = await api.post(
        "/v1/auth/oauth/complete",
        json={
            "registration_token": started["registration_token"],
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
        },
    )
    assert faltante.status_code == 422
    assert faltante.json()["code"] == "email_required"

    completo = await api.post(
        "/v1/auth/oauth/complete",
        json={
            "registration_token": started["registration_token"],
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
            "email": "puesta.a.mano@example.com",
        },
    )
    assert completo.status_code == 201
    cleanup_users(UUID(completo.json()["profile"]["id"]))
    assert completo.json()["profile"]["email"] == "puesta.a.mano@example.com"


async def test_un_registration_token_inventado_no_sirve(api: AsyncClient) -> None:
    response = await api.post(
        "/v1/auth/oauth/complete",
        json={
            "registration_token": "inventado",
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_registration_token"


async def test_un_token_de_google_que_no_sirve_es_401(
    api: AsyncClient,
    google: Callable[[SocialIdentity], FakeGoogle],
) -> None:
    google(identity_for("quien.sea@example.com"))

    response = await api.post(OAUTH_URL, json={"id_token": "invalido-1"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_provider_token"


async def test_un_proveedor_que_no_existe_no_se_atiende(api: AsyncClient) -> None:
    response = await api.post("/v1/auth/oauth/facebook", json={"id_token": "x"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_completar_con_el_correo_de_otra_cuenta_es_409(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    google: Callable[[SocialIdentity], FakeGoogle],
) -> None:
    """El correo repetido lo aplica la base, como en el registro normal (RF-4)."""
    email = "ya.existe@example.com"
    await _register_with_password(api, register_body, cleanup_users, email)
    google(identity_for("otro.correo@example.com"))
    started = (await api.post(OAUTH_URL, json={"id_token": "token-bueno"})).json()

    response = await api.post(
        "/v1/auth/oauth/complete",
        json={
            "registration_token": started["registration_token"],
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
            "email": email,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


async def test_apple_vincula_una_cuenta_que_ya_existe(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    google: Callable[[SocialIdentity], FakeGoogle],
    owner_connection: AsyncConnection,
) -> None:
    """RF-6: el mismo flujo con Apple; la identidad se guarda con provider 'apple'."""
    email = "ana.apple@example.com"
    user_id = await _register_with_password(api, register_body, cleanup_users, email)
    google(SocialIdentity(provider="apple", subject="001234.abcdef", email=email))

    response = await api.post("/v1/auth/oauth/apple", json={"id_token": "token-bueno"})

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert await _identities(owner_connection, user_id) == ["apple", "password"]


async def test_apple_sin_cuenta_pide_completar_el_registro(
    api: AsyncClient,
    google: Callable[[SocialIdentity], FakeGoogle],
) -> None:
    """RF-7: con Apple tampoco se crea nada hasta completar el registro."""
    email = "nueva.con.apple@example.com"
    google(SocialIdentity(provider="apple", subject="001234.nueva", email=email))

    response = await api.post("/v1/auth/oauth/apple", json={"id_token": "token-bueno"})

    assert response.status_code == 200
    body = response.json()
    assert body["registration_required"] is True
    assert body["email"] == email
    assert "access_token" not in body
