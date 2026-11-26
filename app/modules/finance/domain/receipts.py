"""La foto del comprobante de un gasto (spec 014): modelo, puertos y tipo de imagen."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

MAX_RECEIPT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Receipt:
    content: bytes
    content_type: str


def image_type(data: bytes) -> str | None:
    """El tipo real por los primeros bytes, no por lo que dice el cliente (RF-2)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def object_key(user_id: UUID, transaction_id: UUID) -> str:
    """Una por gasto: subir otra pisa la anterior."""
    return f"{user_id}/{transaction_id}"


def recurring_object_key(user_id: UUID, rule_id: UUID) -> str:
    """Una por gasto fijo: subir otra pisa la anterior."""
    return f"recurring/{user_id}/{rule_id}"


class ReceiptRepository(Protocol):
    """Qué gasto tiene foto y dónde está (`finance.transaction_receipts`)."""

    async def save(self, user_id: UUID, transaction_id: UUID, key: str, content_type: str, size: int) -> bool:
        """Guarda o reemplaza. False si el gasto no existe, está borrado, es de otro o no es un gasto."""
        ...

    async def find(self, user_id: UUID, transaction_id: UUID) -> tuple[str, str] | None:
        """La clave y el tipo, o None si no tiene foto."""
        ...

    async def remove(self, user_id: UUID, transaction_id: UUID) -> str | None:
        """Borra la fila y devuelve la clave, o None si no tenía foto."""
        ...


class ReceiptStorage(Protocol):
    """Donde viven las imágenes (el S3 propio)."""

    async def put(self, key: str, receipt: Receipt) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class RecurringReceiptRepository(Protocol):
    """Qué gasto fijo tiene foto y dónde está (`finance.recurring_rule_receipts`)."""

    async def save(self, user_id: UUID, rule_id: UUID, key: str, content_type: str, size: int) -> bool:
        """Guarda o reemplaza. False si el gasto fijo no existe o está borrado."""
        ...

    async def find(self, user_id: UUID, rule_id: UUID) -> tuple[str, str] | None:
        """La clave y el tipo, o None si no tiene foto."""
        ...

    async def remove(self, user_id: UUID, rule_id: UUID) -> str | None:
        """Borra la fila y devuelve la clave, o None si no tenía foto."""
        ...
