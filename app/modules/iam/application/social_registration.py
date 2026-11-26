"""El `registration_token` del registro social (RF-7 y RF-8).

Es un JWT firmado con el mismo secreto de la API: lleva quién es la persona
según el proveedor y vence a los 15 minutos. No hace falta guardarlo en ningún
lado, y la app no puede cambiarlo sin la firma.
"""

from app.core.security import read_claims, sign_claims
from app.modules.iam.domain.errors import InvalidRegistrationToken
from app.modules.iam.domain.models import SocialIdentity

REGISTRATION_TOKEN_TYPE = "provider_registration"  # noqa: S105 — el tipo del token, no un secreto


def create_registration_token(identity: SocialIdentity, *, ttl_minutes: int) -> str:
    return sign_claims(
        {
            "type": REGISTRATION_TOKEN_TYPE,
            "provider": identity.provider,
            "sub": identity.subject,
            "email": identity.email,
            "first_name": identity.first_name,
            "last_name": identity.last_name,
        },
        ttl_minutes=ttl_minutes,
    )


def read_registration_token(token: str) -> SocialIdentity:
    """Quién es, o `InvalidRegistrationToken` si no sirve o venció."""
    try:
        claims = read_claims(token, expected_type=REGISTRATION_TOKEN_TYPE)
        return SocialIdentity(
            provider=_text(claims["provider"]),
            subject=_text(claims["sub"]),
            email=_optional_text(claims.get("email")),
            first_name=_optional_text(claims.get("first_name")),
            last_name=_optional_text(claims.get("last_name")),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidRegistrationToken("El token de registro no sirve: pedí el ingreso de nuevo") from exc


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("falta un dato del proveedor")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
