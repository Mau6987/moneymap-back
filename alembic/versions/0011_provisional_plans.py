"""Planes de pago PROVISIONALES para la pantalla Planes (PRD §6.2).

Los nombres, los precios y los límites están por definir (PRD, preguntas
abiertas). Para que la pantalla tenga qué mostrar, esta migración carga datos
de ejemplo: cambiarlos es un UPDATE en `billing.plans`, `billing.plan_prices` y
`billing.plan_features`, sin desplegar código.

- Los tres planes de pago pasan a públicos y activos, con precio mensual y anual
  en bolivianos (el anual, 10 meses). Sin productos de App Store ni de Play
  Store todavía: nadie los puede comprar, y la API lo dice con `purchasable`.
- Límites que crecen de un plan al siguiente; el gratuito queda igual.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLANS = [
    ("paid_1", "Plus", "Más tarjetas, monedas y metas."),
    ("paid_2", "Pro", "Para manejar varias tarjetas y monedas sin pensar en límites."),
    ("paid_3", "Premium", "Todo sin límites."),
]

# (plan, Bs por mes, Bs por año)
_PRICES = [
    ("paid_1", Decimal("29.00"), Decimal("290.00")),
    ("paid_2", Decimal("49.00"), Decimal("490.00")),
    ("paid_3", Decimal("79.00"), Decimal("790.00")),
]

# None = ilimitado. Los planes de pago antes eran todos ilimitados.
_LIMITS = {
    "paid_1": {"finance.cards": 3, "finance.currencies": 2, "goals.active": 10, "planning.budgets": 10},
    "paid_2": {"finance.cards": 10, "finance.currencies": None, "goals.active": None, "planning.budgets": None},
}


_SET_PLAN = sa.text(
    "UPDATE billing.plans SET name = :name, description = :description, is_public = :public, is_active = :public"
    " WHERE code = :code"
)

_INSERT_PRICE = sa.text(
    """
    INSERT INTO billing.plan_prices (plan_id, billing_period, currency, amount)
    SELECT id, :period, 'BOB', :amount FROM billing.plans WHERE code = :code
    """
)

_SET_LIMIT = sa.text(
    "UPDATE billing.plan_features SET limit_value = :limit"
    " WHERE feature_key = :feature AND plan_id = (SELECT id FROM billing.plans WHERE code = :code)"
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, name, description in _PLANS:
        bind.execute(_SET_PLAN, {"code": code, "name": name, "description": description, "public": True})
    for code, monthly, yearly in _PRICES:
        bind.execute(
            _INSERT_PRICE,
            [{"code": code, "period": "month", "amount": monthly}, {"code": code, "period": "year", "amount": yearly}],
        )
    for code, limits in _LIMITS.items():
        for feature, limit in limits.items():
            bind.execute(_SET_LIMIT, {"code": code, "feature": feature, "limit": limit})


def downgrade() -> None:
    bind = op.get_bind()
    for code, limits in _LIMITS.items():
        for feature in limits:
            bind.execute(_SET_LIMIT, {"code": code, "feature": feature, "limit": None})
    op.execute(
        "DELETE FROM billing.plan_prices WHERE currency = 'BOB'"
        " AND plan_id IN (SELECT id FROM billing.plans WHERE code IN ('paid_1', 'paid_2', 'paid_3'))"
    )
    for number, (code, _, _) in enumerate(_PLANS, start=1):
        bind.execute(_SET_PLAN, {"code": code, "name": f"Plan de pago {number}", "description": None, "public": False})
