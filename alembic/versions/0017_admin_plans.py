"""Panel de administrador para los planes (MM-189, spec 013).

Un solo administrador entra con el mismo login y gestiona los cuatro planes:
nombre, descripción, si se muestran, sus precios y qué funcionalidades tiene
cada uno con qué límite. No se crean ni se borran planes.

- `iam.users.is_admin`, con un índice único parcial: a lo sumo un administrador.
  Se nombra a mano en la base (ver docs/specs/013-panel-admin/spec.md).
- `iam.is_admin()`: si el usuario de `app.user_id` es el administrador.
- `billing.admin_*`: SECURITY DEFINER, porque `moneymap_app` solo lee `billing`.
  Cada una vuelve a mirar el rol: sin él, `42501` con HINT `admin_required`.
- Auditoría: `core.audit_row_change` también en `billing.plans`,
  `billing.plan_features` y `billing.plan_prices`. `billing.admin_changes` lee
  esas filas para el historial del panel.

Bajar un límite no borra nada: lo que ya existe queda y los triggers de
límites impiden crear más (igual que bajar de plan, MM-186).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_COLUMN = """
ALTER TABLE iam.users ADD COLUMN is_admin boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX users_single_admin_uq ON iam.users ((true)) WHERE is_admin;
COMMENT ON COLUMN iam.users.is_admin IS 'MM-189: el único administrador del panel de planes';
"""

_IS_ADMIN = """
CREATE OR REPLACE FUNCTION iam.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT coalesce((
    SELECT u.is_admin FROM iam.users u
     WHERE u.id = nullif(current_setting('app.user_id', true), '')::uuid
       AND u.status = 'active' AND u.deleted_at IS NULL
  ), false)
$$;
"""

_REQUIRE_ADMIN = """
CREATE OR REPLACE FUNCTION billing.require_admin()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  IF NOT iam.is_admin() THEN
    RAISE EXCEPTION 'Solo el administrador gestiona los planes'
      USING ERRCODE = '42501', HINT = 'admin_required';
  END IF;
END
$$;
"""

_UPDATE_PLAN = """
CREATE OR REPLACE FUNCTION billing.admin_update_plan(
  p_code text, p_name text, p_description text, p_is_public boolean)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_tier smallint;
BEGIN
  PERFORM billing.require_admin();
  SELECT tier INTO v_tier FROM billing.plans WHERE code = p_code;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF v_tier = 0 AND NOT p_is_public THEN
    RAISE EXCEPTION 'El plan gratuito siempre se muestra'
      USING ERRCODE = 'P0001', HINT = 'free_plan_required';
  END IF;
  UPDATE billing.plans
     SET name = p_name, description = nullif(btrim(p_description), ''), is_public = p_is_public
   WHERE code = p_code;
  RETURN true;
