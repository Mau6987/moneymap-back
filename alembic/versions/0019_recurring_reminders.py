"""Los recurrentes son recordatorios: ya no se registran solos.

Todos pasan a `auto_post = false`, así el job no registra nada al vencer. La
persona los paga con `POST /v1/recurring-rules/{id}/payments` y, mientras no,
la web los muestra en "Cuentas por pagar". La API ignora un `auto_post: true`
para que las apps viejas que lo mandan sigan funcionando.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE finance.recurring_rules SET auto_post = false WHERE auto_post")


def downgrade() -> None:
    # Cuáles eran automáticos no se guardó: quedan como recordatorios.
    pass
