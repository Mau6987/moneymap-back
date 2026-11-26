"""Solo dos planes, Gratuito y Premium, y metas sin límite en el gratuito.

- `goals.active` queda sin límite en `free`. El trigger de las metas sigue: un
  límite es un dato, y el administrador puede volver a ponerlo desde el panel.
- Plus (`paid_1`) y Pro (`paid_2`) dejan de ofrecerse. No se borran: las
  suscripciones viejas y su historial siguen apuntando a ellos.
- Quien estaba en Plus o en Pro pasa a Premium (`paid_3`), en el mismo periodo
  de facturación: nadie pierde lo que ya tenía.

El downgrade vuelve a ofrecer los planes y el límite, pero no devuelve a nadie a
su plan anterior: ese dato no se guarda.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET_FREE_GOALS = """
UPDATE billing.plan_features AS features
SET limit_value = {limit}
FROM billing.plans AS plans
WHERE plans.id = features.plan_id AND plans.code = 'free' AND features.feature_key = 'goals.active'
"""

_SET_RETIRED_PLANS = """
UPDATE billing.plans SET is_public = {offered}, is_active = {offered} WHERE code IN ('paid_1', 'paid_2')
"""

_MOVE_TO_PREMIUM = """
UPDATE billing.subscriptions AS subs
SET plan_id = premium.plan_id, plan_price_id = premium.id,
    pending_plan_price_id = NULL, pending_change_at = NULL
FROM (
    SELECT DISTINCT ON (prices.billing_period) prices.id, prices.plan_id, prices.billing_period
    FROM billing.plan_prices AS prices
    JOIN billing.plans AS plans ON plans.id = prices.plan_id
    WHERE plans.code = 'paid_3' AND prices.is_active
    ORDER BY prices.billing_period, prices.currency = 'BOB' DESC, prices.currency
) AS premium
WHERE premium.billing_period = subs.billing_period
  AND subs.status IN ('trialing', 'active', 'grace_period', 'on_hold', 'paused')
  AND subs.plan_id IN (SELECT id FROM billing.plans WHERE code IN ('paid_1', 'paid_2'))
"""


def upgrade() -> None:
    op.execute(_SET_FREE_GOALS.format(limit="NULL"))
    op.execute(_MOVE_TO_PREMIUM)
    op.execute(_SET_RETIRED_PLANS.format(offered="false"))


def downgrade() -> None:
    op.execute(_SET_RETIRED_PLANS.format(offered="true"))
    op.execute(_SET_FREE_GOALS.format(limit="2"))