END
$$;
"""

_SET_FEATURE = """
CREATE OR REPLACE FUNCTION billing.admin_set_feature(
  p_code text, p_key text, p_enabled boolean, p_limit integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_plan    uuid;
  v_feature billing.features%ROWTYPE;
BEGIN
  PERFORM billing.require_admin();
  SELECT id INTO v_plan FROM billing.plans WHERE code = p_code;
  SELECT * INTO v_feature FROM billing.features WHERE key = p_key;
  IF v_plan IS NULL OR v_feature.key IS NULL THEN
    RETURN false;
  END IF;
  IF v_feature.value_type = 'boolean' AND p_limit IS NOT NULL THEN
    RAISE EXCEPTION 'Una funcionalidad de sí o no no lleva límite'
      USING ERRCODE = 'P0001', HINT = 'invalid_limit';
  END IF;
  IF p_limit IS NOT NULL AND p_limit < 0 THEN
    RAISE EXCEPTION 'El límite no puede ser negativo'
      USING ERRCODE = 'P0001', HINT = 'invalid_limit';
  END IF;
  INSERT INTO billing.plan_features (plan_id, feature_key, is_enabled, limit_value)
  VALUES (v_plan, p_key, p_enabled, p_limit)
  ON CONFLICT (plan_id, feature_key)
  DO UPDATE SET is_enabled = EXCLUDED.is_enabled, limit_value = EXCLUDED.limit_value;
  RETURN true;
END
$$;
"""

_SET_PRICE = """
CREATE OR REPLACE FUNCTION billing.admin_set_price(
  p_code text, p_period text, p_currency text, p_amount numeric)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_plan billing.plans%ROWTYPE;
  v_old  billing.plan_prices%ROWTYPE;
BEGIN
  PERFORM billing.require_admin();
  SELECT * INTO v_plan FROM billing.plans WHERE code = p_code;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF v_plan.tier = 0 THEN
    RAISE EXCEPTION 'El plan gratuito no tiene precio'
      USING ERRCODE = 'P0001', HINT = 'free_plan_required';
  END IF;
  IF p_amount IS NULL OR p_amount <= 0 THEN
    RAISE EXCEPTION 'El precio tiene que ser mayor que cero'
      USING ERRCODE = 'P0001', HINT = 'invalid_amount';
  END IF;

  -- Un precio no se edita: se cierra y se abre otro, así las suscripciones que
  -- apuntan al viejo siguen con el que pagaron. Los productos de las tiendas pasan al nuevo.
  SELECT * INTO v_old FROM billing.plan_prices
   WHERE plan_id = v_plan.id AND billing_period = p_period AND currency = p_currency AND is_active
   FOR UPDATE;
  IF v_old.id IS NOT NULL THEN
    IF v_old.amount = p_amount THEN
      RETURN true;
    END IF;
    UPDATE billing.plan_prices SET is_active = false, valid_until = now() WHERE id = v_old.id;
  END IF;
  INSERT INTO billing.plan_prices
         (plan_id, billing_period, currency, amount, trial_days,
          app_store_product_id, play_store_product_id, web_price_id)
  VALUES (v_plan.id, p_period, p_currency, p_amount, coalesce(v_old.trial_days, 0),
          v_old.app_store_product_id, v_old.play_store_product_id, v_old.web_price_id);
  RETURN true;
END
$$;
"""

_SUBSCRIBERS = """
CREATE OR REPLACE FUNCTION billing.admin_plan_subscribers()
RETURNS TABLE (plan_code text, subscribers bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  PERFORM billing.require_admin();
  RETURN QUERY
    SELECT up.plan_code, count(*)
      FROM billing.user_plans up
      JOIN iam.users u ON u.id = up.user_id
     WHERE u.deleted_at IS NULL
     GROUP BY up.plan_code;
END
$$;
"""

_CHANGES = """
CREATE OR REPLACE FUNCTION billing.admin_changes(p_limit integer)
RETURNS TABLE (occurred_at timestamptz, entity text, action text, changes jsonb)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  PERFORM billing.require_admin();
  RETURN QUERY
    SELECT a.occurred_at, a.entity, a.action, a.changes
      FROM core.audit_log a
     WHERE a.entity IN ('billing.plans', 'billing.plan_features', 'billing.plan_prices')
     ORDER BY a.occurred_at DESC
     LIMIT least(greatest(p_limit, 1), 200);
END
$$;
"""

_AUDIT = """
CREATE TRIGGER plans_audit AFTER INSERT OR UPDATE OR DELETE ON billing.plans
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();
CREATE TRIGGER plan_features_audit AFTER INSERT OR UPDATE OR DELETE ON billing.plan_features
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();
CREATE TRIGGER plan_prices_audit AFTER INSERT OR UPDATE OR DELETE ON billing.plan_prices
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();
"""

_FUNCTIONS = [
    "iam.is_admin()",
    "billing.require_admin()",
    "billing.admin_update_plan(text, text, text, boolean)",
    "billing.admin_set_feature(text, text, boolean, integer)",
    "billing.admin_set_price(text, text, text, numeric)",
    "billing.admin_plan_subscribers()",
    "billing.admin_changes(integer)",
]


def upgrade() -> None:
    op.execute(_ADMIN_COLUMN)
    for sql in (_IS_ADMIN, _REQUIRE_ADMIN, _UPDATE_PLAN, _SET_FEATURE, _SET_PRICE, _SUBSCRIBERS, _CHANGES):
        op.execute(sql)
    for fn in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")  # noqa: S608 — nombres fijos de esta migración
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO moneymap_app")  # noqa: S608
    op.execute(_AUDIT)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS plans_audit ON billing.plans")
    op.execute("DROP TRIGGER IF EXISTS plan_features_audit ON billing.plan_features")
    op.execute("DROP TRIGGER IF EXISTS plan_prices_audit ON billing.plan_prices")
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")  # noqa: S608
    op.execute("DROP INDEX IF EXISTS iam.users_single_admin_uq")
    op.execute("ALTER TABLE iam.users DROP COLUMN IF EXISTS is_admin")
