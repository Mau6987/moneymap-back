"""Caso de uso de escritura: cerrar el onboarding (spec 007, RF-4 y RF-5)."""

from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.finance.domain.models import OnboardingSummary
from app.modules.finance.domain.ports import OnboardingRepository


async def complete_onboarding(user_id: UUID, onboarding: OnboardingRepository) -> OnboardingSummary:
    """Marca el onboarding como terminado y devuelve Ingresos, Comprometido y Safe to Spend.

    Idempotente: si ya estaba marcado, conserva la fecha y vuelve a dar el
    resumen. Sin moneda principal o sin ninguna cuenta responde 422
    `onboarding_incomplete` con el paso que falta. El ingreso y los gastos
    recurrentes son opcionales (RF-9 de la app): sin ellos, Comprometido es cero.
    """
    status = await onboarding.status(user_id)
    if status.main_currency is None:
        raise OnboardingIncomplete("currency")
    if status.accounts == 0:
        raise OnboardingIncomplete("accounts")
    await onboarding.mark_completed(user_id)
    return await onboarding.summary(user_id)
