"""Caso de uso de escritura: entrar con Google, o pedir los datos que falten (RF-6, RF-7).

Es el flujo que más cuidado tiene: si el correo ya tiene cuenta, se **vincula** y
entra (decisión del 2026-10-16), y si no la tiene se le pide completar el registro.
"""

from datetime import timedelta

from app.core import clock
from app.modules.iam.application.open_session import open_session
from app.modules.iam.application.social_registration import create_registration_token
from app.modules.iam.domain.models import RegistrationRequired, SignedIn, SocialIdentity, SocialSignIn
from app.modules.iam.domain.ports import SessionRepository, UserRepository

REGISTRATION_TOKEN_TTL_MINUTES = 15


async def sign_in_with_provider(
    identity: SocialIdentity,
    users: UserRepository,
    sessions: SessionRepository,
) -> SocialSignIn:
    """Entra si ya tiene cuenta; si no, devuelve lo necesario para crearla.

    El proveedor ya comprobó que el correo es de esa persona (`email_verified`),
    así que si el correo tiene una cuenta con contraseña se vincula sin pedir
    nada más: es la misma persona y ya lo demostró.
    """
    user_id = await users.find_sign_in_id_by_identity(identity.provider, identity.subject)
    if user_id is None:
        user_id = await users.find_sign_in_id_by_email(identity.email) if identity.email else None
        if user_id is None:
            return RegistrationRequired(
                identity=identity,
                registration_token=create_registration_token(identity, ttl_minutes=REGISTRATION_TOKEN_TTL_MINUTES),
            )
        await users.link_identity(user_id, identity)

    await users.cancel_deletion(user_id)  # RF-30: entrar lo cancela
    tokens = await open_session(user_id, sessions, clock.utc_now())
    return SignedIn(tokens=tokens)


def registration_ttl() -> timedelta:
    return timedelta(minutes=REGISTRATION_TOKEN_TTL_MINUTES)
