"""El plan gratuito ya no incluye el registro por voz (pedido del 2026-10-31).

`ai.voice_entries` queda apagado en `free`: la API responde `409 plan_limit`
con `feature: "ai.voice_entries"` y la app ofrece los planes. Los de pago no
cambian (sin límite). El administrador puede volver a cambiarlo desde el panel.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = """
UPDATE billing.plan_features AS features
SET is_enabled = {enabled}, limit_value = {limit}
FROM billing.plans AS plans
WHERE plans.id = features.plan_id AND plans.code = 'free' AND features.feature_key = 'ai.voice_entries'
"""


def upgrade() -> None:
    op.execute(_SET.format(enabled="false", limit="0"))


def downgrade() -> None:
    op.execute(_SET.format(enabled="true", limit="30"))
