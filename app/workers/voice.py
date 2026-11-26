"""Procesa un dictado: voz a texto y frase a movimiento (spec 012, RF-4 a RF-7).

Cada paso prueba los modelos de `ai.route()` en orden: el principal y, si no
responde a tiempo, falla o devuelve algo inválido, el respaldo. Cada intento
queda en `ai.calls`, que suma el dictado y el uso del mes. Si fallan todos, el
dictado queda en `failed`, se devuelve la cuota y se anota en `ops.log`.

Corre con `moneymap_worker_login`: la API no puede leer las rutas ni escribir
`ai.calls`. Por eso cada consulta filtra por el usuario a mano. El audio no
viaja en la cola: se lee de la carpeta en memoria que comparte con la API y se
borra al leerlo (RF-10, `app/modules/ai/infrastructure/audio.py`).
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.modules.ai.domain.extraction import PROMPT_VERSION, Account, Category, Context, InvalidOutput
from app.modules.ai.infrastructure import audio as audio_store
from app.modules.ai.infrastructure.models import Extracted, Route, Transcript, UnsupportedProvider, extract, transcribe
from app.workers import celery

_SELECT_ROUTE = text("SELECT pos, model_code, provider, model, timeout_ms, max_retries FROM ai.route(:task)")
_INSERT_CALL = text(
    """
    INSERT INTO ai.calls (task, model_code, route_position, attempt, status, user_id, voice_entry_id,
                          voice_entry_created_at, latency_ms, audio_seconds, input_tokens, output_tokens)
    VALUES (:task, :model_code, :position, :attempt, :status, :user_id, :entry_id,
            :entry_created_at, :latency_ms, :audio_seconds, :input_tokens, :output_tokens)
    """
)
_SELECT_TRANSCRIPT = text(
    "SELECT transcript FROM ai.voice_entries"
    " WHERE created_at = :entry_created_at AND id = :entry_id AND user_id = :user_id"
)
_SAVE_TRANSCRIPT = text(
    "UPDATE ai.voice_entries SET transcript = :transcript, audio_seconds = :audio_seconds, status = 'transcribed'"
    " WHERE created_at = :entry_created_at AND id = :entry_id AND user_id = :user_id"
    " AND status = 'received'"  # uno descartado mientras se procesaba queda descartado (BUG-047)
)
_SAVE_EXTRACTION = text(
    "UPDATE ai.voice_entries SET extraction = CAST(:extraction AS jsonb), prompt_version = :prompt_version,"
    " status = 'extracted', latency_ms = :latency_ms"
    " WHERE created_at = :entry_created_at AND id = :entry_id AND user_id = :user_id"
    " AND status IN ('received', 'transcribed')"
)
_SAVE_FAILURE = text(
    "UPDATE ai.voice_entries SET status = 'failed', error = :error, latency_ms = :latency_ms"
    " WHERE created_at = :entry_created_at AND id = :entry_id AND user_id = :user_id"
    " AND status IN ('received', 'transcribed')"
    " RETURNING user_id"
)
_SELECT_STALE = text(
    "SELECT id, created_at, user_id FROM ai.voice_entries"
    " WHERE status IN ('received', 'transcribed')"
    " AND created_at < now() - interval '15 minutes'"
    " ORDER BY created_at LIMIT 500"
)
_RELEASE_QUOTA = text("SELECT billing.release(:user_id, 'ai.voice_entries')")
_LOG_FAILURE = text(
    """
    SELECT ops.log(
        p_level => 'error',
        p_category => 'ai',
        p_event_code => 'voice.failed',
        p_message => 'Fallaron todos los modelos de un paso del dictado',
        p_context => CAST(:context AS jsonb),
        p_service => 'worker',
        p_user_id => :user_id
    )
    """
)
_SELECT_TODAY = text("SELECT (now() AT TIME ZONE timezone)::date FROM iam.users WHERE id = :user_id")
_SELECT_CATEGORIES = text(
    "SELECT id, name, kind FROM finance.categories WHERE user_id = :user_id AND deleted_at IS NULL"
    " ORDER BY kind, sort_order, name"
)
_SELECT_ACCOUNTS = text(
    "SELECT id, name, currency, type FROM finance.accounts"
    " WHERE user_id = :user_id AND archived_at IS NULL AND deleted_at IS NULL ORDER BY is_default DESC, name"
)
_SELECT_CURRENCIES = text("SELECT currency FROM finance.user_currencies WHERE user_id = :user_id ORDER BY sort_order")


@dataclass(frozen=True, slots=True)
class Entry:
    id: UUID
    created_at: datetime
    user_id: UUID

    @property
    def params(self) -> dict[str, Any]:
        return {"entry_id": self.id, "entry_created_at": self.created_at, "user_id": self.user_id}


@dataclass(frozen=True, slots=True)
class Usage:
    audio_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


async def _with_fallback[T](
    engine: AsyncEngine, task: str, entry: Entry, call: Callable[[Route], Awaitable[tuple[T, Usage]]]
) -> T | None:
    """Prueba cada modelo de la ruta, con sus reintentos, hasta que uno responde bien."""
    async with engine.connect() as connection:
        rows = (await connection.execute(_SELECT_ROUTE, {"task": task})).all()
    for route in (Route(*row) for row in rows):
        for attempt in range(1, route.max_retries + 2):
            started = time.monotonic()
            result: T | None = None
            usage = Usage()
            try:
                result, usage = await call(route)
                status = "ok"
            except httpx.TimeoutException:
                status = "timeout"
            except InvalidOutput:
                status = "invalid_output"
            except httpx.HTTPStatusError as error:
                status = "rate_limited" if error.response.status_code == 429 else "error"
            except (httpx.HTTPError, UnsupportedProvider, KeyError, ValueError):
                status = "error"
            async with engine.begin() as connection:
                await connection.execute(
                    _INSERT_CALL,
                    {
                        **entry.params,
                        "task": task,
                        "model_code": route.model_code,
                        "position": route.position,
                        "attempt": attempt,
                        "status": status,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "audio_seconds": usage.audio_seconds,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                    },
                )
            if status == "ok":
                return result
    return None


async def process_voice_entry(
    entry: Entry, audio: bytes | None, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Devuelve el estado final del dictado: `extracted` o `failed`. Las pruebas pasan `transport`."""
    started = time.monotonic()
    engine = create_async_engine(get_settings().worker_database_url, poolclass=NullPool)
    try:
        async with httpx.AsyncClient(transport=transport) as client:
            phrase = await _phrase(engine, client, entry, audio)
            if phrase is None:
                return await _fail(engine, entry, "voice.transcribe", started)
            context = await _context(engine, entry.user_id)

            async def run_extract(route: Route) -> tuple[Extracted, Usage]:
                extracted = await extract(client, route, phrase, context)
                return extracted, Usage(input_tokens=extracted.input_tokens, output_tokens=extracted.output_tokens)

            extracted = await _with_fallback(engine, "voice.extract", entry, run_extract)
            if extracted is None:
                return await _fail(engine, entry, "voice.extract", started)
            async with engine.begin() as connection:
                await connection.execute(
                    _SAVE_EXTRACTION,
                    {
                        **entry.params,
                        "extraction": json.dumps(extracted.extraction.to_json()),
                        "prompt_version": PROMPT_VERSION,
                        "latency_ms": _elapsed_ms(started),
                    },
                )
            return "extracted"
    except Exception:
        # A crash in the worker must not leave the entry "received" forever.
        # Best effort: if even this fails, the stale reaper will close it.
        try:
            await _fail(engine, entry, "voice.unexpected", started)
        except Exception:  # noqa: BLE001, S110 - the original error is what matters
            pass
        raise
    finally:
        await engine.dispose()


