"""Verificación del correo antes del registro, contra PostgreSQL 16 (spec 001).

RF cubiertos: RF-22 a RF-26. El correo no sale: un `EmailSender` de prueba guarda
los links, y el reloj se adelanta con `monkeypatch` para vencerlos.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import clock
from app.core.config import get_settings
from app.main import app
from app.modules.iam import router as iam_router
from app.modules.iam.deps import get_email_sender
from app.modules.iam.router import EMAIL_VERIFICATION_PER_EMAIL_LIMIT
from tests.integration.conftest import CURRENT_TERMS_VERSION, VALID_PASSWORD, RegisteredUser

START = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@dataclass
class SentLink:
    email: str
    url: str
    expires_in_minutes: int

    @property
    def path_and_query(self) -> str:
        parts = urlsplit(self.url)
        return f"{parts.path}?{parts.query}"

    @property
    def token(self) -> str:
        return parse_qs(urlsplit(self.url).query)["token"][0]


@dataclass
class FakeEmailSender:
    """Guarda los links en vez de enviarlos."""

    sent: list[SentLink] = field(default_factory=list)

    async def send_verification_link(self, email: str, link: str, expires_in_minutes: int) -> None:
        self.sent.append(SentLink(email, link, expires_in_minutes))


class Clock:
    """El reloj de la API, quieto hasta que la prueba lo adelanta."""

    def __init__(self) -> None:
        self.now = START

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(clock, "utc_now", lambda: fake.now)
    return fake


@pytest.fixture
def sender() -> Iterator[FakeEmailSender]:
    fake = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture
async def new_email(owner_connection: AsyncConnection) -> AsyncIterator[Callable[[], str]]:
    """Correos nuevos; sus verificaciones se borran al terminar."""
    used: list[str] = []

    def build() -> str:
        email = f"ana.{uuid4().hex[:12]}@example.com"
        used.append(email)
        return email

    yield build

    await owner_connection.execute(
        text("DELETE FROM iam.email_verifications WHERE email = ANY(:emails)"), {"emails": used}
    )
    await owner_connection.commit()


def _registration(verification_id: str) -> dict[str, object]:
    return {
        "verification_id": verification_id,
        "password": VALID_PASSWORD,
        "first_name": "Ana",
        "last_name": "Quispe",
        "terms_version": CURRENT_TERMS_VERSION,
    }


async def _start(api: AsyncClient, email: str) -> Response:
    return await api.post("/v1/auth/email-verifications", json={"email": email})


async def test_envia_un_link_que_vence_en_5_minutos_rf22(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    email = new_email()

    response = await _start(api, f"  {email.upper()} ")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email  # sin espacios y en minúsculas, como el registro
    assert body["status"] == "pending"
    assert datetime.fromisoformat(body["expires_at"]) == START + timedelta(minutes=5)
    assert datetime.fromisoformat(body["resend_available_at"]) == START + timedelta(minutes=1)

    assert len(sender.sent) == 1
    link = sender.sent[0]
    assert link.email == email
    assert link.expires_in_minutes == 5
    assert link.url.startswith(f"{get_settings().public_base_url}/v1/auth/verify-email?token=")


async def test_del_link_solo_se_guarda_el_hash_rf22(
    api: AsyncClient, sender: FakeEmailSender, new_email: Callable[[], str], owner_connection: AsyncConnection
) -> None:
    response = await _start(api, new_email())

    stored = (
        await owner_connection.execute(
            text("SELECT token_hash FROM iam.email_verifications WHERE id = :id"), {"id": response.json()["id"]}
        )
    ).scalar_one()
    assert sender.sent[0].token not in stored


async def test_un_correo_con_cuenta_responde_email_taken_y_no_envia_nada_rf22(
    api: AsyncClient,
    sender: FakeEmailSender,
    registered_user: RegisteredUser,
    owner_connection: AsyncConnection,
) -> None:
    email = (
        await owner_connection.execute(text("SELECT email FROM iam.users WHERE id = :id"), {"id": registered_user.id})
    ).scalar_one()

    response = await _start(api, email)

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "email_taken"
    assert "Ana" not in body["detail"]  # no dice nada de la cuenta
    assert sender.sent == []


async def test_el_link_verifica_el_correo_y_la_app_lo_ve_rf23_rf24(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    started = (await _start(api, new_email())).json()
    status_url = f"/v1/auth/email-verifications/{started['id']}"
    assert (await api.get(status_url)).json()["status"] == "pending"

    frozen_clock.advance(minutes=4)
    page = await api.get(sender.sent[0].path_and_query)

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Correo verificado" in page.text
    assert started["email"] in page.text
    assert (await api.get(status_url)).json()["status"] == "verified"

    # Abrirlo otra vez no es un error.
    again = await api.get(sender.sent[0].path_and_query)
    assert again.status_code == 200
    assert "Correo verificado" in again.text


async def test_un_link_vencido_no_verifica_rf24(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    started = (await _start(api, new_email())).json()

    frozen_clock.advance(minutes=5)
    page = await api.get(sender.sent[0].path_and_query)

    assert page.status_code == 410
    assert "El link expiró" in page.text
    status = await api.get(f"/v1/auth/email-verifications/{started['id']}")
    assert status.json()["status"] == "expired"


async def test_un_link_inventado_no_sirve_rf24(api: AsyncClient) -> None:
    page = await api.get("/v1/auth/verify-email?token=no-existe")

    assert page.status_code == 404
    assert "Este link no sirve" in page.text

    empty = await api.get("/v1/auth/verify-email")
    assert empty.status_code == 404


async def test_reenvia_despues_de_un_minuto_y_el_link_anterior_deja_de_servir_rf25(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    started = (await _start(api, new_email())).json()
    resend_url = f"/v1/auth/email-verifications/{started['id']}/resend"

    frozen_clock.advance(seconds=30)
    too_soon = await api.post(resend_url)
    assert too_soon.status_code == 429
    assert too_soon.json()["code"] == "too_many_requests"
    assert too_soon.headers["retry-after"] == "31"
    assert len(sender.sent) == 1

    frozen_clock.advance(seconds=31)
    resent = await api.post(resend_url)
    assert resent.status_code == 200
    body = resent.json()
    assert body["status"] == "pending"
    assert datetime.fromisoformat(body["expires_at"]) == frozen_clock.now + timedelta(minutes=5)
    assert len(sender.sent) == 2

    old_link = await api.get(sender.sent[0].path_and_query)
    assert old_link.status_code == 404
    new_link = await api.get(sender.sent[1].path_and_query)
    assert new_link.status_code == 200


async def test_reenviar_un_link_vencido_lo_revive_rf25(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    started = (await _start(api, new_email())).json()
    frozen_clock.advance(minutes=10)

    resent = await api.post(f"/v1/auth/email-verifications/{started['id']}/resend")

    assert resent.json()["status"] == "pending"
    assert (await api.get(sender.sent[1].path_and_query)).status_code == 200


async def test_registra_con_el_correo_verificado_una_sola_vez_rf26(
    api: AsyncClient,
    sender: FakeEmailSender,
    new_email: Callable[[], str],
    cleanup_users: Callable[[UUID], None],
    owner_connection: AsyncConnection,
) -> None:
    started = (await _start(api, new_email())).json()

    not_yet = await api.post("/v1/auth/register", json=_registration(started["id"]))
    assert not_yet.status_code == 409
    assert not_yet.json()["code"] == "email_not_verified"

    await api.get(sender.sent[0].path_and_query)
    registered = await api.post("/v1/auth/register", json=_registration(started["id"]))

    assert registered.status_code == 201
    profile = registered.json()["profile"]
    cleanup_users(UUID(profile["id"]))
    assert profile["email"] == started["email"]
    verified_at = (
        await owner_connection.execute(
            text("SELECT email_verified_at FROM iam.users WHERE id = :id"), {"id": profile["id"]}
        )
    ).scalar_one()
    assert verified_at is not None

    reused = await api.post("/v1/auth/register", json=_registration(started["id"]))
    assert reused.status_code == 404
    assert reused.json()["code"] == "not_found"
    assert (await api.get(f"/v1/auth/email-verifications/{started['id']}")).status_code == 404


async def test_el_correo_verificado_vence_a_los_30_minutos_rf26(
    api: AsyncClient, sender: FakeEmailSender, frozen_clock: Clock, new_email: Callable[[], str]
) -> None:
    started = (await _start(api, new_email())).json()
    await api.get(sender.sent[0].path_and_query)

    frozen_clock.advance(minutes=31)
    response = await api.post("/v1/auth/register", json=_registration(started["id"]))

    assert response.status_code == 410
    assert response.json()["code"] == "verification_expired"


async def test_una_verificacion_que_no_existe_es_404(api: AsyncClient) -> None:
    missing = uuid4()

    assert (await api.get(f"/v1/auth/email-verifications/{missing}")).status_code == 404
    assert (await api.post(f"/v1/auth/email-verifications/{missing}/resend")).status_code == 404
    registered = await api.post("/v1/auth/register", json=_registration(str(missing)))
    assert registered.status_code == 404


async def test_limita_los_links_por_ip(
    api: AsyncClient, sender: FakeEmailSender, new_email: Callable[[], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # El límite real es 100: con 3 se prueba lo mismo sin mandar 100 correos.
    monkeypatch.setattr(iam_router, "EMAIL_VERIFICATION_LIMIT", 3)
    for _ in range(3):
        assert (await _start(api, new_email())).status_code == 201

    blocked = await _start(api, new_email())

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_requests"
    assert len(sender.sent) == 3


async def test_limita_los_links_por_correo(
    api: AsyncClient, sender: FakeEmailSender, new_email: Callable[[], str]
) -> None:
    """Muchas personas detrás de la misma IP (la web, una operadora) no se frenan entre sí; un correo sí."""
    email = new_email()
    for _ in range(EMAIL_VERIFICATION_PER_EMAIL_LIMIT):
        assert (await _start(api, email)).status_code == 201

    blocked = await _start(api, email.upper())
    other = await _start(api, new_email())

    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_requests")
    assert other.status_code == 201
    assert len(sender.sent) == EMAIL_VERIFICATION_PER_EMAIL_LIMIT + 1
