"""Verificar el token de identidad de Apple (spec 001, RF-6 y RF-7).

Igual que con Google: la app hace el ingreso con Apple y manda el `identityToken`;
acá se comprueba la firma contra las claves públicas de Apple, que el token sea
para nuestra app y que Apple diga que el correo está verificado.

Apple es distinto en tres cosas:

- La audiencia no es una sola: el token que emite la app iOS la firma con el
  **bundle ID** (`com.moneymap.moneymapApp`) y el de la web, con el **Service ID**.
  Se aceptan las dos y se descartan las que no estén configuradas.
- `email_verified` viene como **texto** (`"true"`), no como booleano.
- El correo **solo viene la primera vez** que la persona autoriza la app; en las
  siguientes el token no lo trae. El flujo ya contempla que falte (RF-7).

No hace falta la clave `.p8` ni el `client_secret`: el token se verifica con las
claves públicas de Apple, que están en un JWKS.
"""

from collections.abc import Sequence

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwt import JWTClaimsRegistry

from app.modules.iam.domain.errors import InvalidProviderToken
from app.modules.iam.domain.models import SocialIdentity
from app.modules.iam.infrastructure.jwks import LoadKeySet

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
SIGNING_ALGORITHM = "RS256"


class AppleIdentityProvider:
    """Implementa `IdentityProvider`: verifica el token y dice quién es."""

    def __init__(self, client_ids: Sequence[str], load_key_set: LoadKeySet) -> None:
        self._client_ids = [client_id for client_id in client_ids if client_id]
        self._load_key_set = load_key_set

    async def verify(self, id_token: str) -> SocialIdentity:
        claims = await self._verified_claims(id_token)
        if not _is_true(claims.get("email_verified")):
            raise InvalidProviderToken("Apple no dice que ese correo esté verificado")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise InvalidProviderToken("El token de Apple no trae el usuario")
        email = claims.get("email")
        return SocialIdentity(
            provider="apple",
            subject=subject,
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
        )

    async def _verified_claims(self, id_token: str) -> dict[str, object]:
        key_set = await self._load_key_set()
        try:
            decoded = jwt.decode(id_token, key_set, algorithms=[SIGNING_ALGORITHM])
            JWTClaimsRegistry(iss={"essential": True, "value": APPLE_ISSUER}).validate(decoded.claims)
        except (JoseError, ValueError, KeyError) as exc:
            raise InvalidProviderToken("El token de Apple no es válido") from exc
        if not self._is_for_us(decoded.claims.get("aud")):
            raise InvalidProviderToken("El token de Apple no es para esta app")
        return dict(decoded.claims)

    def _is_for_us(self, audience: object) -> bool:
        """`aud` puede venir como texto o como lista; alcanza con que una coincida."""
        audiences = [audience] if isinstance(audience, str) else audience
        if not isinstance(audiences, list) or not self._client_ids:
            return False
        return any(isinstance(value, str) and value in self._client_ids for value in audiences)


def _is_true(value: object) -> bool:
    """Apple manda `email_verified` como texto ("true"); Google, como booleano."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")
