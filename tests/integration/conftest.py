"""Base de datos real para las pruebas de integración.

PostgreSQL 16 con todas las migraciones aplicadas y el rol `moneymap_api` (que
hereda de `moneymap_app`, así que la RLS se aplica). Cada prueba crea su propio
usuario y no depende de las demás ni del orden.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import timedelta
from typing import NamedTuple
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.db import SessionLocal, user_session
from app.core.dependencies import get_current_user_id
from app.core.rate_limit import clear_rate_limits
from app.main import app
from app.modules.iam.deps import get_email_sender
from app.modules.iam.infrastructure.email_sender import LogEmailSender

# La versión vigente de los términos, en db/migrations/950_seed.sql
CURRENT_TERMS_VERSION = "2026-10"
VALID_PASSWORD = "clave-larga-123"  # noqa: S105 — la contraseña de las pruebas, no un secreto
# Los correos de las pruebas usan este dominio, para poder limpiarlos después.
TEST_EMAIL_DOMAIN = "example.com"

RegisterBody = Callable[..., Awaitable[dict[str, object]]]


class RegisteredUser(NamedTuple):
    """Un usuario creado por la API, como el que sale del onboarding."""

    id: UUID
    headers: dict[str, str]


async def create_financial_user(main_currency: str = "BOB") -> UUID:
    """Un usuario con su configuración financiera: moneda principal y categorías iniciales.

    `iam.users` no tiene RLS (el login ocurre antes de conocer al usuario), así que
    esa fila se inserta sin contexto. Lo que sí lo exige —`finance.user_settings`
    y las categorías— se hace dentro de la sesión del usuario.
    """
    async with SessionLocal() as session, session.begin():
        user_id: UUID = (
            await session.execute(
                text(
                    "INSERT INTO iam.users (email, first_name, last_name, display_name, terms_version)"
                    " VALUES (:email, 'Ana', 'Quispe', 'Ana', :terms_version)"
                    " RETURNING id"
                ),
                {"email": f"ana.{uuid4().hex}@{TEST_EMAIL_DOMAIN}", "terms_version": CURRENT_TERMS_VERSION},
            )
        ).scalar_one()
    async with user_session(user_id) as session:
        await session.execute(
            text("SELECT finance.setup_user(:user_id, :currency)"),
            {"user_id": user_id, "currency": main_currency},
        )
    return user_id


async def delete_user(user_id: UUID) -> None:
    """Borra al usuario y, en cascada, todo lo suyo. Dentro de su sesión: la RLS manda."""
    async with user_session(user_id) as session:
        await session.execute(text("DELETE FROM iam.users WHERE id = :user_id"), {"user_id": user_id})


@pytest.fixture(autouse=True)
async def reset_rate_limits() -> AsyncIterator[None]:
    """El límite de intentos cuenta por IP y en las pruebas todas salen de la misma."""
    await clear_rate_limits()
    yield
    await clear_rate_limits()


@pytest.fixture(autouse=True)
def never_send_real_email() -> Iterator[None]:
    """Las pruebas no mandan correos (engineering §2.6).

    Sin esto, un `.env` con `EMAIL_BACKEND=smtp` —como el de cualquiera que ya
    configuró Gmail— haría que las pruebas de verificación mandaran correos de
    verdad. El adaptador de dev escribe el link en el log y no sale a la red.
    """
    app.dependency_overrides[get_email_sender] = LogEmailSender
    yield
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture(autouse=True)
async def clean_email_verifications() -> AsyncIterator[None]:
    """Borra las verificaciones del correo que dejan las pruebas.

    `iam.email_verifications` no cuelga de `user_id` —la verificación existe antes
    que la cuenta—, así que el borrado en cascada de los usuarios no la toca y las
    filas se irían acumulando en la base de desarrollo.
    """
    yield
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text("DELETE FROM iam.email_verifications WHERE email LIKE :pattern"),
            {"pattern": f"%@{TEST_EMAIL_DOMAIN}"},
        )


async def create_verified_email(email: str) -> UUID:
    """Un correo ya verificado con el link (RF-24), listo para registrarse (RF-26).

    Se inserta directo: el camino del link lo cubre `test_iam_email_verification.py`.
    El correo se guarda como lo deja la API (sin espacios y en minúsculas).
    """
    now = utc_now()
    async with SessionLocal() as session, session.begin():
        verification_id: UUID = (
            await session.execute(
                text(
                    "INSERT INTO iam.email_verifications (email, token_hash, expires_at, verified_at)"
                    " VALUES (:email, :token_hash, :expires_at, :verified_at)"
                    " RETURNING id"
                ),
                {
                    "email": email.strip().lower(),
                    "token_hash": uuid4().hex,
                    "expires_at": now + timedelta(minutes=5),
                    "verified_at": now,
                },
            )
        ).scalar_one()
    return verification_id


@pytest.fixture
def register_body() -> RegisterBody:
    """El cuerpo de un registro válido, con un correo nuevo y ya verificado en cada llamada."""

    async def build(email: str | None = None, **overrides: object) -> dict[str, object]:
        verification_id = await create_verified_email(email or f"ana.{uuid4().hex[:12]}@{TEST_EMAIL_DOMAIN}")
        body: dict[str, object] = {
            "verification_id": str(verification_id),
            "password": VALID_PASSWORD,
            "first_name": "Ana",
            "last_name": "Quispe",
            "terms_version": CURRENT_TERMS_VERSION,
        }
        body.update(overrides)
        return body

    return build


@pytest.fixture
async def cleanup_users() -> AsyncIterator[Callable[[UUID], None]]:
    """Anota los usuarios que crea la API, para borrarlos al terminar la prueba."""
    created: list[UUID] = []

    def remember(user_id: UUID) -> None:
        created.append(user_id)

    yield remember

    for user_id in created:
        await delete_user(user_id)


@pytest.fixture
async def new_financial_user() -> AsyncIterator[Callable[[str], Awaitable[UUID]]]:
    """Crea usuarios que se borran al terminar la prueba."""
    created: list[UUID] = []

    async def factory(main_currency: str = "BOB") -> UUID:
        user_id = await create_financial_user(main_currency)
        created.append(user_id)
        return user_id

    yield factory

    for user_id in created:
        await delete_user(user_id)


@pytest.fixture
async def user_id(new_financial_user: Callable[[str], Awaitable[UUID]]) -> UUID:
    """Un usuario listo para usar."""
    return await new_financial_user()


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    """La API sin usuario inyectado: para el registro, el login y el refresh."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def registered_user(
    api: AsyncClient,
    register_body: RegisterBody,
    cleanup_users: Callable[[UUID], None],
) -> RegisteredUser:
    """Un usuario recién registrado, con su token de acceso."""
    response = await api.post("/v1/auth/register", json=await register_body())
    assert response.status_code == 201
    body = response.json()
    user_id = UUID(body["profile"]["id"])
    cleanup_users(user_id)
    return RegisteredUser(id=user_id, headers={"Authorization": f"Bearer {body['access_token']}"})


