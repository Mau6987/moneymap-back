"""Caso de uso de lectura: cómo va la verificación del correo (RF-23)."""

from uuid import UUID

from app.core import clock
from app.core.errors import NotFound
from app.modules.iam.application.verification_link import describe
from app.modules.iam.domain.models import VerificationState
from app.modules.iam.domain.ports import EmailVerificationRepository


async def get_email_verification(
    verification_id: UUID,
    verifications: EmailVerificationRepository,
) -> VerificationState:
    """La que ya se usó para crear la cuenta tampoco existe: no vuelve a servir."""
    verification = await verifications.get(verification_id)
    if verification is None or verification.used_at is not None:
        raise NotFound("No existe esa verificación")
    return describe(verification, clock.utc_now())
