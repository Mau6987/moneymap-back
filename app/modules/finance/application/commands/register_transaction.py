"""Caso de uso de escritura: registrar un movimiento (RF-6 a RF-8, RF-10 a RF-12)."""

from uuid import UUID

from app.modules.finance.domain.models import NewTransaction, TransactionRecord
from app.modules.finance.domain.ports import TransactionRepository


async def register_transaction(
    transaction: NewTransaction,
    user_id: UUID,
    transactions: TransactionRepository,
) -> TransactionRecord:
    """Guarda el gasto, el ingreso o la transferencia.

    No valida la moneda, ni los decimales del monto, ni la cuenta de destino: lo
    aplica la base (constitución §3) y `core/errors.py` traduce el error. Tampoco
    mueve los saldos: los ajustan los triggers en la misma transacción.
    """
    return await transactions.insert(transaction, user_id)
