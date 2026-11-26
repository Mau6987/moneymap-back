"""Contraseñas y tokens de acceso (constitución §5).

argon2id para las contraseñas. El token de acceso es un JWT corto y firmado; el
refresh token es opaco y de la base solo se guarda su hash: si alguien lee la
tabla, no puede usarlo.
"""

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core import clock
from app.core.config import get_settings

# El algoritmo y el tipo de token, no secretos: noqa por el falso positivo de S105.
ACCESS_TOKEN_ALGORITHM = "HS256"  # noqa: S105
ACCESS_TOKEN_TYPE = "access"  # noqa: S105

# 32 bytes de entropía en el refresh token: adivinarlo no es viable.
REFRESH_TOKEN_BYTES = 32

_hasher = PasswordHasher()  # argon2id con los parámetros por defecto

# Se verifica contra este hash cuando el usuario no existe, para que el login
# tarde lo mismo y no se pueda averiguar qué correos tienen cuenta.
DUMMY_PASSWORD_HASH = _hasher.hash("moneymap-correo-inexistente")


class InvalidAccessTokenError(ValueError):
    """El token de acceso no sirve: mal formado, vencido, de otro tipo o con otra firma."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def access_token_ttl_seconds() -> int:
    return get_settings().access_token_ttl_minutes * 60


def refresh_token_ttl_days() -> int:
    return get_settings().refresh_token_ttl_days


def create_access_token(user_id: UUID) -> str:
    """Un JWT firmado, con el usuario en `sub`."""
    ttl_minutes = get_settings().access_token_ttl_minutes
    return sign_claims({"sub": str(user_id), "type": ACCESS_TOKEN_TYPE}, ttl_minutes=ttl_minutes)


def read_access_token(token: str) -> UUID:
    """El usuario del token, o `InvalidAccessTokenError`."""
    payload = read_claims(token, expected_type=ACCESS_TOKEN_TYPE)
    try:
        return UUID(str(payload["sub"]))
    except ValueError as exc:
        raise InvalidAccessTokenError("El token no trae un usuario válido") from exc


def create_refresh_token() -> str:
    """Un token opaco, imposible de adivinar."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Lo que se guarda en `iam.sessions.refresh_token_hash`."""
    return hashlib.sha256(token.encode()).hexdigest()


RESET_CODE_DIGITS = 6


def create_reset_code() -> str:
    """El código del restablecimiento: 6 dígitos, con `secrets` (no se adivina por el reloj)."""
    return f"{secrets.randbelow(10**RESET_CODE_DIGITS):0{RESET_CODE_DIGITS}d}"


def hash_code(code: str) -> str:
    """El código se guarda con argon2id, como una contraseña.

    Un hash rápido no sirve acá: con 6 dígitos se prueban los 10**6 en un segundo.
    Con argon2id, cada intento cuesta lo mismo que verificar una contraseña.
    """
    return _hasher.hash(code)


def verify_code(code: str, code_hash: str) -> bool:
    return verify_password(code, code_hash)


def sign_claims(payload: dict[str, Any], *, ttl_minutes: int) -> str:
    """Firma un JWT con el secreto de la API, con su `iat` y su `exp`."""
    settings = get_settings()
    issued_at = clock.utc_now()
    claims = {**payload, "iat": issued_at, "exp": issued_at + timedelta(minutes=ttl_minutes)}
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=ACCESS_TOKEN_ALGORITHM)


def read_claims(token: str, *, expected_type: str) -> dict[str, Any]:
    """Verifica firma y vencimiento, y exige el tipo de token. `InvalidAccessTokenError` si no."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise InvalidAccessTokenError("El token no es válido") from exc
    if payload.get("type") != expected_type:
        raise InvalidAccessTokenError(f"El token no es de tipo {expected_type}")
    return payload


def create_verification_token() -> str:
    """El token del link que llega por correo (spec 001, RF-22): tan imposible de adivinar como el refresh."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_verification_token(token: str) -> str:
    """Lo que se guarda en `iam.email_verifications.token_hash`."""
    return hashlib.sha256(token.encode()).hexdigest()
