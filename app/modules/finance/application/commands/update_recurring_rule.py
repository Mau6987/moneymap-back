"""Caso de uso de escritura: corregir un recurrente (RF-30)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import RecurringRuleChanges, RecurringRuleRecord
from app.modules.finance.domain.ports import RecurringRuleRepository


async def update_recurring_rule(
    changes: RecurringRuleChanges,
    rule_id: UUID,
    user_id: UUID,
    rules: RecurringRuleRepository,
) -> RecurringRuleRecord:
    """Corrige cuenta, categoría, monto, descripción o frecuencia.

    Una cuenta de otra moneda la rechaza la base con 422 `currency_mismatch`
    (spec 002, RF-21).
    """
    updated = await rules.update(user_id, rule_id, changes)
    if updated is None:
        raise NotFound("El recurrente, la cuenta o la categoría no existen")
    return updated
