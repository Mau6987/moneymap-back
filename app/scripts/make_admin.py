"""Nombra al administrador del panel de planes (MM-189) con su correo y contraseña.

Uso: uv run python -m app.scripts.make_admin correo@dominio.com [--nombre Ana] [--apellido Quispe]

Pide la contraseña sin mostrarla (dos veces), así no queda en el historial de
la consola. Si el correo no tiene cuenta, la crea ya verificada; si la tiene,
le pone esa contraseña. En los dos casos la deja como el único administrador:
el que había deja de serlo. Usa la conexión del dueño de la base (la de las
migraciones), porque `moneymap_app` no puede escribir `is_admin`.
"""

import argparse
import asyncio
import getpass
import sys
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.iam.schemas import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

_FIND_USER = text("SELECT id, status FROM iam.users WHERE email = :email AND deleted_at IS NULL")

# display_name lo completa el trigger con el nombre; los términos, los vigentes.
_INSERT_USER = text(
    """
    INSERT INTO iam.users (email, first_name, last_name, display_name, terms_version, email_verified_at)
    VALUES (:email, :first_name, :last_name, :first_name,
            (SELECT version FROM iam.terms_versions WHERE is_current), :now)
    RETURNING id
    """
)

_VERIFY_EMAIL = text("UPDATE iam.users SET email_verified_at = coalesce(email_verified_at, :now) WHERE id = :id")

# Una cuenta de Google todavía no tiene identidad `password`: se la agrega.
_SET_PASSWORD = text(
    """
    INSERT INTO iam.auth_identities (user_id, provider, provider_subject, password_hash)
    VALUES (:id, 'password', :email, :password_hash)
    ON CONFLICT (user_id, provider) DO UPDATE SET password_hash = EXCLUDED.password_hash
    """
)

# El índice único parcial permite uno solo: primero se le saca al anterior.
_CLEAR_ADMIN = text("UPDATE iam.users SET is_admin = false WHERE is_admin AND id <> :id")
_SET_ADMIN = text("UPDATE iam.users SET is_admin = true WHERE id = :id")


class AdminResult(NamedTuple):
    id: UUID
    created: bool


class AdminError(Exception):
    """Un dato que no sirve; el mensaje es para la persona que corre el script."""


def check_password(password: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        limits = f"entre {PASSWORD_MIN_LENGTH} y {PASSWORD_MAX_LENGTH}"
        raise AdminError(f"La contraseña tiene que tener {limits} caracteres")


async def make_admin(
    connection: AsyncConnection, email: str, password: str, first_name: str, last_name: str = "MoneyMap"
) -> AdminResult:
    """Crea o actualiza la cuenta y la deja como administrador, todo en una transacción."""
    email = email.strip()
    if "@" not in email:
        raise AdminError("Ese correo no es válido")
    check_password(password)
    now = clock.utc_now()
    async with connection.begin():
        row = (await connection.execute(_FIND_USER, {"email": email})).one_or_none()
        if row is not None and row.status != "active":
            raise AdminError(f"La cuenta de {email} no está activa ({row.status})")
        created = row is None
        if row is None:
            user_id: UUID = (
                await connection.execute(
                    _INSERT_USER, {"email": email, "first_name": first_name, "last_name": last_name, "now": now}
                )
            ).scalar_one()
        else:
            user_id = row.id
            await connection.execute(_VERIFY_EMAIL, {"id": user_id, "now": now})
        await connection.execute(
            _SET_PASSWORD, {"id": user_id, "email": email, "password_hash": hash_password(password)}
        )
        await connection.execute(_CLEAR_ADMIN, {"id": user_id})
        await connection.execute(_SET_ADMIN, {"id": user_id})
    return AdminResult(id=user_id, created=created)


def _ask_password() -> str:
    password = getpass.getpass("Contraseña: ")
    check_password(password)
    if getpass.getpass("Repite la contraseña: ") != password:
        raise AdminError("Las contraseñas no coinciden")
    return password


async def _run(email: str, password: str, first_name: str, last_name: str) -> AdminResult:
    url = make_url(get_settings().migrations_database_url).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await make_admin(connection, email, password, first_name, last_name)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nombra al administrador del panel de planes.")
    parser.add_argument("email", help="el correo con el que va a entrar")
    parser.add_argument("--nombre", default="Administrador", help="el nombre si la cuenta es nueva")
    parser.add_argument("--apellido", default="MoneyMap", help="el apellido si la cuenta es nueva")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args.email, _ask_password(), args.nombre, args.apellido))
    except AdminError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    done = "Cuenta creada" if result.created else "Contraseña actualizada"
    print(f"{done}. {args.email} es ahora el administrador: entra en la web y ve a /admin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
