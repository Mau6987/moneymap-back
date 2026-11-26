"""Caso de uso de lectura: la base del simulador de What If? (spec 009, RF-20 a RF-23)."""

from datetime import date
from uuid import UUID

from app.modules.finance.domain.errors import OnboardingIncomplete
from app.modules.planning.domain.errors import AccountNotInCurrency
from app.modules.planning.domain.ports import WhatIfBaseReader
from app.modules.planning.domain.what_if_base import PeriodType, WhatIfBase


async def get_what_if_base(
    user_id: UUID,
    currency: str | None,
    period_type: PeriodType | None,
    on: date | None,
    account_id: UUID | None,
    reader: WhatIfBaseReader,
) -> WhatIfBase:
    """Los montos de partida de un periodo; los cambios los mueve el cliente y no se guardan.

    Sin moneda principal no hay en qué calcular: 422 `onboarding_incomplete`. Una
    cuenta ajena, borrada o de otra moneda: 404 (RF-21).
    """
    scope = await reader.scope(user_id, currency, period_type, on)
    if scope is None:
        raise OnboardingIncomplete("currency")
    if account_id is not None and not await reader.has_account(user_id, account_id, scope.currency):
        raise AccountNotInCurrency()
    return await reader.base(user_id, scope, account_id)
