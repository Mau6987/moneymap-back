"""Los avisos al 80 % y al 100 % se encienden y se apagan por presupuesto (spec 009, RF-18).

El ajuste general de cada tipo de aviso (`notify.preferences`) sigue mandando:
apagado ahí, no llega de ningún presupuesto.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE planning.budgets"
        " ADD COLUMN alert_at_80 boolean NOT NULL DEFAULT true,"
        " ADD COLUMN alert_at_100 boolean NOT NULL DEFAULT true"
    )
    op.execute("COMMENT ON COLUMN planning.budgets.alert_at_80 IS 'Avisar al llegar al 80 % en el mes'")
    op.execute("COMMENT ON COLUMN planning.budgets.alert_at_100 IS 'Avisar al pasar el 100 % en el mes'")


def downgrade() -> None:
    op.execute("ALTER TABLE planning.budgets DROP COLUMN alert_at_80, DROP COLUMN alert_at_100")
