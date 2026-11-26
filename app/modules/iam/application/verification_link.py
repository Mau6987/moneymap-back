"""Emitir un link de verificación: el token, su hash y el correo (RF-22, RF-25)."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

from app.core.config import get_settings
from app.core.security import create_verification_token, hash_verification_token
from app.modules.iam.domain.models import EmailVerification, VerificationState

VERIFY_EMAIL_PATH = "/v1/auth/verify-email"


class VerificationLink:
    """Un link nuevo. El token en claro solo viaja en el correo; la base guarda su hash."""

    def __init__(self, now: datetime) -> None:
        settings = get_settings()
        token = create_verification_token()
        self.token_hash = hash_verification_token(token)
        self.ttl_minutes = settings.email_verification_ttl_minutes
        self.expires_at = now + timedelta(minutes=self.ttl_minutes)
        self.url = f"{settings.public_base_url.rstrip('/')}{VERIFY_EMAIL_PATH}?{urlencode({'token': token})}"


def resend_cooldown() -> timedelta:
    return timedelta(seconds=get_settings().email_verification_resend_seconds)


def verified_ttl() -> timedelta:
    return timedelta(minutes=get_settings().verified_email_ttl_minutes)


def describe(verification: EmailVerification, now: datetime) -> VerificationState:
    return VerificationState(
        id=verification.id,
        email=verification.email,
        status=verification.status(now, verified_ttl()),
        expires_at=verification.expires_at,
        resend_available_at=verification.resend_available_at(resend_cooldown()),
    )
