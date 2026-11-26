"""Caso de uso de escritura: la configuración financiera (RF-1; spec 003, RF-7)."""

from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.finance.domain.models import SettingsChanges, UserSettings
from app.modules.finance.domain.ports import SettingsRepository


async def update_settings(changes: SettingsChanges, user_id: UUID, settings: SettingsRepository) -> UserSettings:
    """La moneda principal, el periodo financiero y el ahorro planificado.

    La moneda principal va primero: la primera vez crea la configuración y
    siembra las categorías (paso 1 del onboarding). Cambiarla no convierte ningún
    monto. Sin configuración todavía, el periodo y el ahorro no tienen dónde
    guardarse: 422 `onboarding_incomplete`. Lo que valida cada valor lo aplica la
    base (constitución §3) y `core/errors.py` lo traduce.
    """
    saved = None
    if changes.main_currency is not None:
        saved = await settings.save_main_currency(user_id, changes.main_currency)
    if changes.period_type is None and changes.period_start_day is None and changes.planned_savings is None:
        if saved is None:
            raise OnboardingIncomplete("currency")
        return saved
    updated = await settings.update(user_id, changes)
    if updated is None:
        raise OnboardingIncomplete("currency")
    return updated