@pytest.fixture
async def allow_more_currencies(owner_connection: AsyncConnection) -> AsyncIterator[None]:
    """Sube el límite de monedas del plan gratuito mientras dura la prueba.

    Lo gratuito permite **una sola moneda**, así que sin esto no se pueden tener
    cuentas en dos monedas —y la spec 002 lo necesita para probar transferencias
    entre monedas distintas—. Los límites son datos (constitución §4), no código.
    """
    await owner_connection.execute(
        text(
            "UPDATE billing.plan_features SET limit_value = NULL"
            " WHERE feature_key = 'finance.currencies'"
            " AND plan_id = (SELECT id FROM billing.plans WHERE code = 'free')"
        )
    )
    await owner_connection.commit()

    yield

    await owner_connection.execute(
        text(
            "UPDATE billing.plan_features SET limit_value = 1"
            " WHERE feature_key = 'finance.currencies'"
            " AND plan_id = (SELECT id FROM billing.plans WHERE code = 'free')"
        )
    )
    await owner_connection.commit()


@pytest.fixture
async def allow_voice(owner_connection: AsyncConnection) -> AsyncIterator[None]:
    """Prende el registro por voz del plan gratuito mientras dura la prueba.

    Desde la migración 0023 el gratuito no lo incluye; las pruebas de voz
    necesitan un usuario que pueda dictar.
    """
    sql = (
        "UPDATE billing.plan_features SET is_enabled = :enabled, limit_value = :limit"
        " WHERE feature_key = 'ai.voice_entries'"
        " AND plan_id = (SELECT id FROM billing.plans WHERE code = 'free')"
    )
    await owner_connection.execute(text(sql), {"enabled": True, "limit": 30})
    await owner_connection.commit()

    yield

    await owner_connection.execute(text(sql), {"enabled": False, "limit": 0})
    await owner_connection.commit()


@pytest.fixture
async def deactivate_currency(
    owner_connection: AsyncConnection,
) -> AsyncIterator[Callable[[str], Awaitable[None]]]:
    """Retira una moneda del catálogo (RF-20) y la vuelve a activar al terminar.

    Se confirma el cambio porque la API la lee desde otra conexión.
    """
    used: list[str] = []

    async def deactivate(code: str) -> None:
        used.append(code)
        await owner_connection.execute(
            text("UPDATE catalog.currencies SET is_active = false WHERE code = :code"), {"code": code}
        )
        await owner_connection.commit()

    yield deactivate

    for code in used:
        await owner_connection.execute(
            text("UPDATE catalog.currencies SET is_active = true WHERE code = :code"), {"code": code}
        )
    await owner_connection.commit()


@pytest.fixture
async def client(user_id: UUID) -> AsyncIterator[AsyncClient]:
    """La API con el usuario de la prueba inyectado.

    Reemplaza la dependencia de identidad: el resto del camino —router, caso de
    uso, SQL y traducción de errores— es el real. Los endpoints autenticados
    también se prueban con un token de verdad, en `test_finance_accounts.py`.
    """
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest.fixture
async def owner_connection() -> AsyncIterator[AsyncConnection]:
    """Una conexión con el dueño de las tablas, que sí salta la RLS.

    Para comprobar lo que la API solo escribe: `ops.logs` no lo puede leer
    `moneymap_app` (db/migrations/900_security.sql).
    """
    url = make_url(get_settings().migrations_database_url).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()
