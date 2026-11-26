"""Borrar la cuenta con 30 días de gracia: cuándo lo pidió (2026-10-17).

App Store y Google Play exigen que la persona pueda borrar su cuenta desde la
app. Se borra a los 30 días de pedirlo y entrar antes lo cancela (spec 001,
RF-28 a RF-31). Hace falta saber **cuándo** lo pidió: `updated_at` cambia con
cualquier edición y `deleted_at` liberaría el correo antes de tiempo
(`users_email_uq` lo mira).

El CHECK ata la fecha al estado: no queda una cuenta `pending_deletion` sin
fecha, que el job nunca borraría, ni una activa con fecha vieja, que borraría
sin querer.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE iam.users ADD COLUMN deletion_requested_at timestamptz")
    op.execute(
        "ALTER TABLE iam.users ADD CONSTRAINT users_deletion_requested_chk"
        " CHECK ((status = 'pending_deletion') = (deletion_requested_at IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX users_deletion_due_idx ON iam.users (deletion_requested_at) WHERE status = 'pending_deletion'"
    )
    op.execute(
        "COMMENT ON COLUMN iam.users.deletion_requested_at IS"
        " 'Cuándo pidió borrar su cuenta. A los 30 días un job la borra en cascada;"
        " entrar antes lo cancela. Existe solo si status es pending_deletion.'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX iam.users_deletion_due_idx")
    op.execute("ALTER TABLE iam.users DROP CONSTRAINT users_deletion_requested_chk")
    op.execute("ALTER TABLE iam.users DROP COLUMN deletion_requested_at")
