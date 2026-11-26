"""Las reglas de las metas en la base (spec 005, RF-3 y RF-7).

- Los decimales de la moneda en `target_amount` y en cada aporte, con el mismo
  error que los movimientos (`invalid_amount`, migración 0003). El aporte va en
  la moneda de su meta.
- Una meta activa que llega a su objetivo queda cumplida: `status = 'achieved'`
  y `achieved_at`. Pasa al subir `current_amount` (lo mantiene el trigger de los
  aportes) o al bajar `target_amount`. Un retiro posterior no la reabre.
- El límite de metas activas del plan (`goals.active` en `billing.plan_features`)
  ya era un dato pero nadie lo aplicaba. Igual que las tarjetas y las monedas:
  SQLSTATE MM001 con HINT `plan_limit:goals.active`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
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
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER goals_check_rules BEFORE INSERT OR UPDATE OF target_amount, current_amount, currency
          ON goals.goals
          FOR EACH ROW EXECUTE FUNCTION goals.goals_check_rules()
        """
    )
    op.execute(
        "COMMENT ON FUNCTION goals.goals_check_rules() IS"
        " 'Decimales del objetivo (invalid_amount), límite de metas activas del plan (MM001) y meta cumplida"
        " al llegar al objetivo.'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION goals.goal_contributions_check_amount() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.amount, goals.currency)
          FROM goals.goals AS goals
          WHERE goals.user_id = NEW.user_id AND goals.id = NEW.goal_id;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER goal_contributions_check_amount BEFORE INSERT OR UPDATE OF amount
          ON goals.goal_contributions
          FOR EACH ROW EXECUTE FUNCTION goals.goal_contributions_check_amount()
        """
    )
    op.execute(
        "COMMENT ON FUNCTION goals.goal_contributions_check_amount() IS"
        " 'Rechaza un aporte con más decimales que los de la moneda de su meta (invalid_amount).'"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER goal_contributions_check_amount ON goals.goal_contributions")
    op.execute("DROP FUNCTION goals.goal_contributions_check_amount()")
    op.execute("DROP TRIGGER goals_check_rules ON goals.goals")
    op.execute("DROP FUNCTION goals.goals_check_rules()")
