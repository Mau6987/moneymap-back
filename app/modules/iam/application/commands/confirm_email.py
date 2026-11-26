"""Caso de uso de escritura: abrir el link del correo (RF-24)."""

from dataclasses import dataclass

from app.core import clock
from app.core.security import hash_verification_token
from app.modules.iam.application.verification_link import verified_ttl
from app.modules.iam.domain.models import VerificationStatus
from app.modules.iam.domain.ports import EmailVerificationRepository


@dataclass(frozen=True, slots=True)
class ConfirmationOutcome:
    """Qué página ve quien abrió el link. `status` None: el link no sirve."""

    status: VerificationStatus | None
    email: str | None = None


async def confirm_email(token: str, verifications: EmailVerificationRepository) -> ConfirmationOutcome:
    """Marca el correo como verificado si el link sigue vigente.

    Abrirlo dos veces no es un error: el correo sigue verificado. Un link
    reemplazado por un reenvío, o ya usado para crear la cuenta, no sirve.
    """
    now = clock.utc_now()
    verification = await verifications.find_by_token_hash(hash_verification_token(token))
    if verification is None or verification.used_at is not None:
        return ConfirmationOutcome(status=None)
    status = verification.status(now, verified_ttl())
    if status is VerificationStatus.PENDING:
        await verifications.mark_verified(verification.id, now)
        status = VerificationStatus.VERIFIED
    return ConfirmationOutcome(status=status, email=verification.email)
