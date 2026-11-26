"""El worker de voz contra PostgreSQL 16, con stt y Ollama simulados (spec 012, RF-4 a RF-7)."""

import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import user_session
from app.workers.voice import Entry, fail_stale_voice_entries, process_voice_entry

# Desde la migración 0023 el plan gratuito no dicta: estas pruebas lo prenden.
pytestmark = pytest.mark.usefixtures("allow_voice")

Handler = Callable[[httpx.Request], httpx.Response]


async def _new_entry(user_id: UUID, transcript: str | None = None) -> Entry:
    """Como la API: con RLS, descontando la cuota del mes."""
    async with user_session(user_id) as session:
        await session.execute(text("SELECT billing.try_consume(:user_id, 'ai.voice_entries')"), {"user_id": user_id})
        row = (
            await session.execute(
                text(
                    "INSERT INTO ai.voice_entries (user_id, input_type, transcript)"
                    " VALUES (:user_id, :input_type, :transcript) RETURNING id, created_at"
                ),
                {"user_id": user_id, "input_type": "voice" if transcript is None else "text", "transcript": transcript},
            )
        ).one()
    return Entry(row.id, row.created_at, user_id)


def _models(stt_fails: set[str], llm_fails: set[str]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/transcribe":
            if request.url.params["model"] in stt_fails:
                return httpx.Response(500)
            return httpx.Response(200, json={"text": "gasté 50 en almuerzo", "audio_seconds": 3.5})
        body = json.loads(request.content)
        # Un contexto chico deja lugar para todas las capas en una GPU de 4 GB.
        assert body["options"]["num_ctx"] == 4096
        if body["model"] in llm_fails:
            return httpx.Response(200, json={"message": {"content": "no es json"}})
        data = json.loads(body["messages"][1]["content"])
        answer = {
            "kind": "expense",
            "amount": "50",
            "currency": "BOB",
            "category": data["categorias_gasto"][0],
            # Sin onboarding no tiene cuentas: la app la pide al confirmar.
            "account": data["cuentas"][0]["nombre"] if data["cuentas"] else None,
            "description": "Almuerzo",
            "occurred_on": None,
        }
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"movements": [answer]})},
                "prompt_eval_count": 800,
                "eval_count": 60,
            },
        )

    return handle


async def _entry_row(owner_connection: AsyncConnection, entry: Entry) -> dict[str, object]:
    row = await owner_connection.execute(
        text("SELECT * FROM ai.voice_entries WHERE created_at = :created_at AND id = :id"),
        {"created_at": entry.created_at, "id": entry.id},
    )
    return dict(row.mappings().one())


async def _quota_used(owner_connection: AsyncConnection, user_id: UUID) -> int:
    used = await owner_connection.execute(
        text("SELECT used FROM billing.usage_counters WHERE user_id = :user_id AND feature_key = 'ai.voice_entries'"),
        {"user_id": user_id},
    )
    return int(used.scalar_one())


async def test_si_el_principal_falla_responde_el_respaldo_rf4_rf5(
    user_id: UUID, owner_connection: AsyncConnection
) -> None:
    entry = await _new_entry(user_id)
    handler = _models(stt_fails={"parakeet"}, llm_fails={"qwen3.5:4b"})

    status = await process_voice_entry(entry, b"audio", httpx.MockTransport(handler))

    row = await _entry_row(owner_connection, entry)
    assert status == row["status"] == "extracted"
    assert row["transcript"] == "gasté 50 en almuerzo"
    assert (row["stt_model_code"], row["llm_model_code"]) == ("local.whisper-large-v3-turbo", "ollama.gemma3-4b")
    # Cada modelo con su reintento: 2 fallas + 1 acierto en cada paso.
    assert (row["attempts"], row["fallback_used"], row["cost_usd"]) == (6, True, 0)
    extraction = row["extraction"]
    assert isinstance(extraction, dict)
    assert (extraction["amount"], extraction["description"], extraction["missing"]) == (
        "50",
        "Almuerzo",
        ["account_id"],
    )
    assert await _quota_used(owner_connection, user_id) == 1


