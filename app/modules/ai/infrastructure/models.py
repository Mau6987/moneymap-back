"""Las llamadas a los modelos propios de docker-compose.ai.yml (spec 012).

`local` es el servicio stt (Parakeet y Whisper) y `ollama`, el LLM. El
proveedor y el modelo salen de `ai.route()`: los pagos quedaron sin ruta en la
migración 0014 y acá no tienen adaptador.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.modules.ai.domain.extraction import SCHEMA, Context, Extraction, InvalidOutput, build_messages, parse


class UnsupportedProvider(Exception):
    """Una ruta apunta a un proveedor sin adaptador: se prueba el siguiente."""


@dataclass(frozen=True, slots=True)
class Route:
    position: int
    model_code: str
    provider: str
    model: str
    timeout_ms: int
    max_retries: int


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    audio_seconds: float


@dataclass(frozen=True, slots=True)
class Extracted:
    extraction: Extraction
    input_tokens: int
    output_tokens: int


async def transcribe(client: httpx.AsyncClient, route: Route, audio: bytes) -> Transcript:
    if route.provider != "local":
        raise UnsupportedProvider(route.provider)
    response = await client.post(
        f"{get_settings().stt_base_url}/transcribe",
        params={"model": route.model},
        content=audio,
        timeout=route.timeout_ms / 1000,
    )
    response.raise_for_status()
    body = response.json()
    text = str(body.get("text") or "").strip()
    if not text:
        raise InvalidOutput("transcripción vacía")
    return Transcript(text, float(body["audio_seconds"]))


async def extract(client: httpx.AsyncClient, route: Route, phrase: str, context: Context) -> Extracted:
    if route.provider != "ollama":
        raise UnsupportedProvider(route.provider)
    settings = get_settings()
    payload: dict[str, Any] = {
        "model": route.model,
        "messages": build_messages(phrase, context),
        "format": SCHEMA,
        "stream": False,
        # Qwen 3.5 piensa antes de responder y así no termina a tiempo en CPU.
        "think": False,
        # 4096 alcanzan (la frase con las listas son ~1000 tokens) y dejan lugar en la GPU.
        "options": {"temperature": 0, "num_ctx": 4096}
        | ({"num_gpu": settings.llm_num_gpu} if settings.llm_num_gpu is not None else {}),
    }
    response = await client.post(f"{settings.llm_base_url}/api/chat", json=payload, timeout=route.timeout_ms / 1000)
    response.raise_for_status()
    body = response.json()
    extraction = parse(body["message"]["content"], context)
    return Extracted(extraction, int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0))
