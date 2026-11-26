"""Las categorías borradas en la base (spec 007, RF-12).

- Un movimiento o un recurrente no entra en una categoría borrada, ni en una
  que no es del usuario: `foreign_key_violation` sin nombre de restricción,
  que la API responde como 404 (igual que una cuenta que no existe). Solo al
  crearlo o al cambiarle la categoría: lo que ya estaba se sigue editando.
- Una categoría con recurrentes sin borrar no se borra: HINT `category_in_use`.
  Así ningún recurrente queda apuntando a una categoría borrada y el worker no
  falla al registrarlo.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.assert_category_active() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.category_id IS NOT NULL
             AND (TG_OP = 'INSERT' OR NEW.category_id IS DISTINCT FROM OLD.category_id) THEN
            PERFORM 1 FROM finance.categories c
            WHERE c.user_id = NEW.user_id AND c.id = NEW.category_id AND c.deleted_at IS NULL;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'La categoría % no existe para este usuario', NEW.category_id
                USING ERRCODE = 'foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER transactions_category_active BEFORE INSERT OR UPDATE OF category_id ON finance.transactions
          FOR EACH ROW EXECUTE FUNCTION finance.assert_category_active()
        """
    )
    op.execute(
        """
        CREATE TRIGGER recurring_rules_category_active BEFORE INSERT OR UPDATE OF category_id
          ON finance.recurring_rules
          FOR EACH ROW EXECUTE FUNCTION finance.assert_category_active()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.categories_check_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_rules integer;
        BEGIN
          IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
            SELECT count(*) INTO v_rules FROM finance.recurring_rules r
            WHERE r.user_id = NEW.user_id AND r.category_id = NEW.id AND r.deleted_at IS NULL;
            IF v_rules > 0 THEN
              RAISE EXCEPTION '"%" tiene % %: cámbialos de categoría o bórralos antes de borrarla',
                NEW.name, v_rules, CASE WHEN v_rules = 1 THEN 'recurrente' ELSE 'recurrentes' END
                USING ERRCODE = 'check_violation', HINT = 'category_in_use';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER categories_check_delete BEFORE UPDATE OF deleted_at ON finance.categories
          FOR EACH ROW EXECUTE FUNCTION finance.categories_check_delete()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER categories_check_delete ON finance.categories")
    op.execute("DROP FUNCTION finance.categories_check_delete()")
    op.execute("DROP TRIGGER recurring_rules_category_active ON finance.recurring_rules")
    op.execute("DROP TRIGGER transactions_category_active ON finance.transactions")
    op.execute("DROP FUNCTION finance.assert_category_active()")
