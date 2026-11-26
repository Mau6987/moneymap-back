"""Un aporte no pasa lo que le falta a la meta ni va a una meta cerrada (BUG-049).

Antes un aporte podía pasar el objetivo: la meta quedaba cumplida y lo que
sobraba salía de la cuenta sin ir a ningún lado ("desaparecía"). Ahora un aporte
llega como mucho a lo que falta: si lo pasa, 422 `contribution_exceeds_remaining`.
A una meta cumplida o archivada no se aporta: 422 `goal_closed`. La fila de la
meta ya se bloquea: dos aportes a la vez no la pasan entre los dos. Los retiros
(montos negativos) no cambian: se puede sacar de una meta cumplida.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = """
CREATE OR REPLACE FUNCTION goals.goal_contributions_check_account() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_goal record;
  v_account record;
BEGIN
  -- FOR UPDATE: dos aportes o retiros a la vez esperan su turno y el segundo ve lo que dejó el primero.
  SELECT g.currency, g.current_amount, g.target_amount, g.status INTO v_goal
    FROM goals.goals g WHERE g.user_id = NEW.user_id AND g.id = NEW.goal_id
     FOR UPDATE;
  IF NEW.amount > 0 THEN
    IF v_goal.status IN ('achieved', 'archived') THEN
      RAISE EXCEPTION 'La meta ya está cumplida o archivada: no recibe más aportes'
        USING ERRCODE = 'check_violation', HINT = 'goal_closed';
    END IF;
    IF NEW.amount > v_goal.target_amount - v_goal.current_amount THEN
      RAISE EXCEPTION 'La meta solo necesita % % para completarse',
        v_goal.target_amount - v_goal.current_amount, v_goal.currency
        USING ERRCODE = 'check_violation', HINT = 'contribution_exceeds_remaining';
    END IF;
  END IF;
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
  'Un aporte no pasa lo que falta ni va a una meta cerrada; la cuenta existe, va en la moneda de la meta '
  'y tiene saldo; un retiro no saca más de lo acumulado.';
"""

# La de la migración 0020.
_CHECK_0020 = """
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
    SELECT a.name, a.currency, a.current_balance INTO v_account
      FROM finance.accounts a
     WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id
       AND a.deleted_at IS NULL AND a.archived_at IS NULL
       FOR UPDATE;
    IF NOT FOUND THEN
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


def upgrade() -> None:
    op.execute(_CHECK)


def downgrade() -> None:
    op.execute(_CHECK_0020)