async def _phrase(engine: AsyncEngine, client: httpx.AsyncClient, entry: Entry, audio: bytes | None) -> str | None:
    """La frase escrita (RF-2) ya está guardada; la dictada se transcribe.

    Un dictado sin audio ni frase perdió el audio (se reinició el contenedor): falla.
    """
    if audio is None:
        async with engine.connect() as connection:
            written = (await connection.execute(_SELECT_TRANSCRIPT, entry.params)).scalar_one()
        return None if written is None else str(written)

    async def run_transcribe(route: Route) -> tuple[Transcript, Usage]:
        transcript = await transcribe(client, route, audio)
        return transcript, Usage(audio_seconds=transcript.audio_seconds)

    transcript = await _with_fallback(engine, "voice.transcribe", entry, run_transcribe)
    if transcript is None:
        return None
    async with engine.begin() as connection:
        await connection.execute(
            _SAVE_TRANSCRIPT,
            {**entry.params, "transcript": transcript.text, "audio_seconds": transcript.audio_seconds},
        )
    return transcript.text


async def _context(engine: AsyncEngine, user_id: UUID) -> Context:
    params = {"user_id": user_id}
    async with engine.connect() as connection:
        today = (await connection.execute(_SELECT_TODAY, params)).scalar_one()
        categories = [Category(str(r.id), r.name, r.kind) for r in await connection.execute(_SELECT_CATEGORIES, params)]
        accounts = [
            Account(str(r.id), r.name, r.currency, r.type) for r in await connection.execute(_SELECT_ACCOUNTS, params)
        ]
        currencies = list((await connection.execute(_SELECT_CURRENCIES, params)).scalars())
    return Context(today, categories, accounts, currencies)


async def _fail(engine: AsyncEngine, entry: Entry, task: str, started: float) -> str:
    """RF-7: el dictado no se pierde en silencio y no descuenta la cuota."""
    async with engine.begin() as connection:
        updated = (
            await connection.execute(_SAVE_FAILURE, {**entry.params, "error": task, "latency_ms": _elapsed_ms(started)})
        ).first()
        if updated is None:
            # Another worker already finished it (or it was processed just
            # before the reaper): do not release the quota twice.
            return "failed"
        await connection.execute(_RELEASE_QUOTA, {"user_id": entry.user_id})
        context = {"task": task, "voice_entry_id": str(entry.id)}
        await connection.execute(_LOG_FAILURE, {"user_id": entry.user_id, "context": json.dumps(context)})
    return "failed"


async def fail_stale_voice_entries() -> int:
    """Cierra dictados que un worker muerto dejó en received/transcribed."""
    engine = create_async_engine(get_settings().worker_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(_SELECT_STALE)).all()
        for row in rows:
            await _fail(engine, Entry(row.id, row.created_at, row.user_id), "voice.stale", time.monotonic())
        return len(rows)
    finally:
        await engine.dispose()


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


@celery.task(name="ai.process_voice_entry", soft_time_limit=180, time_limit=200)  # type: ignore[untyped-decorator]
def process_voice_entry_task(entry_id: str, created_at: str, user_id: str) -> str:
    """La API encola solo los ids; el audio, si es un dictado, lo dejó en `audio.put`."""
    entry = Entry(UUID(entry_id), datetime.fromisoformat(created_at), UUID(user_id))
    return asyncio.run(process_voice_entry(entry, audio_store.take(entry.id)))


@celery.task(name="ai.fail_stale_voice_entries")  # type: ignore[untyped-decorator]
def fail_stale_voice_entries_task() -> int:
    """Cierra dictados que quedaron pendientes porque un worker murió."""
    return asyncio.run(fail_stale_voice_entries())
