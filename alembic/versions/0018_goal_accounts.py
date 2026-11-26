"""Los aportes y retiros de una meta salen de una cuenta y vuelven a ella (spec 005).

- `goals.goal_contributions.account_id`: la cuenta de donde sale el aporte o a
  donde vuelve el retiro. Opcional: los aportes viejos no la tienen.
- El saldo de esa cuenta se ajusta en la misma transacción SQL, como con los
  movimientos: un aporte lo baja y un retiro (aporte negativo) lo sube. No se
  crea un movimiento: ahorrar no es un gasto ni retirar un ingreso.
- La cuenta va en la moneda de la meta (`currency_mismatch`), no está archivada
  y un retiro no saca más de lo acumulado (`goal_insufficient`), tampoco con dos
  retiros a la vez: se bloquea la fila de la meta.
- Una cuenta con aportes no cambia de moneda (`account_currency_locked`).
- `finance.recalculate_account_balance` también cuenta esos aportes.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMN = """
ALTER TABLE goals.goal_contributions
  ADD COLUMN account_id uuid,
  ADD CONSTRAINT goal_contributions_account_fk FOREIGN KEY (user_id, account_id)
      REFERENCES finance.accounts (user_id, id) ON DELETE SET NULL (account_id);
CREATE INDEX goal_contributions_account_idx ON goals.goal_contributions (user_id, account_id)
  WHERE account_id IS NOT NULL;
COMMENT ON COLUMN goals.goal_contributions.account_id IS
  'Cuenta de donde sale el aporte o a donde vuelve el retiro. Su saldo se ajusta con el aporte.';
"""

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
    SELECT a.name, a.currency INTO v_account
      FROM finance.accounts a
     WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
       AND a.deleted_at IS NULL AND a.archived_at IS NULL;
    IF NOT FOUND THEN
      -- 404, como en los movimientos: una cuenta archivada no mueve dinero.
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
CREATE TRIGGER goal_contributions_check_account BEFORE INSERT ON goals.goal_contributions
  FOR EACH ROW EXECUTE FUNCTION goals.goal_contributions_check_account();
COMMENT ON FUNCTION goals.goal_contributions_check_account() IS
  'La cuenta del aporte existe y va en la moneda de la meta; un retiro no saca más de lo acumulado.';
"""

# Aporte: sale de la cuenta. Retiro (negativo): vuelve a ella.
_BALANCE = """
CREATE OR REPLACE FUNCTION goals.apply_contribution_to_account() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.account_id IS NOT NULL THEN
    PERFORM finance.adjust_account_balance(OLD.user_id, OLD.account_id, OLD.amount);
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') AND NEW.account_id IS NOT NULL THEN
    PERFORM finance.adjust_account_balance(NEW.user_id, NEW.account_id, -NEW.amount);
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER goal_contributions_apply_account AFTER INSERT OR UPDATE OR DELETE ON goals.goal_contributions
  FOR EACH ROW EXECUTE FUNCTION goals.apply_contribution_to_account();
"""

# Como con los movimientos (account_currency_locked): una cuenta con aportes ya se
# usó en su moneda. Cambiarla mezclaría monedas en su saldo.
_CURRENCY_LOCK = """
CREATE OR REPLACE FUNCTION goals.accounts_currency_locked_by_contributions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.currency <> OLD.currency AND EXISTS (
       SELECT 1 FROM goals.goal_contributions c WHERE c.user_id = OLD.user_id AND c.account_id = OLD.id) THEN
    RAISE EXCEPTION 'La cuenta "%" ya se usó en una meta: crea una cuenta nueva en % en vez de cambiar su moneda',
      OLD.name, NEW.currency
      USING ERRCODE = 'check_violation', HINT = 'account_currency_locked';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER accounts_currency_locked_by_contributions BEFORE UPDATE OF currency ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION goals.accounts_currency_locked_by_contributions();
"""

_RECALCULATE = """
CREATE OR REPLACE FUNCTION finance.recalculate_account_balance(p_user uuid, p_account uuid)
RETURNS numeric
LANGUAGE sql AS $$
  UPDATE finance.accounts a
     SET current_balance = a.opening_balance + coalesce((
           SELECT sum(CASE WHEN t.account_id = p_account
                           THEN CASE t.kind WHEN 'income' THEN t.amount ELSE -t.amount END
                           ELSE t.amount END)          -- llegó por transferencia
           FROM finance.transactions t
           WHERE t.user_id = p_user
             AND (t.account_id = p_account OR t.transfer_account_id = p_account)
             AND t.deleted_at IS NULL), 0)
         - coalesce((
           SELECT sum(c.amount)                         -- aportes a metas y retiros
           FROM goals.goal_contributions c
           WHERE c.user_id = p_user AND c.account_id = p_account), 0)
   WHERE a.user_id = p_user AND a.id = p_account
  RETURNING a.current_balance
$$;
"""

_RECALCULATE_OLD = """
CREATE OR REPLACE FUNCTION finance.recalculate_account_balance(p_user uuid, p_account uuid)
RETURNS numeric
LANGUAGE sql AS $$
  UPDATE finance.accounts a
     SET current_balance = a.opening_balance + coalesce((
           SELECT sum(CASE WHEN t.account_id = p_account
                           THEN CASE t.kind WHEN 'income' THEN t.amount ELSE -t.amount END
                           ELSE t.amount END)          -- llegó por transferencia
           FROM finance.transactions t
           WHERE t.user_id = p_user
             AND (t.account_id = p_account OR t.transfer_account_id = p_account)
             AND t.deleted_at IS NULL), 0)
   WHERE a.user_id = p_user AND a.id = p_account
  RETURNING a.current_balance
$$;
"""


def upgrade() -> None:
    for sql in (_COLUMN, _CHECK, _BALANCE, _CURRENCY_LOCK, _RECALCULATE):
        op.execute(sql)


def downgrade() -> None:
    op.execute(_RECALCULATE_OLD)
    op.execute("DROP TRIGGER IF EXISTS accounts_currency_locked_by_contributions ON finance.accounts")
    op.execute("DROP FUNCTION IF EXISTS goals.accounts_currency_locked_by_contributions()")
    op.execute("DROP TRIGGER goal_contributions_apply_account ON goals.goal_contributions")
    op.execute("DROP FUNCTION goals.apply_contribution_to_account()")
    op.execute("DROP TRIGGER goal_contributions_check_account ON goals.goal_contributions")
    op.execute("DROP FUNCTION goals.goal_contributions_check_account()")
    op.execute("ALTER TABLE goals.goal_contributions DROP COLUMN account_id")
