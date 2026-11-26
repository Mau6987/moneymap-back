"""Caso de uso de lectura: hasta dónde llegó el onboarding (spec 007, RF-3)."""

from uuid import UUID

from app.modules.finance.domain.models import OnboardingStatus
from app.modules.finance.domain.ports import OnboardingRepository


async def get_onboarding_status(user_id: UUID, onboarding: OnboardingRepository) -> OnboardingStatus:
    """Si terminó y qué pasos ya guardó: la app retoma desde el primero que falta."""
    return await onboarding.status(user_id)
