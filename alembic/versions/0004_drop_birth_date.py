"""Quita la fecha de nacimiento: el registro ya no pide la edad (2026-10-16).

Producto decidió no pedir la fecha de nacimiento, así que se van la columna y el
CHECK de mayores de 18 que la usaba (`users_adult_chk`). El RF-2 de la spec 001
queda sin efecto: su número no se reusa.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE iam.users DROP CONSTRAINT users_adult_chk")
    op.execute("ALTER TABLE iam.users DROP COLUMN birth_date")


def downgrade() -> None:
    # Vuelve la columna vacía: los valores se perdieron al quitarla, así que no se
    # puede reponer ni el NOT NULL ni el CHECK de mayores de 18.
    op.execute("ALTER TABLE iam.users ADD COLUMN birth_date date")
    op.execute(
        "COMMENT ON COLUMN iam.users.birth_date IS"
        " 'Fecha de nacimiento. La migración 0004 la quita y este downgrade la repone"
        " vacía: los valores no se recuperan.'"
    )
