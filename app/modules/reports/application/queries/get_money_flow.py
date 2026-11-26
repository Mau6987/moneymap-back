"""Casos de uso de lectura: Map y Money Flow (spec 004, RF-1 a RF-8)."""

from datetime import date
from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.reports.domain.errors import PeriodConflict
from app.modules.reports.domain.models import FlowCategories, FlowGroup, MoneyFlow
from app.modules.reports.domain.ports import ReportsReader


async def get_money_flow(
    user_id: UUID, currency: str | None, month: date | None, reader: ReportsReader, on: date | None = None
) -> MoneyFlow:
    """La posición (RF-1) y el Money Flow (RF-6) salen del mismo cálculo.

    Un mes sin movimientos da todo en cero (RF-16). Sin moneda principal no hay
    en qué calcular: 422 `onboarding_incomplete`, como en Safe to Spend.
    """
    if month is not None and on is not None:
        raise PeriodConflict()
    flow = await reader.money_flow(user_id, currency, month, on)
    if flow is None:
        raise OnboardingIncomplete("currency")
    return flow


async def get_flow_categories(
    user_id: UUID,
    currency: str | None,
    month: date | None,
    group: FlowGroup,
    reader: ReportsReader,
    on: date | None = None,
) -> FlowCategories:
    """RF-8: las categorías de un grupo, de mayor a menor."""
    if month is not None and on is not None:
        raise PeriodConflict()
    categories = await reader.flow_categories(user_id, currency, month, group, on)
    if categories is None:
        raise OnboardingIncomplete("currency")
    return categories
