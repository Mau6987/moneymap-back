"""Caso de uso de lectura: la configuración financiera (RF-1; spec 003, RF-7)."""

from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.finance.domain.models import UserSettings
from app.modules.finance.domain.ports import SettingsRepository


async def get_settings(user_id: UUID, settings: SettingsRepository) -> UserSettings:
    """Sin moneda principal todavía no hay configuración: 422 `onboarding_incomplete`."""
    stored = await settings.get(user_id)
    if stored is None:
        raise OnboardingIncomplete("currency")
    return stored
