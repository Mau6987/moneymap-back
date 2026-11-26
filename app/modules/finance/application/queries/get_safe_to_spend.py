"""Caso de uso de lectura: Safe to Spend (spec 003, RF-1 a RF-6)."""

from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.finance.domain.models import SafeToSpend
from app.modules.finance.domain.ports import SafeToSpendReader


async def get_safe_to_spend(user_id: UUID, currency: str | None, reader: SafeToSpendReader) -> SafeToSpend:
    """En la moneda pedida o, sin ella, en la principal (RF-3).

    Sin cuentas en esa moneda el desglose sale en cero, no es un error (RF-16).
    Sin moneda principal todavía no hay en qué calcular: 422 `onboarding_incomplete`.
    """
    computed = await reader.compute(user_id, currency)
    if computed is None:
        raise OnboardingIncomplete("currency")
    return computed
