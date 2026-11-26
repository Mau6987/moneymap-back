"""Borrar la cuenta con 30 días de gracia (spec 001).

RF cubiertos: RF-28 y RF-30. El job que borra a los 30 días (RF-29) está en
`test_workers_account_deletion.py`.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core import clock
from app.core.db import SessionLocal
from app.main import app
from app.modules.iam.deps import get_identity_provider, get_identity_providers
from app.modules.iam.domain.models import SocialIdentity
from tests.integration.conftest import VALID_PASSWORD, RegisterBody

GOOGLE_SUBJECT = "google-sub-borrado"


class Registered:
    """Una persona registrada con contraseña, con sus dos tokens."""

    def __init__(self, body: dict[str, object], email: str) -> None:
        profile = body["profile"]
        assert isinstance(profile, dict)
        self.id = UUID(profile["id"])
        self.email = email
        self.refresh_token = str(body["refresh_token"])
        self.headers = {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture
async def person(api: AsyncClient, register_body: RegisterBody, cleanup_users: Callable[[UUID], None]) -> Registered:
    body = await register_body()
    response = await api.post("/v1/auth/register", json=body)
    assert response.status_code == 201
    registered = Registered(response.json(), response.json()["profile"]["email"])
    cleanup_users(registered.id)
    return registered


class FakeGoogle:
    def __init__(self, subject: str, email: str) -> None:
        self.identity = SocialIdentity(
            provider="google", subject=subject, email=email, first_name="Ana", last_name="Quispe"
        )

    async def verify(self, id_token: str) -> SocialIdentity:
        return self.identity


@pytest.fixture
def google() -> Iterator[Callable[[str, str], None]]:
    """El proveedor de mentira, para la ruta del ingreso y para la del borrado."""

    def use(subject: str, email: str) -> None:
        fake = FakeGoogle(subject, email)
        app.dependency_overrides[get_identity_provider] = lambda provider="google": fake
        app.dependency_overrides[get_identity_providers] = lambda: lambda provider: fake

    yield use

    app.dependency_overrides.pop(get_identity_provider, None)
    app.dependency_overrides.pop(get_identity_providers, None)


async def _account_state(user_id: UUID) -> tuple[str, object]:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT status, deletion_requested_at FROM iam.users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        ).one()
    return row[0], row[1]


async def _link_google(user_id: UUID) -> None:
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO iam.auth_identities (user_id, provider, provider_subject)"
                " VALUES (:user_id, 'google', :subject)"
            ),
            {"user_id": user_id, "subject": GOOGLE_SUBJECT},
        )


async def test_con_la_contrasena_la_deja_para_borrar_en_30_dias_rf28(api: AsyncClient, person: Registered) -> None:
    before = clock.utc_now()

    response = await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD}, headers=person.headers)

    assert response.status_code == 202
    scheduled = response.json()["deletion_scheduled_at"]
    assert scheduled.startswith(str((before + timedelta(days=30)).date()))
    status, requested_at = await _account_state(person.id)
    assert status == "pending_deletion"
    assert requested_at is not None


async def test_cierra_todas_las_sesiones_rf28(api: AsyncClient, person: Registered) -> None:
    assert (
        await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD}, headers=person.headers)
    ).status_code == 202

    refresh = await api.post("/v1/auth/refresh", json={"refresh_token": person.refresh_token})

    assert refresh.status_code == 401


async def test_con_otra_contrasena_responde_403_y_no_toca_la_cuenta_rf28(api: AsyncClient, person: Registered) -> None:
    response = await api.post("/v1/me/deletion", json={"password": "otra-clave-999"}, headers=person.headers)

    assert response.status_code == 403
    assert response.json()["code"] == "reauthentication_failed"
    assert (await _account_state(person.id))[0] == "active"
    assert (await api.post("/v1/auth/refresh", json={"refresh_token": person.refresh_token})).status_code == 200


async def test_pide_una_sola_prueba_rf28(api: AsyncClient, person: Registered) -> None:
    both = await api.post(
        "/v1/me/deletion",
        json={"password": VALID_PASSWORD, "provider": "google", "id_token": "x"},
        headers=person.headers,
    )
    none = await api.post("/v1/me/deletion", json={}, headers=person.headers)
    half = await api.post("/v1/me/deletion", json={"provider": "google"}, headers=person.headers)

    assert [r.status_code for r in (both, none, half)] == [422, 422, 422]
    assert (await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD})).status_code == 401  # sin token


async def test_con_la_cuenta_de_google_vinculada_rf28(
    api: AsyncClient, person: Registered, google: Callable[[str, str], None]
) -> None:
    await _link_google(person.id)
    google(GOOGLE_SUBJECT, person.email)

    response = await api.post(
        "/v1/me/deletion", json={"provider": "google", "id_token": "token-fresco"}, headers=person.headers
    )

    assert response.status_code == 202
    assert (await _account_state(person.id))[0] == "pending_deletion"


async def test_una_cuenta_de_google_que_no_es_la_suya_responde_403_rf28(
    api: AsyncClient, person: Registered, google: Callable[[str, str], None]
) -> None:
    await _link_google(person.id)
    google("google-sub-de-otra-persona", person.email)

    response = await api.post(
        "/v1/me/deletion", json={"provider": "google", "id_token": "token-ajeno"}, headers=person.headers
    )

    assert response.status_code == 403
    assert (await _account_state(person.id))[0] == "active"


async def test_entrar_con_la_contrasena_cancela_el_borrado_rf30(api: AsyncClient, person: Registered) -> None:
    assert (
        await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD}, headers=person.headers)
    ).status_code == 202

    login = await api.post("/v1/auth/login", json={"email": person.email, "password": VALID_PASSWORD})

    assert login.status_code == 200
    assert await _account_state(person.id) == ("active", None)


async def test_entrar_con_google_cancela_el_borrado_rf30(
    api: AsyncClient, person: Registered, google: Callable[[str, str], None]
) -> None:
    await _link_google(person.id)
    google(GOOGLE_SUBJECT, person.email)
    assert (
        await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD}, headers=person.headers)
    ).status_code == 202

    signed_in = await api.post("/v1/auth/oauth/google", json={"id_token": "token-fresco"})

    assert signed_in.status_code == 200
    assert "access_token" in signed_in.json()
    assert await _account_state(person.id) == ("active", None)


async def test_el_correo_sigue_tomado_mientras_espera_rf28(api: AsyncClient, person: Registered) -> None:
    assert (
        await api.post("/v1/me/deletion", json={"password": VALID_PASSWORD}, headers=person.headers)
    ).status_code == 202

    again = await api.post("/v1/auth/email-verifications", json={"email": person.email})

    assert again.status_code == 409
    assert again.json()["code"] == "email_taken"
