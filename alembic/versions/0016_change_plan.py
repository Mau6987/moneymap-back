"""Cambiar de plan sin cobro (MM-186, spec 011 RF-5).

Todavía no hay cobros: toda cuenta empieza en el gratuito y el usuario elige
su plan desde la app o la web. `billing.change_plan` deja la suscripción en el
plan pedido al instante, con `provider = 'internal'` y sin pago:

- A un plan de pago: crea la suscripción activa (mensual, renovación
  automática, así el job no la vence) o cambia la que ya tiene.
- Al gratuito: termina la suscripción viva (`expired`, `cancel_reason = 'user'`).
- Una suscripción de App Store o Play Store no se toca: se cambia en la tienda
  (HINT `plan_managed_by_store`).

Al bajar de plan no se borra nada: lo que ya existe queda y los triggers de
límites impiden crear más hasta estar dentro del nuevo plan.

El usuario sale de `app.user_id` (la misma variable que usa la RLS), nunca de un
parámetro: `moneymap_app` no puede cambiar el plan de otro. La función es
SECURITY DEFINER porque `moneymap_app` solo lee `billing.subscriptions`.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION billing.change_plan(p_code text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_user  uuid := nullif(current_setting('app.user_id', true), '')::uuid;
  v_plan  billing.plans%ROWTYPE;
  v_sub   billing.subscriptions%ROWTYPE;
  v_price uuid;
BEGIN
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'Sin usuario en la sesión' USING ERRCODE = '42501';
  END IF;

  SELECT * INTO v_plan FROM billing.plans WHERE code = p_code AND is_active AND is_public;
  IF NOT FOUND THEN
    RETURN false;
  END IF;

  SELECT * INTO v_sub FROM billing.subscriptions
   WHERE user_id = v_user AND status IN ('trialing', 'active', 'grace_period', 'on_hold', 'paused')
   FOR UPDATE;

  IF v_sub.id IS NOT NULL AND v_sub.provider IN ('app_store', 'play_store') THEN
    RAISE EXCEPTION 'La suscripción se cambia en la tienda donde se compró'
      USING ERRCODE = 'P0001', HINT = 'plan_managed_by_store';
  END IF;

  PERFORM set_config('app.change_source', 'user', true);

  IF v_plan.tier = 0 THEN
    IF v_sub.id IS NOT NULL THEN
      UPDATE billing.subscriptions
         SET status = 'expired', auto_renew = false, cancel_reason = 'user', ended_at = now()
       WHERE id = v_sub.id;
    END IF;
    RETURN true;
  END IF;

  SELECT id INTO v_price
    FROM billing.plan_prices
   WHERE plan_id = v_plan.id AND billing_period = 'month' AND is_active
   ORDER BY currency = 'BOB' DESC, currency
   LIMIT 1;
  IF v_price IS NULL THEN
    RETURN false;
  END IF;

  IF v_sub.id IS NOT NULL THEN
    UPDATE billing.subscriptions
       SET plan_id = v_plan.id, plan_price_id = v_price, billing_period = 'month',
           status = 'active', auto_renew = true,
           pending_plan_price_id = NULL, pending_change_at = NULL
     WHERE id = v_sub.id;
  ELSE
    INSERT INTO billing.subscriptions
           (user_id, plan_id, plan_price_id, billing_period, status, provider, auto_renew, current_period_end)
    VALUES (v_user, v_plan.id, v_price, 'month', 'active', 'internal', true, now() + interval '1 month');
  END IF;
  RETURN true;
END
$$
"""


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION billing.change_plan(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION billing.change_plan(text) TO moneymap_app")
    op.execute(
        "COMMENT ON FUNCTION billing.change_plan(text) IS "
        "'MM-186: cambia el plan del usuario de app.user_id sin cobro (provider internal).'"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS billing.change_plan(text)")
