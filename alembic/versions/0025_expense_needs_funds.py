"""Un gasto no saca de la cuenta más de lo que tiene (BUG-024, decisión del 2026-10-31).

Hasta acá `finance.transactions_check_funds` frenaba las transferencias y el
pago de un gasto fijo (migración 0021). Ahora frena todo gasto, al crearlo o al
editarlo para que saque más: 422 `account_insufficient`, como en la app. Un
ingreso no tiene límite y una edición que no saca más (otra descripción, otra
fecha, menos monto) sigue pasando aunque la cuenta ya esté en negativo.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = """
CREATE OR REPLACE FUNCTION finance.transactions_check_funds() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_account   record;
  v_available numeric;
BEGIN
  -- BUG-024: todo gasto, no solo el pago de un gasto fijo; un ingreso no tiene límite.
  IF NEW.deleted_at IS NOT NULL OR NEW.kind NOT IN ('transfer', 'expense') THEN
    RETURN NEW;
  END IF;
  -- Una edición que no saca más de la cuenta (otra descripción, otra fecha, menos
  -- monto) pasa aunque la cuenta ya esté en negativo por otros gastos.
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND OLD.account_id = NEW.account_id
     AND OLD.kind = NEW.kind AND NEW.amount <= OLD.amount THEN
    RETURN NEW;
  END IF;
  -- FOR UPDATE: dos pagos a la vez desde la misma cuenta esperan su turno.
  SELECT a.name, a.current_balance INTO v_account
    FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RETURN NEW;
  END IF;
  -- Al editar, lo que el movimiento viejo ya sacó de esta cuenta vuelve antes de mirar el nuevo.
  v_available := v_account.current_balance;
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND OLD.account_id = NEW.account_id THEN
    v_available := v_available + CASE OLD.kind WHEN 'income' THEN -OLD.amount ELSE OLD.amount END;
  END IF;
  IF NEW.amount > v_available THEN
    RAISE EXCEPTION 'La cuenta "%" tiene % y no alcanza para %', v_account.name, v_available, NEW.amount
      USING ERRCODE = 'check_violation', HINT = 'account_insufficient';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION finance.transactions_check_funds() IS
  'Un gasto o una transferencia, al crearse o al editarse, no sacan de la cuenta más de lo que tiene.';
"""

# La de la migración 0021.
_CHECK_0021 = """
CREATE OR REPLACE FUNCTION finance.transactions_check_funds() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_account   record;
  v_available numeric;
BEGIN
  IF NEW.deleted_at IS NOT NULL
     OR NOT (NEW.kind = 'transfer' OR (NEW.kind = 'expense' AND NEW.recurring_rule_id IS NOT NULL)) THEN
    RETURN NEW;
  END IF;
  -- Una edición que no saca más de la cuenta (otra descripción, otra fecha, menos
  -- monto) pasa aunque la cuenta ya esté en negativo por otros gastos.
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND OLD.account_id = NEW.account_id
     AND OLD.kind = NEW.kind AND NEW.amount <= OLD.amount THEN
    RETURN NEW;
  END IF;
  -- FOR UPDATE: dos pagos a la vez desde la misma cuenta esperan su turno.
  SELECT a.name, a.current_balance INTO v_account
    FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RETURN NEW;
  END IF;
  -- Al editar, lo que el movimiento viejo ya sacó de esta cuenta vuelve antes de mirar el nuevo.
  v_available := v_account.current_balance;
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND OLD.account_id = NEW.account_id THEN
    v_available := v_available + CASE OLD.kind WHEN 'income' THEN -OLD.amount ELSE OLD.amount END;
  END IF;
  IF NEW.amount > v_available THEN
    RAISE EXCEPTION 'La cuenta "%" tiene % y no alcanza para %', v_account.name, v_available, NEW.amount
      USING ERRCODE = 'check_violation', HINT = 'account_insufficient';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION finance.transactions_check_funds() IS
  'Una transferencia o el pago de un gasto fijo, al crearse o al editarse, no sacan de la cuenta más de lo que tiene.';
"""


def upgrade() -> None:
    op.execute(_CHECK)


def downgrade() -> None:
    op.execute(_CHECK_0021)
