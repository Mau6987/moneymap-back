"""Caso de uso de escritura: corregir un movimiento (RF-13)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.models import TransactionChanges, TransactionRecord
from app.modules.finance.domain.ports import TransactionRepository


async def update_transaction(
    changes: TransactionChanges,
    transaction_id: UUID,
    user_id: UUID,
    transactions: TransactionRepository,
) -> TransactionRecord:
    """Corrige cuenta, categoría, monto, fecha, descripción o cuenta de destino.

    Si la cuenta nueva es de otra moneda, la base responde 422 `currency_mismatch`
    y el movimiento queda como estaba (RF-13).
    """
    updated = await transactions.update(transaction_id, user_id, changes)
    if updated is None:
        raise NotFound("El movimiento no existe")
    return updated
