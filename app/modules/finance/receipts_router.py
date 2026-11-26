"""La foto del comprobante de un gasto (spec 014): solo HTTP, sin SQL ni reglas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.dependencies import get_current_user_id
from app.modules.finance.application.commands.receipts import attach_receipt, remove_receipt
from app.modules.finance.application.queries.get_receipt import get_receipt
from app.modules.finance.deps import get_receipt_repository, get_receipt_storage
from app.modules.finance.domain.errors import InvalidReceipt
from app.modules.finance.domain.receipts import MAX_RECEIPT_BYTES, ReceiptRepository, ReceiptStorage

router = APIRouter(prefix="/transactions/{transaction_id}/receipt")

User = Annotated[UUID, Depends(get_current_user_id)]
Receipts = Annotated[ReceiptRepository, Depends(get_receipt_repository)]
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
    summary="Adjunta la foto del comprobante",
    openapi_extra=_IMAGE_BODY,
)
async def attach_receipt_route(
    transaction_id: UUID, request: Request, user_id: User, receipts: Receipts, storage: Storage
) -> None:
    """RF-1 y RF-2: uno por gasto; subir otro lo reemplaza."""
    if int(request.headers.get("content-length") or 0) > MAX_RECEIPT_BYTES:
        raise InvalidReceipt()
    await attach_receipt(user_id, transaction_id, await request.body(), receipts, storage)


@router.get(
    "",
    response_class=Response,
    summary="La foto del comprobante",
    responses={200: {"content": {"image/*": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def get_receipt_route(transaction_id: UUID, user_id: User, receipts: Receipts, storage: Storage) -> Response:
    """RF-3: la imagen tal cual, sin guardarse en cachés compartidas."""
    receipt = await get_receipt(user_id, transaction_id, receipts, storage)
    return Response(receipt.content, media_type=receipt.content_type, headers={"Cache-Control": "private, no-store"})


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Quita la foto del comprobante")
async def remove_receipt_route(transaction_id: UUID, user_id: User, receipts: Receipts, storage: Storage) -> None:
    """RF-4."""
    await remove_receipt(user_id, transaction_id, receipts, storage)
