"""Presupuestos por categoría (spec 009, PRD §6.16 y §6.17).

Sale de `db/future/110_budgets.sql`, recortado a lo que pide el PRD V1.5:

- Un presupuesto es un monto por mes para una categoría de gasto y una moneda.
  Se repite todos los meses hasta que se cambia o se borra. Lo no gastado no se
  acumula, y los avisos son fijos al 80 y al 100 %. Por eso no van `starts_on`,
  `ends_on`, `rollover` ni `alert_threshold`: corregir el monto cambia el
  presupuesto desde el mes en curso.
- Los decimales del monto, con el mismo error que los movimientos
  (`invalid_amount`), y la moneda activa (`currency_unavailable`).
- El límite del plan (`planning.budgets`, PROVISIONAL: 3 en el gratuito, PRD
  §6.2) igual que las metas: SQLSTATE MM001 con HINT `plan_limit:planning.budgets`.
- Los avisos `budget.threshold` (80 %) y `budget.exceeded` (100 %).
- La categoría tiene que existir y no estar borrada (el mismo trigger de la
  migración 0008: 404). Al borrar una categoría se borran sus presupuestos: un
  presupuesto sin categoría no mide nada y no tiene por qué frenar el borrado.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# billing.resource_usage de db/migrations/030_billing.sql, con una rama más.
_RESOURCE_USAGE = """
CREATE OR REPLACE FUNCTION billing.resource_usage(p_user uuid, p_feature text) RETURNS integer
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  CASE p_feature
    WHEN 'finance.cards' THEN
      RETURN (SELECT count(*) FROM finance.accounts a
              JOIN catalog.account_types t ON t.code = a.type AND t.is_card
              WHERE a.user_id = p_user AND a.deleted_at IS NULL AND a.archived_at IS NULL);
    WHEN 'finance.currencies' THEN
      RETURN (SELECT count(DISTINCT a.currency) FROM finance.accounts a
              WHERE a.user_id = p_user AND a.deleted_at IS NULL AND a.archived_at IS NULL);
    WHEN 'goals.active' THEN
      RETURN (SELECT count(*) FROM goals.goals g
              WHERE g.user_id = p_user AND g.deleted_at IS NULL AND g.status = 'active');
    {budgets}
    ELSE
      RETURN 0;
  END CASE;
