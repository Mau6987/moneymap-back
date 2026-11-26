"""La foto del comprobante de un gasto (spec 014).

La imagen vive en el S3 propio (SeaweedFS, en el docker-compose); acá solo la
clave del objeto, su tipo y su tamaño. Uno por gasto: subir otro lo reemplaza. Al borrar el usuario se van
sus filas en cascada.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE finance.transaction_receipts (
          user_id        uuid        NOT NULL,
          transaction_id uuid        NOT NULL,
          object_key     text        NOT NULL,
          content_type   text        NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
          size_bytes     integer     NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
          created_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT transaction_receipts_pk PRIMARY KEY (user_id, transaction_id),
          CONSTRAINT transaction_receipts_transaction_fk FOREIGN KEY (user_id, transaction_id)
            REFERENCES finance.transactions (user_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute("ALTER TABLE finance.transaction_receipts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY own_rows ON finance.transaction_receipts FOR ALL TO moneymap_app"
        " USING (user_id = (SELECT core.current_user_id())) WITH CHECK (user_id = (SELECT core.current_user_id()))"
    )
    op.execute(
        "CREATE POLICY worker_all ON finance.transaction_receipts FOR ALL TO moneymap_worker"
        " USING (true) WITH CHECK (true)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON finance.transaction_receipts TO moneymap_app, moneymap_worker")
    op.execute(
        "COMMENT ON TABLE finance.transaction_receipts IS"
        " 'La foto del comprobante de un gasto: la imagen está en el S3 propio;"
        " acá su clave, tipo y tamaño. Uno por gasto.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE finance.transaction_receipts")
