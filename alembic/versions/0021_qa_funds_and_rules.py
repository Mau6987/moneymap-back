"""Bugs de QA: saldo al mover dinero, gastos fijos sin cuenta y metas sin nombres repetidos.

- BUG-028 y BUG-029: una transferencia y el pago de un gasto fijo mueven dinero
  que tiene que estar. Si pasan el saldo de la cuenta, 422 `account_insufficient`
  (el mismo código que los aportes a metas, migración 0020). La fila de la cuenta
  se bloquea: dos pagos a la vez no la dejan en negativo. También al editarlos:
  subir el monto, cambiar la cuenta o restaurar uno borrado. Un gasto común
  sigue pudiendo dejarla en negativo: registra lo que ya pasó.
- BUG-027: un gasto fijo ya no queda atado a una cuenta. `account_id` es
  opcional; sin cuenta, la regla lleva su moneda. La cuenta se elige al pagar
  (`finance.require_payment_account`: sin ninguna, 422 `account_required`).
- BUG-030: dos metas vivas del mismo usuario no se llaman igual, sin importar
  mayúsculas (409 `goal_name_taken`). Es un trigger y no un índice único para
  no fallar con los repetidos que ya existen.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNDS = """
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
CREATE TRIGGER transactions_check_funds BEFORE INSERT OR UPDATE ON finance.transactions
  FOR EACH ROW EXECUTE FUNCTION finance.transactions_check_funds();
COMMENT ON FUNCTION finance.transactions_check_funds() IS
  'Una transferencia o el pago de un gasto fijo, al crearse o al editarse, no sacan de la cuenta más de lo que tiene.';
"""

_RULE_ACCOUNT = """
ALTER TABLE finance.recurring_rules ALTER COLUMN account_id DROP NOT NULL;
COMMENT ON COLUMN finance.recurring_rules.account_id IS
  'Cuenta sugerida para pagarlo; opcional (BUG-027). La cuenta real se elige al pagar.';

CREATE OR REPLACE FUNCTION finance.recurring_rules_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_currency char(3);
  v_name     text;
BEGIN
  SELECT a.currency, a.name INTO v_currency, v_name
  FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id;
  IF FOUND THEN                                   -- si no existe, la clave foránea lo rechaza
    IF NEW.currency IS NULL THEN
      NEW.currency := v_currency;
    ELSIF NEW.currency <> v_currency THEN
      RAISE EXCEPTION 'La cuenta "%" es en %: no se puede usar con %', v_name, v_currency, NEW.currency
        USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
    END IF;
  ELSIF NEW.account_id IS NULL AND NEW.currency IS NULL THEN
    RAISE EXCEPTION 'Un gasto fijo sin cuenta necesita su moneda'
      USING ERRCODE = 'check_violation', HINT = 'validation_error';
  ELSIF NEW.account_id IS NULL THEN
    PERFORM catalog.assert_currency_active(NEW.currency);
  END IF;
  NEW.next_due_on := coalesce(NEW.next_due_on, NEW.start_date);
  RETURN NEW;
END $$;

-- La cuenta con la que se paga: la elegida al pagar, o la sugerida del gasto fijo.
CREATE OR REPLACE FUNCTION finance.require_payment_account(p_account uuid)
RETURNS uuid
LANGUAGE plpgsql AS $$
BEGIN
  IF p_account IS NULL THEN
    RAISE EXCEPTION 'Elegí la cuenta con la que pagas este gasto fijo'
      USING ERRCODE = 'check_violation', HINT = 'account_required';
  END IF;
  RETURN p_account;
END $$;
"""

_RULE_ACCOUNT_OLD = """
CREATE OR REPLACE FUNCTION finance.recurring_rules_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_currency char(3);
  v_name     text;
BEGIN
  SELECT a.currency, a.name INTO v_currency, v_name
  FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id;
  IF FOUND THEN                                   -- si no existe, la clave foránea lo rechaza
    IF NEW.currency IS NULL THEN
      NEW.currency := v_currency;
    ELSIF NEW.currency <> v_currency THEN
      RAISE EXCEPTION 'La cuenta "%" es en %: no se puede usar con %', v_name, v_currency, NEW.currency
        USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
    END IF;
  END IF;
  NEW.next_due_on := coalesce(NEW.next_due_on, NEW.start_date);
  RETURN NEW;
END $$;
"""

_GOAL_NAMES = """
CREATE OR REPLACE FUNCTION goals.goals_check_name() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- ponytail: sin índice único (hay repetidos viejos); dos altas iguales a la vez pueden pasar.
  IF NEW.deleted_at IS NULL AND EXISTS (
       SELECT 1 FROM goals.goals g
        WHERE g.user_id = NEW.user_id AND g.id <> NEW.id AND g.deleted_at IS NULL
          AND lower(btrim(g.name)) = lower(btrim(NEW.name))) THEN
    RAISE EXCEPTION 'Ya tienes una meta que se llama "%"', NEW.name
      USING ERRCODE = 'unique_violation', HINT = 'goal_name_taken';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER goals_check_name BEFORE INSERT OR UPDATE OF name ON goals.goals
  FOR EACH ROW EXECUTE FUNCTION goals.goals_check_name();
COMMENT ON FUNCTION goals.goals_check_name() IS 'Dos metas vivas del usuario no se llaman igual (goal_name_taken).';
"""


def upgrade() -> None:
    for sql in (_FUNDS, _RULE_ACCOUNT, _GOAL_NAMES):
        op.execute(sql)


def downgrade() -> None:
    op.execute("DROP TRIGGER goals_check_name ON goals.goals")
    op.execute("DROP FUNCTION goals.goals_check_name()")
    op.execute("DROP FUNCTION finance.require_payment_account(uuid)")
    op.execute(_RULE_ACCOUNT_OLD)
    # Los gastos fijos sin cuenta impiden volver: hay que asignarles una antes.
    op.execute("ALTER TABLE finance.recurring_rules ALTER COLUMN account_id SET NOT NULL")
    op.execute("DROP TRIGGER transactions_check_funds ON finance.transactions")
    op.execute("DROP FUNCTION finance.transactions_check_funds()")
