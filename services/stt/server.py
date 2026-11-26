"""Voz a texto propio (spec 012): Parakeet de principal y Whisper de respaldo.

    POST /transcribe?model=parakeet|whisper   el audio crudo en el cuerpo
    GET  /health                              los modelos cargados

Acepta lo que decodifica PyAV (m4a, ogg, webm, wav, mp3) y responde
{"text": "...", "audio_seconds": 5.2}. Cada modelo atiende un audio a la vez,
para no quitarle CPU a la API. `STT_MODELS` elige cuáles cargar.
"""

import io
import json
import os
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import onnx_asr
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

SAMPLE_RATE = 16000
MAX_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 60
THREADS = int(os.environ.get("STT_THREADS", "4"))

Transcriber = Callable[[np.ndarray], str]


def _parakeet() -> Transcriber:
    model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8")
    return lambda audio: str(model.recognize(audio, sample_rate=SAMPLE_RATE))


def _whisper() -> Transcriber:
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=THREADS)

    def run(audio: np.ndarray) -> str:
        segments, _ = model.transcribe(audio, language="es", beam_size=1)
        return " ".join(segment.text.strip() for segment in segments)

    return run


LOADERS = {"parakeet": _parakeet, "whisper": _whisper}
MODELS = {
    name: (LOADERS[name](), threading.Lock())
    for name in os.environ.get("STT_MODELS", "parakeet,whisper").split(",")
    if name
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"models": sorted(MODELS)})
        else:
            self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        name = parse_qs(url.query).get("model", [""])[0]
        if url.path != "/transcribe" or name not in MODELS:
            self._reply(404, {"error": "unknown_model"})
            return
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= MAX_BYTES:
            self._reply(413, {"error": "audio_too_large"})
            return
        try:
            audio = decode_audio(io.BytesIO(self.rfile.read(size)), sampling_rate=SAMPLE_RATE)
        except Exception:  # PyAV levanta errores de varios tipos según el formato
            self._reply(422, {"error": "invalid_audio"})
            return
        seconds = len(audio) / SAMPLE_RATE
        if seconds > MAX_SECONDS:
            self._reply(413, {"error": "audio_too_long"})
            return
        transcribe, lock = MODELS[name]
        with lock:
            text = transcribe(audio).strip()
        self._reply(200, {"text": text, "audio_seconds": round(seconds, 2)})

    def _reply(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    # Todas las interfaces del contenedor: el compose publica solo en 127.0.0.1
    # y en la red interna moneymap-ai.
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()  # noqa: S104
