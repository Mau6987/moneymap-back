"""Caso de uso de escritura: completar el registro social (RF-8)."""

from app.core import clock
from app.modules.iam.application.open_session import open_session
from app.modules.iam.application.social_registration import read_registration_token
from app.modules.iam.domain.errors import ProviderEmailMissing
from app.modules.iam.domain.models import AuthResult, NewUser, SocialRegistration
from app.modules.iam.domain.ports import SessionRepository, UserRepository


async def complete_social_registration(
    registration: SocialRegistration,
    registration_token: str,
    users: UserRepository,
    sessions: SessionRepository,
) -> AuthResult:
    """Crea la cuenta con la identidad del proveedor y abre su sesión.

    El correo es el que verificó el proveedor; el del pedido solo se usa si el
    proveedor no lo dio. La cuenta queda con el correo **ya verificado**, porque
    lo verificó Google. Los términos y el correo repetido los aplica la base.
    """
    identity = read_registration_token(registration_token)
    email = registration.email or identity.email
    if not email:
        raise ProviderEmailMissing("El proveedor no dio tu correo: escribilo para crear la cuenta")

    now = clock.utc_now()
    profile = await users.create(
        NewUser(
            email=email,
            first_name=registration.first_name,
            last_name=registration.last_name,
            terms_version=registration.terms_version,
            email_verified_at=now,
        )
    )
    await users.link_identity(profile.id, identity)
    tokens = await open_session(profile.id, sessions, now)
    return AuthResult(profile=profile, tokens=tokens)
