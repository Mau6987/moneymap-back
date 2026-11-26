"""Casos de uso de escritura: adjuntar y quitar la foto del comprobante (spec 014)."""

from uuid import UUID

from app.core.errors import NotFound
from app.modules.finance.domain.errors import InvalidReceipt
from app.modules.finance.domain.receipts import (
    MAX_RECEIPT_BYTES,
    Receipt,
    ReceiptRepository,
    ReceiptStorage,
    RecurringReceiptRepository,
    image_type,
    object_key,
    recurring_object_key,
)


async def attach_receipt(
    user_id: UUID, transaction_id: UUID, data: bytes, receipts: ReceiptRepository, storage: ReceiptStorage
) -> None:
    """RF-1 y RF-2: guarda la fila y después la imagen; si el S3 falla, la fila vuelve atrás con la transacción."""
    content_type = image_type(data)
    if content_type is None or not 0 < len(data) <= MAX_RECEIPT_BYTES:
        raise InvalidReceipt()
    key = object_key(user_id, transaction_id)
    if not await receipts.save(user_id, transaction_id, key, content_type, len(data)):
        raise NotFound("El gasto no existe")
    await storage.put(key, Receipt(data, content_type))


async def remove_receipt(
    user_id: UUID, transaction_id: UUID, receipts: ReceiptRepository, storage: ReceiptStorage
) -> None:
    """RF-4: borra la fila y la imagen; sin foto, 404."""
    key = await receipts.remove(user_id, transaction_id)
    if key is None:
        raise NotFound("El gasto no tiene comprobante")
    await storage.delete(key)


async def attach_recurring_receipt(
    user_id: UUID, rule_id: UUID, data: bytes, receipts: RecurringReceiptRepository, storage: ReceiptStorage
) -> None:
    """Adjunta o reemplaza la foto del comprobante de un gasto fijo."""
    content_type = image_type(data)
    if content_type is None or not 0 < len(data) <= MAX_RECEIPT_BYTES:
        raise InvalidReceipt()
    key = recurring_object_key(user_id, rule_id)
    if not await receipts.save(user_id, rule_id, key, content_type, len(data)):
        raise NotFound("El gasto fijo no existe")
    await storage.put(key, Receipt(data, content_type))


async def remove_recurring_receipt(
    user_id: UUID, rule_id: UUID, receipts: RecurringReceiptRepository, storage: ReceiptStorage
) -> None:
    """Quita la foto del comprobante de un gasto fijo; sin foto, 404."""
    key = await receipts.remove(user_id, rule_id)
    if key is None:
        raise NotFound("El gasto fijo no tiene comprobante")
    await storage.delete(key)