END $$
"""
_BUDGETS_USAGE = """WHEN 'planning.budgets' THEN
      RETURN (SELECT count(*) FROM planning.budgets b WHERE b.user_id = p_user AND b.deleted_at IS NULL);"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE planning.budgets (
          id            uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
          user_id       uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
          category_id   uuid          NOT NULL,
          currency      char(3)       NOT NULL REFERENCES catalog.currencies (code),
          amount        numeric(19,4) NOT NULL CONSTRAINT budgets_amount_check CHECK (amount > 0),
          created_at    timestamptz   NOT NULL DEFAULT now(),
          updated_at    timestamptz   NOT NULL DEFAULT now(),
          deleted_at    timestamptz,
          category_kind catalog.money_kind NOT NULL DEFAULT 'expense' CHECK (category_kind = 'expense'),
          CONSTRAINT budgets_category_fk FOREIGN KEY (user_id, category_id, category_kind)
                                         REFERENCES finance.categories (user_id, id, kind)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX budgets_active_uq ON planning.budgets (user_id, category_id, currency)"
        " WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE TRIGGER budgets_set_updated_at BEFORE UPDATE ON planning.budgets"
        " FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()"
    )
    op.execute(
        """
        CREATE FUNCTION planning.budgets_check_rules() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          v_limit record;
        BEGIN
          PERFORM catalog.assert_currency_active(NEW.currency);
          PERFORM finance.assert_amount_decimals(NEW.amount, NEW.currency);
          IF TG_OP = 'INSERT' THEN
            -- Serializa las altas del mismo usuario (varias instancias de la API)
            PERFORM pg_advisory_xact_lock(hashtextextended('planning.budgets:' || NEW.user_id::text, 0));
            SELECT * INTO v_limit FROM billing.limit_status(NEW.user_id, 'planning.budgets');
            IF NOT coalesce(v_limit.allowed, false) THEN
              RAISE EXCEPTION 'Tu plan permite % presupuesto(s) y ya tienes %',
                coalesce(v_limit.limit_value, 0), coalesce(v_limit.used, 0)
                USING ERRCODE = 'MM001', HINT = 'plan_limit:planning.budgets';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER budgets_check_rules BEFORE INSERT OR UPDATE OF amount, currency ON planning.budgets"
        " FOR EACH ROW EXECUTE FUNCTION planning.budgets_check_rules()"
    )
    op.execute(
        "CREATE TRIGGER budgets_category_active BEFORE INSERT OR UPDATE OF category_id ON planning.budgets"
        " FOR EACH ROW EXECUTE FUNCTION finance.assert_category_active()"
    )
    op.execute(
        """
        CREATE FUNCTION planning.delete_category_budgets() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          UPDATE planning.budgets SET deleted_at = now()
          WHERE user_id = NEW.user_id AND category_id = NEW.id AND deleted_at IS NULL;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER categories_delete_budgets AFTER UPDATE OF deleted_at ON finance.categories"
        " FOR EACH ROW WHEN (NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL)"
        " EXECUTE FUNCTION planning.delete_category_budgets()"
    )
    op.execute("ALTER TABLE planning.budgets ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY own_rows ON planning.budgets FOR ALL TO moneymap_app"
        " USING (user_id = (SELECT core.current_user_id())) WITH CHECK (user_id = (SELECT core.current_user_id()))"
    )
    op.execute("CREATE POLICY worker_all ON planning.budgets FOR ALL TO moneymap_worker USING (true) WITH CHECK (true)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON planning.budgets TO moneymap_app, moneymap_worker")
    op.execute(_RESOURCE_USAGE.format(budgets=_BUDGETS_USAGE))
    op.execute(
        """
        INSERT INTO billing.features (key, description, value_type, limit_period)
        VALUES ('planning.budgets', 'Presupuestos por categoría', 'limit', 'total')
        """
    )
    op.execute(
        """
        INSERT INTO billing.plan_features (plan_id, feature_key, is_enabled, limit_value)
        SELECT id, 'planning.budgets', true, CASE WHEN code = 'free' THEN 3 END FROM billing.plans
        """
    )
    op.execute(
        """
        INSERT INTO notify.notification_types (key, description) VALUES
          ('budget.threshold', 'Usaste el 80 % del presupuesto de una categoría'),
          ('budget.exceeded',  'Superaste el presupuesto de una categoría')
        """
    )
    op.execute(
        "COMMENT ON TABLE planning.budgets IS 'Límite mensual por categoría de gasto y moneda; se repite cada mes."
        " Lo gastado sale de reports.category_totals en esa moneda. Quién escribe: la API.'"
    )
    op.execute("COMMENT ON COLUMN planning.budgets.amount IS 'Monto por mes, en currency'")
    op.execute("COMMENT ON COLUMN planning.budgets.currency IS 'Solo cuentan los gastos en esta moneda'")
    op.execute(
        "COMMENT ON FUNCTION planning.budgets_check_rules() IS"
        " 'Moneda activa, decimales del monto (invalid_amount) y límite de presupuestos del plan (MM001).'"
    )
    op.execute(
        "COMMENT ON FUNCTION planning.delete_category_budgets() IS 'Al borrar una categoría, borra sus presupuestos.'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notify.notification_types WHERE key IN ('budget.threshold', 'budget.exceeded')")
    op.execute("DELETE FROM billing.plan_features WHERE feature_key = 'planning.budgets'")
    op.execute("DELETE FROM billing.features WHERE key = 'planning.budgets'")
    op.execute(_RESOURCE_USAGE.format(budgets=""))
    op.execute("DROP TRIGGER categories_delete_budgets ON finance.categories")
    op.execute("DROP FUNCTION planning.delete_category_budgets()")
    op.execute("DROP TABLE planning.budgets")
    op.execute("DROP FUNCTION planning.budgets_check_rules()")
