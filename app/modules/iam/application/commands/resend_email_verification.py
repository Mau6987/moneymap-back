"""Caso de uso de escritura: reenviar el link (RF-25)."""

from uuid import UUID

from app.core import clock
from app.core.errors import NotFound, TooManyRequests
from app.modules.iam.application.verification_link import VerificationLink, describe, resend_cooldown
from app.modules.iam.domain.models import VerificationState
from app.modules.iam.domain.ports import EmailSender, EmailVerificationRepository


async def resend_email_verification(
    verification_id: UUID,
    verifications: EmailVerificationRepository,
    sender: EmailSender,
) -> VerificationState:
    """Un link nuevo, y el anterior deja de servir. No antes de un minuto desde el último.

    Si el correo ya está verificado no hay nada que reenviar: devuelve el estado
    como está y la app sigue al registro.
    """
    now = clock.utc_now()
    verification = await verifications.get(verification_id, for_update=True)
    if verification is None or verification.used_at is not None:
        raise NotFound("No existe esa verificación")
    if verification.verified_at is not None:
        return describe(verification, now)
    available_at = verification.resend_available_at(resend_cooldown())
    if now < available_at:
        raise TooManyRequests(retry_after_seconds=max(int((available_at - now).total_seconds()) + 1, 1))
    link = VerificationLink(now)
    renewed = await verifications.renew_token(verification_id, link.token_hash, link.expires_at, now)
    await sender.send_verification_link(renewed.email, link.url, link.ttl_minutes)
    return describe(renewed, now)
