"""El verificador del token de Apple (RF-6), con claves de prueba.

No se llama a Apple: se genera un par de claves RSA, se firma un token como lo
haría Apple y se comprueba que el verificador lo acepte o lo rechace.
"""

from datetime import UTC, datetime, timedelta

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from app.core import clock
from app.modules.iam.domain.errors import InvalidProviderToken
from app.modules.iam.infrastructure.apple_identity import APPLE_ISSUER, AppleIdentityProvider

BUNDLE_ID = "com.moneymap.moneymapApp"
SERVICE_ID = "com.moneymap.web"
KEY_ID = "clave-de-prueba"

_key = RSAKey.generate_key(2048, parameters={"kid": KEY_ID, "use": "sig", "alg": "RS256"})
_key_set = KeySet.import_key_set({"keys": [_key.as_dict(private=False)]})


async def _load_key_set() -> KeySet:
    return _key_set


def verifier(*client_ids: str) -> AppleIdentityProvider:
    return AppleIdentityProvider(client_ids or (BUNDLE_ID, SERVICE_ID), _load_key_set)


def apple_token(**overrides: object) -> str:
    """Un token como el que emite Apple, con lo que se quiera cambiar."""
    now = clock.utc_now()
    claims: dict[str, object] = {
        "iss": APPLE_ISSUER,
        "aud": BUNDLE_ID,
        "sub": "001234.abcdef.1234",
        "email": "Ana@Example.com",
        "email_verified": "true",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": KEY_ID}, claims, _key)


async def test_acepta_un_token_valido_de_la_app_ios() -> None:
    identity = await verifier().verify(apple_token())

    assert identity.provider == "apple"
    assert identity.subject == "001234.abcdef.1234"
    assert identity.email == "ana@example.com"  # se normaliza
    # Apple no manda el nombre en el token: lo pide el registro (RF-7).
    assert (identity.first_name, identity.last_name) == (None, None)


async def test_acepta_la_audiencia_del_service_id_de_la_web() -> None:
    """El mismo token sirve para la web: cambia la audiencia, no el verificador."""
    identity = await verifier().verify(apple_token(aud=SERVICE_ID))

    assert identity.email == "ana@example.com"


async def test_rechaza_un_token_que_no_es_para_esta_app() -> None:
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(apple_token(aud="com.otra.app"))


async def test_sin_audiencias_configuradas_no_acepta_nada() -> None:
    with pytest.raises(InvalidProviderToken):
        await AppleIdentityProvider([], _load_key_set).verify(apple_token())


async def test_rechaza_un_correo_que_apple_no_verifico() -> None:
    """Sin esto, cualquiera podría crear una cuenta de Apple con el correo de otra persona."""
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(apple_token(email_verified="false"))

    with pytest.raises(InvalidProviderToken):
        await verifier().verify(apple_token(email_verified=None))


async def test_acepta_email_verified_como_booleano() -> None:
    """Apple lo manda como texto; algunos tokens lo traen como booleano."""
    identity = await verifier().verify(apple_token(email_verified=True))

    assert identity.email == "ana@example.com"


async def test_el_correo_puede_faltar_en_el_segundo_ingreso() -> None:
    """Apple solo manda el correo la primera vez que se autoriza la app (RF-7)."""
    identity = await verifier().verify(apple_token(email=None))

    assert identity.email is None
    assert identity.subject == "001234.abcdef.1234"


async def test_rechaza_un_token_vencido() -> None:
    vencido = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(apple_token(exp=vencido))


async def test_rechaza_un_token_de_otro_emisor() -> None:
    with pytest.raises(InvalidProviderToken):
        await verifier().verify(apple_token(iss="https://accounts.google.com"))


async def test_rechaza_un_token_firmado_por_otro() -> None:
    otra_clave = RSAKey.generate_key(2048, parameters={"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    ajeno = jwt.encode({"alg": "RS256", "kid": KEY_ID}, {"sub": "1", "aud": BUNDLE_ID}, otra_clave)

    with pytest.raises(InvalidProviderToken):
        await verifier().verify(ajeno)


async def test_rechaza_algo_que_no_es_un_token() -> None:
    with pytest.raises(InvalidProviderToken):
        await verifier().verify("esto-no-es-un-token")
