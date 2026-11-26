"""La foto del comprobante de un gasto (spec 014).

RF cubiertos: RF-1 a RF-5. El S3 se cambia por un almacén en memoria: el resto
del camino (router, caso de uso, SQL con RLS) es el real.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.dependencies import get_current_user_id
from app.main import app
from app.modules.finance.deps import get_receipt_storage
from app.modules.finance.domain.receipts import MAX_RECEIPT_BYTES, Receipt

CASH_BOB = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}
JPEG = b"\xff\xd8\xff\xe0" + b"foto" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"foto" * 10


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, Receipt] = {}

    async def put(self, key: str, receipt: Receipt) -> None:
        self.objects[key] = receipt

    async def get(self, key: str) -> bytes:
        return self.objects[key].content

    async def delete(self, key: str) -> None:
        del self.objects[key]


@pytest.fixture
def storage(client: AsyncClient) -> MemoryStorage:
    memory = MemoryStorage()
    app.dependency_overrides[get_receipt_storage] = lambda: memory
    return memory


async def _movement(client: AsyncClient, kind: str = "expense") -> str:
    accounts = (await client.get("/v1/accounts")).json()
    account = accounts[0]["id"] if accounts else (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    categories = (await client.get("/v1/categories")).json()
    category = next(item["id"] for item in categories if item["type"] == kind)
    response = await client.post(
        "/v1/transactions",
        json={
            "kind": kind,
            "account_id": account,
            "category_id": category,
            "amount": "35.50",
            "description": "Café",
            "occurred_on": date.today().isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    movement: str = response.json()["id"]
    return movement


async def _has_receipt(client: AsyncClient, movement: str) -> bool:
    items = (await client.get("/v1/transactions")).json()["items"]
    found: bool = next(item["has_receipt"] for item in items if item["id"] == movement)
    return found


async def test_adjunta_ve_reemplaza_y_quita_el_comprobante_rf1_rf3_rf4_rf5(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    movement = await _movement(client)
    assert await _has_receipt(client, movement) is False

    stored = await client.put(f"/v1/transactions/{movement}/receipt", content=JPEG)
    assert stored.status_code == 204, stored.text
    assert await _has_receipt(client, movement) is True

    shown = await client.get(f"/v1/transactions/{movement}/receipt")
    assert shown.status_code == 200
    assert shown.content == JPEG
    assert shown.headers["content-type"] == "image/jpeg"
    assert shown.headers["cache-control"] == "private, no-store"

    # Otra foto reemplaza la anterior, con su tipo real.
    assert (await client.put(f"/v1/transactions/{movement}/receipt", content=PNG)).status_code == 204
    shown = await client.get(f"/v1/transactions/{movement}/receipt")
    assert (shown.content, shown.headers["content-type"]) == (PNG, "image/png")
    assert len(storage.objects) == 1

    assert (await client.delete(f"/v1/transactions/{movement}/receipt")).status_code == 204
    assert storage.objects == {}
    assert await _has_receipt(client, movement) is False
    assert (await client.get(f"/v1/transactions/{movement}/receipt")).status_code == 404
    assert (await client.delete(f"/v1/transactions/{movement}/receipt")).status_code == 404


async def test_solo_imagenes_de_hasta_5_mb_rf2(client: AsyncClient, storage: MemoryStorage) -> None:
    movement = await _movement(client)

    for body in (b"", b"%PDF-1.7 no es una foto", JPEG[:3] + b"\x00" * MAX_RECEIPT_BYTES):
        response = await client.put(
            f"/v1/transactions/{movement}/receipt", content=body, headers={"Content-Type": "image/jpeg"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_receipt"
    assert storage.objects == {}


async def test_solo_en_gastos_vivos_y_propios_rf1(
    client: AsyncClient,
    storage: MemoryStorage,
    new_financial_user: Callable[[str], Awaitable[UUID]],
) -> None:
    income = await _movement(client, "income")
    assert (await client.put(f"/v1/transactions/{income}/receipt", content=JPEG)).status_code == 404
    assert (await client.put(f"/v1/transactions/{uuid4()}/receipt", content=JPEG)).status_code == 404

    expense = await _movement(client)
    assert (await client.put(f"/v1/transactions/{expense}/receipt", content=JPEG)).status_code == 204

    # Un gasto borrado ya no muestra su foto.
    deleted = await _movement(client)
    assert (await client.put(f"/v1/transactions/{deleted}/receipt", content=JPEG)).status_code == 204
    assert (await client.delete(f"/v1/transactions/{deleted}")).status_code == 204
    assert (await client.get(f"/v1/transactions/{deleted}/receipt")).status_code == 404
    assert (await client.put(f"/v1/transactions/{deleted}/receipt", content=JPEG)).status_code == 404

    # De otro usuario: 404, nunca 403.
    other = await new_financial_user("BOB")
    app.dependency_overrides[get_current_user_id] = lambda: other
    assert (await client.get(f"/v1/transactions/{expense}/receipt")).status_code == 404
    assert (await client.delete(f"/v1/transactions/{expense}/receipt")).status_code == 404
    assert (await client.put(f"/v1/transactions/{expense}/receipt", content=PNG)).status_code == 404
    assert len(storage.objects) == 2
