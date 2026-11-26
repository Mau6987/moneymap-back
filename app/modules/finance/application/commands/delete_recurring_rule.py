"""Caso de uso de escritura: dar de baja un recurrente (RF-31)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.ports import RecurringRuleRepository


async def delete_recurring_rule(rule_id: UUID, user_id: UUID, rules: RecurringRuleRepository) -> None:
    """Borrado lógico: deja de vencer. Los movimientos que ya registró se quedan."""
    if not await rules.soft_delete(user_id, rule_id):
        raise NotFound("El recurrente no existe")
