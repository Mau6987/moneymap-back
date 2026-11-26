"""Contraseñas y tokens, sin base de datos (constitución §5)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core import clock
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    InvalidAccessTokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    read_access_token,
    verify_code,
    verify_password,
)


def test_la_contrasena_no_se_guarda_en_claro() -> None:
    password_hash = hash_password("clave-larga-123")

    assert password_hash.startswith("$argon2id$")
    assert "clave-larga-123" not in password_hash
    assert verify_password("clave-larga-123", password_hash)
    assert not verify_password("otra-clave-larga", password_hash)


def test_un_hash_ilegible_no_rompe_la_verificacion() -> None:
    assert not verify_password("clave-larga-123", "esto-no-es-un-hash")


def test_el_hash_de_mentira_no_coincide_ni_rompe() -> None:
    """El código de un correo sin cuenta se compara contra él (spec 008, RF-12):
    cuesta lo mismo que uno real y nunca coincide."""
    assert not verify_code("123456", DUMMY_PASSWORD_HASH)


def test_el_token_de_acceso_lleva_al_usuario() -> None:
    user_id = uuid4()

    assert read_access_token(create_access_token(user_id)) == user_id


def test_un_token_de_acceso_vencido_no_sirve(monkeypatch: pytest.MonkeyPatch) -> None:
    # Se firma como si fuera hace 40 minutos: su vida útil son 15, así que ya venció.
    monkeypatch.setattr(clock, "utc_now", lambda: datetime.now(UTC) - timedelta(minutes=40))
    token = create_access_token(uuid4())
    monkeypatch.undo()

    with pytest.raises(InvalidAccessTokenError):
        read_access_token(token)


def test_un_token_con_otra_firma_no_sirve() -> None:
    header, payload, signature = create_access_token(uuid4()).split(".")
    other_signature = signature[:-1] + ("A" if signature[-1] != "A" else "B")

    with pytest.raises(InvalidAccessTokenError):
        read_access_token(f"{header}.{payload}.{other_signature}")


def test_un_texto_que_no_es_un_token_no_sirve() -> None:
    with pytest.raises(InvalidAccessTokenError):
        read_access_token("no-es-un-jwt")


def test_el_refresh_token_es_opaco_y_se_guarda_hasheado() -> None:
    token = create_refresh_token()

    assert len(token) >= 32
    assert token != create_refresh_token()
    assert hash_refresh_token(token) != token
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert len(hash_refresh_token(token)) == 64
