"""Caso de uso de escritura: registrar a una persona con correo y contraseña (RF-1, RF-26)."""

from app.core import clock
from app.core.errors import NotFound
from app.core.security import hash_password
from app.modules.iam.application.open_session import open_session
from app.modules.iam.application.verification_link import verified_ttl
from app.modules.iam.domain.errors import EmailNotVerified, VerificationExpired
from app.modules.iam.domain.models import AuthResult, NewUser, Registration, VerificationStatus
from app.modules.iam.domain.ports import EmailVerificationRepository, SessionRepository, UserRepository


async def register(
    registration: Registration,
    password: str,
    users: UserRepository,
    sessions: SessionRepository,
    verifications: EmailVerificationRepository,
) -> AuthResult:
    """Crea la persona con el correo que verificó, su identidad `password` y su primera sesión.

    La verificación queda usada en la misma transacción: no sirve para una
    segunda cuenta, y si dos pedidos llegan juntos el bloqueo deja pasar a uno.
    No valida los términos ni si el correo ya tiene cuenta: lo
    aplica la base (constitución §3) y `core/errors.py` traduce lo que devuelva.
    """
    now = clock.utc_now()
    verification = await verifications.get(registration.verification_id, for_update=True)
    if verification is None or verification.used_at is not None:
        raise NotFound("No existe esa verificación")
    match verification.status(now, verified_ttl()):
        case VerificationStatus.PENDING:
            raise EmailNotVerified("Todavía no abriste el link que te enviamos")
        case VerificationStatus.EXPIRED:
            raise VerificationExpired("La verificación venció: pedí un link nuevo")
        case VerificationStatus.VERIFIED:
            pass

    new_user = NewUser(
        email=verification.email,
        first_name=registration.first_name,
        last_name=registration.last_name,
        terms_version=registration.terms_version,
        email_verified_at=verification.verified_at,
    )
    profile = await users.create(new_user)
    await users.append_password_identity(profile.id, new_user.email, hash_password(password))
    await verifications.mark_used(verification.id, now)
    tokens = await open_session(profile.id, sessions, now)
    return AuthResult(profile=profile, tokens=tokens)
