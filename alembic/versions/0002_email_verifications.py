"""Verificación del correo antes de crear la cuenta (spec 001, RF-22 a RF-26).

`iam.verification_tokens` cuelga de un usuario que ya existe. El registro de la
app verifica el correo primero y pide los datos después, así que el correo
verificado necesita su propia tabla, sin usuario todavía.

Sin RLS, como el resto de la identidad previa al login: su acceso lo controla la
API (900_security.sql). Del link solo se guarda el hash.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.email_verifications (
          id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
          email        citext      NOT NULL CHECK (email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'),
          token_hash   text        NOT NULL UNIQUE,
          expires_at   timestamptz NOT NULL,
          last_sent_at timestamptz NOT NULL DEFAULT now(),
          verified_at  timestamptz,
          used_at      timestamptz,
          created_at   timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT email_verifications_used_chk CHECK (used_at IS NULL OR verified_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX email_verifications_email_idx ON iam.email_verifications (email) WHERE used_at IS NULL")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON iam.email_verifications TO moneymap_app, moneymap_worker")

    op.execute(
        "COMMENT ON TABLE iam.email_verifications IS"
        " 'Correos verificados con un link antes de crear la cuenta; del link solo se guarda el hash'"
    )
    op.execute(
        """
        COMMENT ON COLUMN iam.email_verifications.id IS
          'Identificador que recibe la app para consultar el estado (UUID aleatorio, no se adivina)';
        COMMENT ON COLUMN iam.email_verifications.email IS
          'Correo que se está verificando';
        COMMENT ON COLUMN iam.email_verifications.token_hash IS
          'Hash del token del link; único';
        COMMENT ON COLUMN iam.email_verifications.expires_at IS
          'Hasta cuándo vale el link (5 minutos desde el último envío)';
        COMMENT ON COLUMN iam.email_verifications.last_sent_at IS
          'Cuándo se envió el último link; marca la espera para reenviar';
        COMMENT ON COLUMN iam.email_verifications.verified_at IS
          'Cuándo se abrió el link; vacío si todavía no';
        COMMENT ON COLUMN iam.email_verifications.used_at IS
          'Cuándo se creó la cuenta con esta verificación; no vale otra vez';
        COMMENT ON COLUMN iam.email_verifications.created_at IS
          'Cuándo se creó la fila';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE iam.email_verifications")
