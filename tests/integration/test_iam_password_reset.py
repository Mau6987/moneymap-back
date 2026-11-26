"""El restablecimiento de la contraseña (spec 008).

El correo se intercepta: se prueba **lo que la API quiso mandar**, sin salir a la
red (engineering §2.6). Los códigos de verdad salen con `secrets`, así que la
prueba no los inventa: los lee de lo que se mandó.
"""

from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import app
from app.modules.iam.deps import get_email_sender
from tests.integration.conftest import CURRENT_TERMS_VERSION, VALID_PASSWORD, RegisterBody

RESET_URL = "/v1/auth/password-reset"
CONFIRM_URL = "/v1/auth/password-reset/confirm"
VERIFY_URL = "/v1/auth/password-reset/verify"
NEW_PASSWORD = "clave-nueva-456"  # noqa: S105 — la contraseña de las pruebas, no un secreto


class RecordingEmailSender:
    """Captura lo que la API quiso mandar, en vez de mandarlo."""

    def __init__(self) -> None:
        self.links: list[str] = []
        self.codes: list[tuple[str, str]] = []
        self.google_notices: list[str] = []

    async def send_verification_link(self, email: str, link: str, expires_in_minutes: int) -> None:
        self.links.append(link)

    async def send_password_reset_code(self, email: str, code: str, expires_in_minutes: int) -> None:
        self.codes.append((email, code))

    async def send_google_account_notice(self, email: str) -> None:
        self.google_notices.append(email)

    @property
    def last_code(self) -> str:
        return self.codes[-1][1]


@pytest.fixture
def mailbox() -> Iterator[RecordingEmailSender]:
    sender = RecordingEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


async def _register(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    email: str,
) -> dict[str, object]:
    response = await api.post("/v1/auth/register", json=await register_body(email=email))
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    cleanup_users(UUID(str(body["profile"]["id"])))  # type: ignore[index]
    return body


