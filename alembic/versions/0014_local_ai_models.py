"""Modelos de IA propios para el registro por voz (PRD 1.5.2, spec 012).

Voz a texto en el servicio stt (Parakeet de principal, Whisper de respaldo) y
extracción en Ollama (Qwen3 4B de principal, Gemma 3 4B de respaldo), todos en
docker-compose.ai.yml. Cuestan 0 por uso: el costo es el del servidor. Las
rutas de los proveedores pagos quedan desactivadas con ai.set_route_order, que
deja el cambio en ai.route_changes; sus modelos siguen en el catálogo.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INSERT_MODELS = """
INSERT INTO ai.models (code, provider, model, kind, price_per_minute_usd,
                       input_per_mtok_usd, cached_input_per_mtok_usd, output_per_mtok_usd, prices_checked_on, notes)
VALUES
  ('local.parakeet-tdt-0.6b-v3',   'local',  'parakeet',          'stt', 0, NULL, NULL, NULL, '2026-10-23',
   'NVIDIA Parakeet TDT 0.6B v3 (ONNX, int8) en el servicio stt. CC-BY-4.0'),
  ('local.whisper-large-v3-turbo', 'local',  'whisper',           'stt', 0, NULL, NULL, NULL, '2026-10-23',
   'Whisper large-v3-turbo con faster-whisper (int8) en el servicio stt. MIT'),
  ('ollama.qwen3-4b-instruct',     'ollama', 'qwen3:4b-instruct', 'llm', NULL, 0, 0, 0, '2026-10-23',
   'Qwen3 4B Instruct 2507 (Q4_K_M) en Ollama. Apache 2.0'),
  ('ollama.gemma3-4b',             'ollama', 'gemma3:4b',         'llm', NULL, 0, 0, 0, '2026-10-23',
   'Gemma 3 4B (Q4_K_M) en Ollama. Gemma Terms of Use')
"""

_SET_ORDER = "SELECT ai.set_route_order(:task, CAST(:models AS text[]), :reason)"

# En CPU, Whisper y el LLM tardan más que una API, sobre todo con el modelo frío.
_SET_TIMEOUTS = """
UPDATE ai.routes SET timeout_ms = CASE model_code WHEN 'local.parakeet-tdt-0.6b-v3' THEN 15000 ELSE 30000 END
WHERE model_code IN ('local.parakeet-tdt-0.6b-v3', 'local.whisper-large-v3-turbo',
                     'ollama.qwen3-4b-instruct', 'ollama.gemma3-4b')
"""

_LOCAL_ORDER = {
    "voice.transcribe": ["local.parakeet-tdt-0.6b-v3", "local.whisper-large-v3-turbo"],
    "voice.extract": ["ollama.qwen3-4b-instruct", "ollama.gemma3-4b"],
}
_PAID_ORDER = {
    "voice.transcribe": ["openai.gpt-transcribe", "groq.whisper-large-v3-turbo", "deepgram.nova-3"],
    "voice.extract": ["openai.gpt-6-luna", "deepseek.deepseek-flash", "anthropic.claude-haiku-5-5"],
}


def _set_orders(orders: dict[str, list[str]], reason: str) -> None:
    bind = op.get_bind()
    bind.execute(sa.text("SELECT set_config('app.actor', 'migración 0014', true)"))
    for task, models in orders.items():
        bind.execute(sa.text(_SET_ORDER), {"task": task, "models": models, "reason": reason})


def upgrade() -> None:
    op.execute(_INSERT_MODELS)
    _set_orders(_LOCAL_ORDER, "PRD 1.5.2: modelos propios, sin APIs pagas")
    op.execute(_SET_TIMEOUTS)


def downgrade() -> None:
    _set_orders(_PAID_ORDER, "downgrade de la migración 0014")
    op.execute(
        "DELETE FROM ai.routes WHERE model_code IN (SELECT code FROM ai.models WHERE provider IN ('local', 'ollama'))"
    )
    op.execute("DELETE FROM ai.models WHERE provider IN ('local', 'ollama')")
