"""El verificador del token de Google (RF-6), con claves de prueba.

No se llama a Google: se genera un par de claves RSA, se firma un token como lo
haría Google y se comprueba que el verificador lo acepte o lo rechace. Es la
parte con más riesgo del ingreso, así que se prueba entera.
"""

from datetime import UTC, datetime, timedelta

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from app.core import clock
from app.modules.iam.domain.errors import InvalidProviderToken
from app.modules.iam.infrastructure.google_identity import GOOGLE_ISSUERS, GoogleIdentityProvider

CLIENT_ID = "1234-abc.apps.googleusercontent.com"
KEY_ID = "clave-de-prueba"

_key = RSAKey.generate_key(2048, parameters={"kid": KEY_ID, "use": "sig", "alg": "RS256"})
_key_set = KeySet.import_key_set({"keys": [_key.as_dict(private=False)]})


async def _load_key_set() -> KeySet:
    return _key_set


def verifier() -> GoogleIdentityProvider:
    return GoogleIdentityProvider(CLIENT_ID, _load_key_set)


def google_token(**overrides: object) -> str:
    """Un token como el que emite Google, con lo que se quiera cambiar."""
    now = clock.utc_now()
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Ana@Example.com",
        "email_verified": True,
        "given_name": "Ana",
        "family_name": "Quispe",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": KEY_ID}, claims, _key)


async def test_acepta_un_token_valido_y_devuelve_quien_es() -> None:
    identity = await verifier().verify(google_token())

    assert identity.provider == "google"
    assert identity.subject == "1234567890"
    assert identity.email == "ana@example.com"  # se normaliza
    assert (identity.first_name, identity.last_name) == ("Ana", "Quispe")


async def test_acepta_los_dos_formatos_de_emisor_de_google() -> None:
    for issuer in GOOGLE_ISSUERS:
        identity = await verifier().verify(google_token(iss=issuer))
        assert identity.email == "ana@example.com"


async def test_rechaza_un_token_que_no_es_para_esta_app() -> None:
    """La audiencia es lo que impide que sirva el token de otra aplicación."""
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(google_token(aud="otra-app.apps.googleusercontent.com"))


async def test_rechaza_un_correo_que_google_no_verifico() -> None:
    """Sin esto, cualquiera podría crear una cuenta de Google con el correo de otra persona."""
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(google_token(email_verified=False))

    with pytest.raises(InvalidProviderToken):
        await verifier().verify(google_token(email_verified=None))


async def test_rechaza_un_token_vencido() -> None:
    vencido = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(google_token(exp=vencido))


async def test_rechaza_un_token_firmado_por_otro() -> None:
    otra_clave = RSAKey.generate_key(2048, parameters={"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    ajeno = jwt.encode({"alg": "RS256", "kid": KEY_ID}, {"sub": "1", "aud": CLIENT_ID}, otra_clave)

    with pytest.raises(InvalidProviderToken):
        await verifier().verify(ajeno)


async def test_rechaza_algo_que_no_es_un_token() -> None:
    with pytest.raises(InvalidProviderToken):
        await verifier().verify("esto-no-es-un-token")


async def test_el_nombre_puede_faltar() -> None:
    """RF-7: si el proveedor no lo da, la app lo pide al completar el registro."""
    identity = await verifier().verify(google_token(given_name=None, family_name=None))

    assert (identity.first_name, identity.last_name) == (None, None)
