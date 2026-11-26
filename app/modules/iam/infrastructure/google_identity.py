"""Verificar el token de identidad que manda la app (spec 001, RF-6 y RF-7).

La app hace el ingreso con Google y manda el token; acá se comprueba la firma
contra las claves públicas de Google, que el token sea **para nuestra app**
(la audiencia) y que Google diga que el correo está verificado. Sin esa última
comprobación, cualquiera podría crear una cuenta de Google con el correo de otra
persona y quedarse con su cuenta de MoneyMap.

Se usa `joserfc`: es la librería a la que apunta authlib desde que su módulo de
JOSE quedó deprecado. Verifica la firma RS256 contra un JWKS.
"""

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwt import JWTClaimsRegistry

from app.modules.iam.domain.errors import InvalidProviderToken
from app.modules.iam.domain.models import SocialIdentity
from app.modules.iam.infrastructure.jwks import LoadKeySet

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Google usa los dos formatos según el momento del token.
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
SIGNING_ALGORITHM = "RS256"


class GoogleIdentityProvider:
    """Implementa `IdentityProvider`: verifica el token y dice quién es."""

    def __init__(self, client_id: str, load_key_set: LoadKeySet) -> None:
        self._client_id = client_id
        self._load_key_set = load_key_set

    async def verify(self, id_token: str) -> SocialIdentity:
        claims = await self._verified_claims(id_token)
        if claims.get("email_verified") is not True:
            raise InvalidProviderToken("Google no dice que ese correo esté verificado")
        email = claims.get("email")
        subject = claims.get("sub")
        if not isinstance(email, str) or not email.strip() or not isinstance(subject, str):
            raise InvalidProviderToken("El token de Google no trae el correo")
        return SocialIdentity(
            provider="google",
            subject=subject,
            email=email.strip().lower(),
            first_name=_optional_text(claims.get("given_name")),
            last_name=_optional_text(claims.get("family_name")),
        )

    async def _verified_claims(self, id_token: str) -> dict[str, object]:
        key_set = await self._load_key_set()
        try:
            decoded = jwt.decode(id_token, key_set, algorithms=[SIGNING_ALGORITHM])
            JWTClaimsRegistry(
                iss={"essential": True, "values": list(GOOGLE_ISSUERS)},
                aud={"essential": True, "value": self._client_id},
            ).validate(decoded.claims)
        except (JoseError, ValueError, KeyError) as exc:
            raise InvalidProviderToken("El token de Google no es válido") from exc
        return dict(decoded.claims)


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
