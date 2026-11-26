"""Caso de uso de escritura: empezar a verificar un correo, antes de la cuenta (RF-22)."""

from app.core import clock
from app.modules.iam.application.verification_link import VerificationLink, describe
from app.modules.iam.domain.errors import EmailAlreadyRegistered
from app.modules.iam.domain.models import VerificationState
from app.modules.iam.domain.ports import EmailSender, EmailVerificationRepository, UserRepository


async def start_email_verification(
    email: str,
    users: UserRepository,
    verifications: EmailVerificationRepository,
    sender: EmailSender,
) -> VerificationState:
    """Envía el link al correo. Si el correo ya tiene cuenta no envía nada: 409 `email_taken`."""
    if await users.email_taken(email):
        raise EmailAlreadyRegistered("Ese correo ya tiene una cuenta")
    now = clock.utc_now()
    link = VerificationLink(now)
    verification = await verifications.create(email, link.token_hash, link.expires_at, now)
    await sender.send_verification_link(email, link.url, link.ttl_minutes)
    return describe(verification, now)
