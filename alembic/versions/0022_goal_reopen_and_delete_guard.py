"""Las metas se reabren al bajar del objetivo y no se borran con saldo.

Dos reglas de QA:

- Una meta cumplida que recibe un retiro (o cuyo objetivo sube) vuelve a
  `active`: el estado tiene que reflejar el saldo actual, no solo el momento en
  que se alcanzó. `achieved_at` vuelve a null.
- Una meta con `current_amount > 0` no se puede borrar: primero hay que retirar
  el saldo a una cuenta. El SQLSTATE MM002 con HINT `goal_has_saved` lo traduce
  la API a 409 `goal_has_saved`.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION goals.goals_check_rules() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_limit record;
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.target_amount, NEW.currency);
          IF TG_OP = 'INSERT' AND NEW.status = 'active' THEN
            -- Serializa las altas del mismo usuario (varias instancias de la API)
            PERFORM pg_advisory_xact_lock(hashtextextended('goals.goals:' || NEW.user_id::text, 0));
            SELECT * INTO v_limit FROM billing.limit_status(NEW.user_id, 'goals.active');
            IF NOT coalesce(v_limit.allowed, false) THEN
              RAISE EXCEPTION 'Tu plan permite % meta(s) activa(s) y ya tienes %',
                coalesce(v_limit.limit_value, 0), coalesce(v_limit.used, 0)
                USING ERRCODE = 'MM001', HINT = 'plan_limit:goals.active';
            END IF;
          END IF;
          IF NEW.status = 'active' AND NEW.current_amount >= NEW.target_amount THEN
            NEW.status := 'achieved';
            NEW.achieved_at := now();
          ELSIF NEW.status = 'achieved' AND NEW.current_amount < NEW.target_amount THEN
            -- Un retiro o un objetivo más alto la dejan por debajo: vuelve a
            -- contar como activa y a estimar su fecha.
            NEW.status := 'active';
            NEW.achieved_at := NULL;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION goals.goals_block_delete_with_saved() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL
             AND OLD.current_amount > 0 THEN
            RAISE EXCEPTION 'La meta tiene % ahorrado; retiralo a una cuenta antes de borrarla',
              OLD.current_amount
              USING ERRCODE = 'MM002', HINT = 'goal_has_saved';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER goals_block_delete_with_saved
          BEFORE UPDATE OF deleted_at ON goals.goals
          FOR EACH ROW EXECUTE FUNCTION goals.goals_block_delete_with_saved()
        """
    )
    op.execute(
        "COMMENT ON FUNCTION goals.goals_block_delete_with_saved() IS"
        " 'No deja borrar una meta con saldo: primero hay que retirarlo a una cuenta.'"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER goals_block_delete_with_saved ON goals.goals")
    op.execute("DROP FUNCTION goals.goals_block_delete_with_saved()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION goals.goals_check_rules() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_limit record;
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.target_amount, NEW.currency);
          IF TG_OP = 'INSERT' AND NEW.status = 'active' THEN
            PERFORM pg_advisory_xact_lock(hashtextextended('goals.goals:' || NEW.user_id::text, 0));
            SELECT * INTO v_limit FROM billing.limit_status(NEW.user_id, 'goals.active');
            IF NOT coalesce(v_limit.allowed, false) THEN
              RAISE EXCEPTION 'Tu plan permite % meta(s) activa(s) y ya tienes %',
                coalesce(v_limit.limit_value, 0), coalesce(v_limit.used, 0)
                USING ERRCODE = 'MM001', HINT = 'plan_limit:goals.active';
            END IF;
          END IF;
          IF NEW.status = 'active' AND NEW.current_amount >= NEW.target_amount THEN
            NEW.status := 'achieved';
            NEW.achieved_at := now();
          END IF;
          RETURN NEW;
        END $$
        """
    )
