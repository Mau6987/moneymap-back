"""Caso de uso de escritura: borrar un movimiento (RF-27)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.ports import TransactionRepository


async def delete_transaction(transaction_id: UUID, user_id: UUID, transactions: TransactionRepository) -> None:
    """Borrado lógico: el movimiento deja de contar y la base devuelve el saldo a sus cuentas."""
    if not await transactions.soft_delete(transaction_id, user_id):
        raise NotFound("El movimiento no existe")
