"""Caso de uso de lectura: la foto del comprobante de un gasto (spec 014, RF-3)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.receipts import (
    Receipt,
    ReceiptRepository,
    ReceiptStorage,
    RecurringReceiptRepository,
)


async def get_receipt(
    user_id: UUID, transaction_id: UUID, receipts: ReceiptRepository, storage: ReceiptStorage
) -> Receipt:
    found = await receipts.find(user_id, transaction_id)
    if found is None:
        raise NotFound("El gasto no tiene comprobante")
    key, content_type = found
    return Receipt(await storage.get(key), content_type)


async def get_recurring_receipt(
    user_id: UUID, rule_id: UUID, receipts: RecurringReceiptRepository, storage: ReceiptStorage
) -> Receipt:
    found = await receipts.find(user_id, rule_id)
    if found is None:
        raise NotFound("El gasto fijo no tiene comprobante")
    key, content_type = found
    return Receipt(await storage.get(key), content_type)