async def test_pide_el_codigo_y_seis_digitos_llegan_al_correo(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.codigo@example.com"
    await _register(api, register_body, cleanup_users, email)

    response = await api.post(RESET_URL, json={"email": email})

    assert response.status_code == 202
    assert mailbox.codes and mailbox.codes[-1][0] == email
    assert len(mailbox.last_code) == 6 and mailbox.last_code.isdigit()


async def test_un_correo_sin_cuenta_responde_lo_mismo_y_no_manda_nada(
    api: AsyncClient,
    mailbox: RecordingEmailSender,
) -> None:
    """Es lo único que impide averiguar quién tiene cuenta (RF-2, RF-12)."""
    response = await api.post(RESET_URL, json={"email": "nadie@example.com"})

    assert response.status_code == 202
    assert response.content == b""  # sin cuerpo: no hay nada que contar
    assert mailbox.codes == [] and mailbox.google_notices == []


async def test_cambia_la_contrasena_y_cierra_todas_las_sesiones(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
    owner_connection: AsyncConnection,
) -> None:
    email = "ana.cambia@example.com"
    registered = await _register(api, register_body, cleanup_users, email)
    refresh_token = str(registered["refresh_token"])
    assert (await api.post("/v1/auth/refresh", json={"refresh_token": refresh_token})).status_code == 200

    await api.post(RESET_URL, json={"email": email})
    response = await api.post(
        CONFIRM_URL,
        json={"email": email, "code": mailbox.last_code, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    # Entra con la nueva y no con la vieja.
    assert (await api.post("/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})).status_code == 200
    assert (await api.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})).status_code == 401
    # Y todas las sesiones quedaron cerradas: el refresh que servía ya no sirve.
    assert (await api.post("/v1/auth/refresh", json={"refresh_token": refresh_token})).status_code == 401

    logged = (
        await owner_connection.execute(text("SELECT count(*) FROM ops.logs WHERE event_code = 'auth.password.reset'"))
    ).scalar_one()
    assert logged >= 1


async def test_el_codigo_sirve_una_sola_vez(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.unavez@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})
    code = mailbox.last_code

    first = await api.post(CONFIRM_URL, json={"email": email, "code": code, "new_password": NEW_PASSWORD})
    second = await api.post(CONFIRM_URL, json={"email": email, "code": code, "new_password": NEW_PASSWORD})

    assert first.status_code == 204
    assert second.status_code == 401
    assert second.json()["code"] == "invalid_reset_code"


async def test_un_codigo_equivocado_es_401_y_no_dice_mas(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.mal@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    wrong = await api.post(CONFIRM_URL, json={"email": email, "code": "000000", "new_password": NEW_PASSWORD})
    unknown = await api.post(
        CONFIRM_URL, json={"email": "nadie@example.com", "code": "000000", "new_password": NEW_PASSWORD}
    )

    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_reset_code"
    # El mismo detalle para un correo que existe y para uno que no (RF-12).
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert (await api.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})).status_code == 200


async def test_un_codigo_vencido_es_401(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
    owner_connection: AsyncConnection,
) -> None:
    email = "ana.vencido@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})
    await owner_connection.execute(
        text(
            "UPDATE iam.verification_tokens SET expires_at = now() - interval '1 minute'"
            " WHERE purpose = 'password_reset'"
        )
    )
    await owner_connection.commit()

    response = await api.post(
        CONFIRM_URL, json={"email": email, "code": mailbox.last_code, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_reset_code"


async def test_el_codigo_nuevo_reemplaza_al_anterior(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.dos.codigos@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})
    primero = mailbox.last_code
    await api.post(RESET_URL, json={"email": email})
    segundo = mailbox.last_code

    viejo = await api.post(CONFIRM_URL, json={"email": email, "code": primero, "new_password": NEW_PASSWORD})
    nuevo = await api.post(CONFIRM_URL, json={"email": email, "code": segundo, "new_password": NEW_PASSWORD})

    assert primero != segundo
    assert viejo.status_code == 401
    assert nuevo.status_code == 204


async def test_la_contrasena_nueva_tiene_que_cumplir_la_politica(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.corta@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    response = await api.post(CONFIRM_URL, json={"email": email, "code": mailbox.last_code, "new_password": "corta"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert (await api.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})).status_code == 200


async def test_una_cuenta_solo_de_google_avisa_en_vez_de_mandar_codigo(
    api: AsyncClient,
    mailbox: RecordingEmailSender,
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    email = "solo.google@example.com"
    user_id = (
        await owner_connection.execute(
            text(
                "INSERT INTO iam.users (email, first_name, last_name, display_name, terms_version,"
                " email_verified_at) VALUES (:email, 'Ana', 'Quispe', 'Ana', :terms, now()) RETURNING id"
            ),
            {"email": email, "terms": CURRENT_TERMS_VERSION},
        )
    ).scalar_one()
    await owner_connection.execute(
        text(
            "INSERT INTO iam.auth_identities (user_id, provider, provider_subject)"
            " VALUES (:user_id, 'google', 'google-sub-solo')"
        ),
        {"user_id": user_id},
    )
    await owner_connection.commit()
    cleanup_users(user_id)

    response = await api.post(RESET_URL, json={"email": email})

    assert response.status_code == 202
    assert mailbox.codes == []
    assert mailbox.google_notices == [email]


async def test_una_cuenta_suspendida_no_recibe_nada(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
    owner_connection: AsyncConnection,
) -> None:
    email = "ana.suspendida@example.com"
    await _register(api, register_body, cleanup_users, email)
    await owner_connection.execute(
        text("UPDATE iam.users SET status = 'suspended' WHERE email = :email"), {"email": email}
    )
    await owner_connection.commit()

    response = await api.post(RESET_URL, json={"email": email})

    assert response.status_code == 202
    assert mailbox.codes == [] and mailbox.google_notices == []


async def test_el_sexto_intento_se_corta(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.limite@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    intentos = [
        await api.post(CONFIRM_URL, json={"email": email, "code": "000000", "new_password": NEW_PASSWORD})
        for _ in range(6)
    ]

    assert [response.status_code for response in intentos[:5]] == [401] * 5
    assert intentos[5].status_code == 429
    assert intentos[5].json()["code"] == "too_many_requests"


async def test_verify_acepta_el_codigo_sin_gastarlo(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    """RF-15: la app pregunta el código antes de pedir la contraseña nueva."""
    email = "ana.verifica@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    response = await api.post(VERIFY_URL, json={"email": email, "code": mailbox.last_code})

    assert response.status_code == 204
    # No cambió nada: la contraseña vieja sigue sirviendo...
    assert (await api.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})).status_code == 200
    # ...y el mismo código todavía cambia la contraseña.
    confirmed = await api.post(
        CONFIRM_URL, json={"email": email, "code": mailbox.last_code, "new_password": NEW_PASSWORD}
    )
    assert confirmed.status_code == 204


async def test_verify_rechaza_un_codigo_equivocado_igual_que_un_correo_sin_cuenta(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    email = "ana.verifica.mal@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    wrong = await api.post(VERIFY_URL, json={"email": email, "code": "000000"})
    unknown = await api.post(VERIFY_URL, json={"email": "nadie@example.com", "code": "000000"})

    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_reset_code"
    # No dice si el correo existe (RF-12).
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert unknown.status_code == 401


async def test_verify_rechaza_un_codigo_vencido(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
    owner_connection: AsyncConnection,
) -> None:
    email = "ana.verifica.vencido@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})
    await owner_connection.execute(
        text(
            "UPDATE iam.verification_tokens SET expires_at = now() - interval '1 minute'"
            " WHERE purpose = 'password_reset'"
        )
    )
    await owner_connection.commit()

    response = await api.post(VERIFY_URL, json={"email": email, "code": mailbox.last_code})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_reset_code"


async def test_verify_pide_seis_digitos(api: AsyncClient) -> None:
    response = await api.post(VERIFY_URL, json={"email": "ana@example.com", "code": "12a"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_verify_y_confirm_comparten_los_cinco_intentos(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
    mailbox: RecordingEmailSender,
) -> None:
    """RF-9: verify no abre una puerta para adivinar el código."""
    email = "ana.verifica.limite@example.com"
    await _register(api, register_body, cleanup_users, email)
    await api.post(RESET_URL, json={"email": email})

    for _ in range(5):
        assert (await api.post(VERIFY_URL, json={"email": email, "code": "000000"})).status_code == 401
    sexto = await api.post(CONFIRM_URL, json={"email": email, "code": mailbox.last_code, "new_password": NEW_PASSWORD})

    assert sexto.status_code == 429
    assert sexto.json()["code"] == "too_many_requests"
