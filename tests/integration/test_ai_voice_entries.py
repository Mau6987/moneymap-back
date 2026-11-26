"""Los endpoints del registro por voz contra PostgreSQL 16 (spec 012, RF-1 a RF-3, RF-8 y RF-9).

La cola se reemplaza por una lista: lo que hace el worker está en test_ai_voice_worker.py.
"""

from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import app
from app.modules.ai.deps import get_voice_queue
from app.modules.ai.domain.voice import VoiceEntry

# Desde la migración 0023 el plan gratuito no dicta: estas pruebas lo prenden.
pytestmark = pytest.mark.usefixtures("allow_voice")

CASH_ACCOUNT = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "2500.00"}


class ListQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[UUID, bytes | None]] = []

    def enqueue(self, user_id: UUID, entry: VoiceEntry, audio: bytes | None) -> None:
        self.sent.append((entry.id, audio))


@pytest.fixture
async def queue(client: AsyncClient) -> AsyncIterator[ListQueue]:
    fake = ListQueue()
    app.dependency_overrides[get_voice_queue] = lambda: fake
    yield fake


async def test_el_audio_se_encola_y_responde_202_rf1(client: AsyncClient, queue: ListQueue) -> None:
    response = await client.post("/v1/voice-entries", content=b"audio-m4a", headers={"Content-Type": "audio/mp4"})

    body = response.json()
    assert response.status_code == 202
    assert (body["status"], body["input_type"], body["transcript"], body["extraction"]) == (
        "received",
        "voice",
        None,
        None,
    )
    assert queue.sent == [(UUID(body["id"]), b"audio-m4a")]
    assert (await client.get(f"/v1/voice-entries/{body['id']}")).json() == body


async def test_la_frase_escrita_va_sin_audio_rf2(client: AsyncClient, queue: ListQueue) -> None:
    response = await client.post("/v1/voice-entries/text", json={"text": "gasté 50 en almuerzo"})

    body = response.json()
    assert (response.status_code, body["input_type"], body["transcript"]) == (202, "text", "gasté 50 en almuerzo")
    assert queue.sent == [(UUID(body["id"]), None)]


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(b"audio", "application/json"), (b"", "audio/mp4"), (b"x" * (2 * 1024 * 1024 + 1), "audio/mp4")],
    ids=["no_es_audio", "vacio", "muy_grande"],
)
async def test_rechaza_lo_que_no_es_audio_rf1(
    client: AsyncClient, queue: ListQueue, content: bytes, content_type: str
) -> None:
    response = await client.post("/v1/voice-entries", content=content, headers={"Content-Type": content_type})

    assert (response.status_code, response.json()["code"]) == (422, "invalid_audio")
    assert queue.sent == []


async def test_sin_cuota_responde_plan_limit_y_no_encola_rf3(
    client: AsyncClient, queue: ListQueue, user_id: UUID, owner_connection: AsyncConnection
) -> None:
    await owner_connection.execute(
        text(
            "INSERT INTO billing.usage_counters (user_id, feature_key, period_start, used)"
            " VALUES (:user_id, 'ai.voice_entries', date_trunc('month', now())::date, 30)"
        ),
        {"user_id": user_id},
    )
    await owner_connection.commit()

    response = await client.post("/v1/voice-entries/text", json={"text": "gasté 50"})

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["feature"]) == ("plan_limit", "ai.voice_entries")
    assert queue.sent == []


async def test_lo_de_otro_o_inexistente_responde_404_rf8(client: AsyncClient) -> None:
    assert (await client.get(f"/v1/voice-entries/{uuid4()}")).status_code == 404


async def test_confirmar_enlaza_el_movimiento_y_descartar_lo_cierra_rf9(
    client: AsyncClient, queue: ListQueue, owner_connection: AsyncConnection
) -> None:
    entry_id = (await client.post("/v1/voice-entries/text", json={"text": "gasté 50"})).json()["id"]
    await owner_connection.execute(
        text("UPDATE ai.voice_entries SET status = 'extracted' WHERE id = :id"), {"id": entry_id}
    )
    await owner_connection.commit()
    account = (await client.post("/v1/accounts", json=CASH_ACCOUNT)).json()
    category = next(c for c in (await client.get("/v1/categories")).json() if c["type"] == "expense")
    transaction = await client.post(
        "/v1/transactions",
        json={
            "kind": "expense",
            "account_id": account["id"],
            "category_id": category["id"],
            "amount": "50.00",
            "occurred_on": date.today().isoformat(),
            "description": "Almuerzo",
            "source": "voice",
        },
    )

    wrong = await client.post(f"/v1/voice-entries/{entry_id}/confirm", json={"transaction_id": str(uuid4())})
    confirmed = await client.post(
        f"/v1/voice-entries/{entry_id}/confirm", json={"transaction_id": transaction.json()["id"]}
    )
    late = await client.post(f"/v1/voice-entries/{entry_id}/discard")

    assert (wrong.status_code, wrong.json()["code"]) == (422, "validation_error")
    assert (confirmed.json()["status"], confirmed.json()["transaction_id"]) == ("confirmed", transaction.json()["id"])
    assert late.status_code == 409


async def test_cancelar_un_dictado_pendiente_lo_descarta_bug047(
    client: AsyncClient, queue: ListQueue, owner_connection: AsyncConnection
) -> None:
    entry_id = (await client.post("/v1/voice-entries/text", json={"text": "gasté 50"})).json()["id"]

    cancelled = await client.post(f"/v1/voice-entries/{entry_id}/discard")

    assert (cancelled.status_code, cancelled.json()["status"]) == (200, "discarded")
    # El worker termina después y ya no lo pisa.
    await owner_connection.execute(
        text(
            "UPDATE ai.voice_entries SET status = 'extracted' WHERE id = :id AND status IN ('received', 'transcribed')"
        ),
        {"id": entry_id},
    )
    await owner_connection.commit()
    assert (await client.get(f"/v1/voice-entries/{entry_id}")).json()["status"] == "discarded"


async def test_el_plan_gratuito_no_dicta(
    client: AsyncClient, allow_voice: None, owner_connection: AsyncConnection
) -> None:
    """Desde la 0023 el gratuito no incluye la voz: sin el fixture, 409 plan_limit."""
    await owner_connection.execute(
        text(
            "UPDATE billing.plan_features SET is_enabled = false, limit_value = 0"
            " WHERE feature_key = 'ai.voice_entries' AND plan_id = (SELECT id FROM billing.plans WHERE code = 'free')"
        )
    )
    await owner_connection.commit()

    response = await client.post("/v1/voice-entries/text", json={"text": "gasté 50"})

    assert (response.status_code, response.json()["code"]) == (409, "plan_limit")
