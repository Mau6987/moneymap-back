"""Caso de uso de escritura: marcar un recurrente como pagado (spec 003, RF-17 a RF-19)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import RecurringPayment, RecurringPaymentRecord
from app.modules.finance.domain.ports import RecurringRuleRepository


async def register_recurring_payment(
    payment: RecurringPayment, rule_id: UUID, user_id: UUID, rules: RecurringRuleRepository
) -> RecurringPaymentRecord:
    """Registra el movimiento y pasa el recurrente a su vencimiento siguiente.

    Los decimales del monto y la moneda los valida la base, como en cualquier
    movimiento. El que no existe, está dado de baja o es de otro: 404.
    """
    registered = await rules.register_payment(user_id, rule_id, payment)
    if registered is None:
        raise NotFound("El recurrente no existe o ya no vence")
    return registered
