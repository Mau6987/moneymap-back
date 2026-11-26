"""Un gasto o ingreso fijo no se repite (BUG-012).

Dos recurrentes vivos del mismo usuario con el mismo nombre (sin importar
mayúsculas), monto, frecuencia y moneda son el mismo compromiso contado dos
veces: 409 `recurring_duplicate`, como ya avisa la app. Otro monto u otra
frecuencia ("Coca Cola" Bs 12 cada semana y Bs 10 cada mes) sí pasan.

Es un trigger y no un índice único porque puede haber repetidos viejos, que
siguen ahí hasta que el usuario borre uno. El nombre ordena el trigger después
de `recurring_rules_before_write`, que completa la moneda.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = """
CREATE FUNCTION finance.recurring_rules_check_duplicate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- ponytail: sin índice único (hay repetidos viejos); dos altas iguales a la vez pueden pasar.
  IF NEW.deleted_at IS NULL AND EXISTS (
       SELECT 1 FROM finance.recurring_rules r
        WHERE r.user_id = NEW.user_id AND r.id <> NEW.id AND r.deleted_at IS NULL
          AND lower(btrim(r.description)) = lower(btrim(NEW.description))
          AND r.amount = NEW.amount AND r.frequency = NEW.frequency
          AND r.currency = NEW.currency) THEN
    RAISE EXCEPTION 'Ya tienes "%" con el mismo monto y frecuencia', NEW.description
      USING ERRCODE = 'unique_violation', HINT = 'recurring_duplicate';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER recurring_rules_check_duplicate
  BEFORE INSERT OR UPDATE OF description, amount, frequency, currency, deleted_at ON finance.recurring_rules
  FOR EACH ROW EXECUTE FUNCTION finance.recurring_rules_check_duplicate();
COMMENT ON FUNCTION finance.recurring_rules_check_duplicate() IS
  'Dos recurrentes vivos del usuario no repiten nombre, monto, frecuencia y moneda (recurring_duplicate).';
"""


def upgrade() -> None:
    op.execute(_CHECK)


def downgrade() -> None:
    op.execute("DROP TRIGGER recurring_rules_check_duplicate ON finance.recurring_rules")
    op.execute("DROP FUNCTION finance.recurring_rules_check_duplicate()")
