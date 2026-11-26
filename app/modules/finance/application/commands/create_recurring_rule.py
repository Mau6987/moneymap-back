"""Caso de uso de escritura: un ingreso o gasto recurrente (spec 007, pasos 3 y 4)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import NewRecurringRule, RecurringRuleRecord
from app.modules.finance.domain.ports import RecurringRuleRepository


async def create_recurring_rule(
    rule: NewRecurringRule, user_id: UUID, repository: RecurringRuleRepository
) -> RecurringRuleRecord:
    """Crea el recurrente en la moneda de su cuenta (spec 002, RF-21).

    Si la cuenta o la categoría no son del usuario responde 404, nunca 403.
    """
    created = await repository.insert(user_id, rule)
    if created is None:
        raise NotFound("La cuenta o la categoría no existen")
    return created
