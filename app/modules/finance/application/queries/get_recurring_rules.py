"""Caso de uso de lectura: los recurrentes del usuario (RF-29)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.finance.domain.models import RecurringRuleRecord
from app.modules.finance.domain.ports import RecurringRuleRepository


async def get_recurring_rules(user_id: UUID, rules: RecurringRuleRepository) -> Sequence[RecurringRuleRecord]:
    """Los vigentes, cada uno en la moneda de su cuenta; el que vence primero arriba."""
    return await rules.list(user_id)
