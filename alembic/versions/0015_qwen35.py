"""Qwen 3.5 4B de principal para extraer el movimiento (PRD 1.5.3, spec 012).

Es más nuevo que Qwen3 4B Instruct y pesa lo mismo. Piensa antes de responder:
el worker le manda `think: false`, porque pensando no termina a tiempo en CPU.
Gemma 3 4B sigue de respaldo; Qwen3 4B Instruct queda en el catálogo sin ruta.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INSERT_MODEL = """
INSERT INTO ai.models (code, provider, model, kind, price_per_minute_usd,
                       input_per_mtok_usd, cached_input_per_mtok_usd, output_per_mtok_usd, prices_checked_on, notes)
VALUES ('ollama.qwen3-5-4b', 'ollama', 'qwen3.5:4b', 'llm', NULL, 0, 0, 0, '2026-10-24',
        'Qwen 3.5 4B (Q4_K_M) en Ollama, sin pensar (think: false). Apache 2.0')
"""

_SET_ORDER = "SELECT ai.set_route_order('voice.extract', CAST(:models AS text[]), :reason)"

# Con el modelo frío tarda unos 20 s en la laptop: 60 s dan margen en el VPS sin GPU.
_SET_TIMEOUT = "UPDATE ai.routes SET timeout_ms = 60000 WHERE model_code = 'ollama.qwen3-5-4b'"


def _set_order(models: list[str], reason: str) -> None:
    bind = op.get_bind()
    bind.execute(sa.text("SELECT set_config('app.actor', 'migración 0015', true)"))
    bind.execute(sa.text(_SET_ORDER), {"models": models, "reason": reason})


def upgrade() -> None:
    op.execute(_INSERT_MODEL)
    _set_order(["ollama.qwen3-5-4b", "ollama.gemma3-4b"], "PRD 1.5.3: Qwen 3.5 4B de principal")
    op.execute(_SET_TIMEOUT)


def downgrade() -> None:
    _set_order(["ollama.qwen3-4b-instruct", "ollama.gemma3-4b"], "downgrade de la migración 0015")
    op.execute("DELETE FROM ai.routes WHERE model_code = 'ollama.qwen3-5-4b'")
    op.execute("DELETE FROM ai.models WHERE code = 'ollama.qwen3-5-4b'")
