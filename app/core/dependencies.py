"""Dependencias de FastAPI que comparten todos los módulos: identidad y sesión.

La identidad sale del token de acceso (spec 001, RF-19): un JWT firmado con el
usuario en `sub`. De ahí sale `app.user_id`, que es lo que hace que la RLS
devuelva las filas del usuario y solo las suyas.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, user_session
from app.core.errors import Unauthorized
from app.core.security import InvalidAccessTokenError, read_access_token

# auto_error=False: el 401 lo arma la API, en problem+json, no FastAPI.
_bearer = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def get_current_user_id(credentials: BearerCredentials) -> UUID:
    """El usuario del token de acceso (RF-19)."""
    if credentials is None or not credentials.credentials:
        raise Unauthorized("Falta el token de acceso")
    try:
        return read_access_token(credentials.credentials)
    except InvalidAccessTokenError as exc:
        raise Unauthorized("El token de acceso no es válido o venció") from exc


async def current_session(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> AsyncIterator[AsyncSession]:
    """La transacción del usuario: empieza con app.user_id, así la RLS devuelve sus filas."""
    async with user_session(user_id) as session:
        yield session


async def public_session() -> AsyncIterator[AsyncSession]:
    """Para lo que pasa antes de saber quién es: registro, login y refresh.

    `iam.users`, `iam.auth_identities` y `iam.sessions` no tienen RLS a propósito
    —el login ocurre antes de conocer al usuario— y su acceso se controla en la
    API (db/migrations/900_security.sql).
    """
    async with SessionLocal() as session, session.begin():
        yield session