async def test_la_frase_escrita_no_pasa_por_voz_a_texto_rf2(user_id: UUID, owner_connection: AsyncConnection) -> None:
    entry = await _new_entry(user_id, transcript="pagué 50 de almuerzo")
    requests: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return _models(set(), set())(request)

    status = await process_voice_entry(entry, None, httpx.MockTransport(spy))

    row = await _entry_row(owner_connection, entry)
    assert (status, row["attempts"], row["stt_model_code"]) == ("extracted", 1, None)
    assert requests == ["/api/chat"]


async def test_si_fallan_todos_queda_failed_y_devuelve_la_cuota_rf7(
    user_id: UUID, owner_connection: AsyncConnection
) -> None:
    entry = await _new_entry(user_id)
    started = datetime.now().astimezone()

    status = await process_voice_entry(entry, b"audio", httpx.MockTransport(lambda _: httpx.Response(503)))

    row = await _entry_row(owner_connection, entry)
    assert (status, row["status"], row["error"]) == ("failed", "failed", "voice.transcribe")
    assert await _quota_used(owner_connection, user_id) == 0
    logged = await owner_connection.execute(
        text(
            "SELECT count(*) FROM ops.logs"
            " WHERE user_id = :user_id AND event_code = 'voice.failed' AND occurred_at >= :since"
        ),
        {"user_id": user_id, "since": started},
    )
    assert logged.scalar_one() == 1


async def test_si_se_perdio_el_audio_queda_failed_sin_llamar_a_los_modelos_rf10(
    user_id: UUID, owner_connection: AsyncConnection
) -> None:
    """El tmpfs del audio no sobrevive a un reinicio: el dictado no puede quedar colgado."""
    entry = await _new_entry(user_id)
    requests: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(500)

    status = await process_voice_entry(entry, None, httpx.MockTransport(spy))

    row = await _entry_row(owner_connection, entry)
    assert (status, row["error"], requests) == ("failed", "voice.transcribe", [])
    assert await _quota_used(owner_connection, user_id) == 0


async def test_un_error_inesperado_marca_failed_y_devuelve_la_cuota(
    user_id: UUID, owner_connection: AsyncConnection
) -> None:
    """Un fallo no previsto no puede dejar la entrada en `received` para siempre."""
    entry = await _new_entry(user_id)

    def boom(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await process_voice_entry(entry, b"audio", httpx.MockTransport(boom))

    row = await _entry_row(owner_connection, entry)
    assert (row["status"], row["error"]) == ("failed", "voice.unexpected")
    assert await _quota_used(owner_connection, user_id) == 0


async def test_el_reaper_cierra_los_dictados_viejos(user_id: UUID, owner_connection: AsyncConnection) -> None:
    """Un worker muerto no puede dejar una entrada pendiente para siempre."""
    stale = await _new_entry(user_id)
    fresh = await _new_entry(user_id)
    moved = (
        await owner_connection.execute(
            text(
                "UPDATE ai.voice_entries SET created_at = now() - interval '20 minutes'"
                " WHERE created_at = :created_at AND id = :id"
                " RETURNING created_at"
            ),
            {"created_at": stale.created_at, "id": stale.id},
        )
    ).scalar_one()
    await owner_connection.commit()
    stale_moved = Entry(stale.id, moved, stale.user_id)

    closed = await fail_stale_voice_entries()

    stale_row = await _entry_row(owner_connection, stale_moved)
    fresh_row = await _entry_row(owner_connection, fresh)
    assert closed >= 1
    assert (stale_row["status"], stale_row["error"]) == ("failed", "voice.stale")
    assert fresh_row["status"] == "received"
    # El viejo devolvió su cuota; el nuevo sigue consumiendo la suya.
    assert await _quota_used(owner_connection, user_id) == 1
