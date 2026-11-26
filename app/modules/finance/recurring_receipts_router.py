"""La foto del comprobante de un gasto fijo (spec 014 + recurrentes): solo HTTP, sin SQL ni reglas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.dependencies import get_current_user_id
from app.modules.finance.application.commands.receipts import attach_recurring_receipt, remove_recurring_receipt
from app.modules.finance.application.queries.get_receipt import get_recurring_receipt
from app.modules.finance.deps import get_receipt_storage, get_recurring_receipt_repository
from app.modules.finance.domain.errors import InvalidReceipt
from app.modules.finance.domain.receipts import MAX_RECEIPT_BYTES, ReceiptStorage, RecurringReceiptRepository

router = APIRouter(prefix="/recurring-rules/{rule_id}/receipt")

User = Annotated[UUID, Depends(get_current_user_id)]
Receipts = Annotated[RecurringReceiptRepository, Depends(get_recurring_receipt_repository)]
Storage = Annotated[ReceiptStorage, Depends(get_receipt_storage)]

_IMAGE_BODY = {
    "requestBody": {
        "required": True,
        "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
        "description": "La foto cruda: JPEG, PNG o WebP, hasta 5 MB",
    }
}


@router.put(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Adjunta la foto del comprobante a un gasto fijo",
    openapi_extra=_IMAGE_BODY,
)
async def attach_recurring_receipt_route(
    rule_id: UUID, request: Request, user_id: User, receipts: Receipts, storage: Storage
) -> None:
    """Uno por gasto fijo; subir otro lo reemplaza."""
    if int(request.headers.get("content-length") or 0) > MAX_RECEIPT_BYTES:
        raise InvalidReceipt()
    await attach_recurring_receipt(user_id, rule_id, await request.body(), receipts, storage)


@router.get(
    "",
    response_class=Response,
    summary="La foto del comprobante del gasto fijo",
    responses={200: {"content": {"image/*": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def get_recurring_receipt_route(
    rule_id: UUID, user_id: User, receipts: Receipts, storage: Storage
) -> Response:
    """La imagen tal cual, sin guardarse en cachés compartidas."""
    receipt = await get_recurring_receipt(user_id, rule_id, receipts, storage)
    return Response(receipt.content, media_type=receipt.content_type, headers={"Cache-Control": "private, no-store"})


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Quita la foto del comprobante del gasto fijo")
async def remove_recurring_receipt_route(
    rule_id: UUID, user_id: User, receipts: Receipts, storage: Storage
) -> None:
    await remove_recurring_receipt(user_id, rule_id, receipts, storage)

