"""Un aporte a una meta no saca de la cuenta más de lo que tiene (spec 005, RF-21).

Un gasto puede dejar la cuenta en negativo: registra lo que ya pasó. Un aporte
mueve dinero que tiene que estar: si pasa el saldo de la cuenta, 422
`account_insufficient`. La app ya lo frenaba; así también la web y cualquier
cliente. La fila de la cuenta se bloquea, como la de la meta: dos aportes a la
vez no la dejan en negativo. Los retiros y los aportes sin cuenta no cambian.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = """
CREATE OR REPLACE FUNCTION goals.goal_contributions_check_account() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_goal record;
  v_account record;
BEGIN
  -- FOR UPDATE: dos retiros a la vez esperan su turno y el segundo ve lo que dejó el primero.
  SELECT g.currency, g.current_amount INTO v_goal
    FROM goals.goals g WHERE g.user_id = NEW.user_id AND g.id = NEW.goal_id
     FOR UPDATE;
  IF NEW.account_id IS NOT NULL THEN
    -- FOR UPDATE: lo mismo con dos aportes a la vez desde la misma cuenta.
    SELECT a.name, a.currency, a.current_balance INTO v_account
      FROM finance.accounts a
     WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
       AND a.deleted_at IS NULL AND a.archived_at IS NULL
       FOR UPDATE;
    IF NOT FOUND THEN
      -- 404, como en los movimientos: una cuenta archivada no mueve dinero.
      RAISE EXCEPTION 'La cuenta no existe o está archivada' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF v_account.currency <> v_goal.currency THEN
      RAISE EXCEPTION 'La cuenta "%" es en % y la meta en %', v_account.name, v_account.currency, v_goal.currency
        USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
    END IF;
    IF NEW.amount > v_account.current_balance THEN
      RAISE EXCEPTION 'La cuenta "%" tiene % y no se puede aportar %', v_account.name, v_account.current_balance,
        NEW.amount
        USING ERRCODE = 'check_violation', HINT = 'account_insufficient';
    END IF;
  END IF;
  IF NEW.amount < 0 AND v_goal.current_amount + NEW.amount < 0 THEN
    RAISE EXCEPTION 'La meta tiene % y no se puede sacar %', v_goal.current_amount, -NEW.amount
      USING ERRCODE = 'check_violation', HINT = 'goal_insufficient';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION goals.goal_contributions_check_account() IS
  'La cuenta del aporte existe, va en la moneda de la meta y tiene saldo; un retiro no saca más de lo acumulado.';
"""

# La de la migración 0018.
_CHECK_0018 = """
CREATE OR REPLACE FUNCTION goals.goal_contributions_check_account() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_goal record;
  v_account record;
BEGIN
  SELECT g.currency, g.current_amount INTO v_goal
    FROM goals.goals g WHERE g.user_id = NEW.user_id AND g.id = NEW.goal_id
     FOR UPDATE;
  IF NEW.account_id IS NOT NULL THEN
    SELECT a.name, a.currency INTO v_account
      FROM finance.accounts a
     WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
       AND a.deleted_at IS NULL AND a.archived_at IS NULL;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'La cuenta no existe o está archivada' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF v_account.currency <> v_goal.currency THEN
      RAISE EXCEPTION 'La cuenta "%" es en % y la meta en %', v_account.name, v_account.currency, v_goal.currency
        USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
    END IF;
  END IF;
  IF NEW.amount < 0 AND v_goal.current_amount + NEW.amount < 0 THEN
    RAISE EXCEPTION 'La meta tiene % y no se puede sacar %', v_goal.current_amount, -NEW.amount
      USING ERRCODE = 'check_violation', HINT = 'goal_insufficient';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION goals.goal_contributions_check_account() IS
  'La cuenta del aporte existe y va en la moneda de la meta; un retiro no saca más de lo acumulado.';
"""


def upgrade() -> None:
    op.execute(_CHECK)


def downgrade() -> None:
    op.execute(_CHECK_0018)
