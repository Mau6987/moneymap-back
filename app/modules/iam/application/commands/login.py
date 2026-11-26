"""Caso de uso de escritura: iniciar sesión con correo y contraseña (RF-20)."""

from app.core import clock
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.modules.iam.application.open_session import open_session
from app.modules.iam.domain.errors import EmailNotVerified, InvalidCredentials
from app.modules.iam.domain.models import TokenPair
from app.modules.iam.domain.ports import SessionRepository, UserRepository

INVALID_CREDENTIALS_DETAIL = "Correo o contraseña incorrectos"
EMAIL_NOT_VERIFIED_DETAIL = "Verificá tu correo antes de entrar"


async def login(
    email: str,
    password: str,
    users: UserRepository,
    sessions: SessionRepository,
) -> TokenPair:
    """Verifica la contraseña y abre una sesión nueva.

    Si el correo no existe se verifica igual contra un hash de mentira: así el
    login tarda lo mismo y no se puede averiguar qué correos tienen cuenta.

    Una cuenta con el correo sin confirmar no entra (MM-88). Se comprueba
    **después** de la contraseña: con una clave mala la respuesta sigue siendo
    `invalid_credentials` y no delata que la cuenta existe.
    """
    identity = await users.find_password_identity(email)
    password_hash = identity.password_hash if identity is not None else DUMMY_PASSWORD_HASH
    if not verify_password(password, password_hash) or identity is None:
        raise InvalidCredentials(INVALID_CREDENTIALS_DETAIL)
    if identity.email_verified_at is None:
        raise EmailNotVerified(EMAIL_NOT_VERIFIED_DETAIL)
    await users.cancel_deletion(identity.user_id)  # spec 001, RF-30: entrar lo cancela
    return await open_session(identity.user_id, sessions, clock.utc_now())
