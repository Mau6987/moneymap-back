"""Caso de uso de escritura: omitir una vez de un recurrente (spec 003, RF-22)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import RecurringRuleRecord
from app.modules.finance.domain.ports import RecurringRuleRepository


async def skip_recurring_occurrence(
    user_id: UUID, rule_id: UUID, rules: RecurringRuleRepository
) -> RecurringRuleRecord:
    """Pasa al vencimiento siguiente sin registrar un movimiento.

    Para lo que se pagó por fuera de la app: esa vez deja de contar como por
    pagar. El que no existe, está dado de baja o es de otro: 404.
    """
    record = await rules.skip_occurrence(user_id, rule_id)
    if record is None:
        raise NotFound("El recurrente no existe o ya no vence")
    return record
