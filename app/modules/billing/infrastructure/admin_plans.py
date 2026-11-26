"""El SQL del panel de planes (MM-189).

Las lecturas del catálogo son tablas que `moneymap_app` ya lee. Lo que es de
todos los usuarios (suscriptores por plan, historial) y toda escritura pasan por
las funciones `billing.admin_*` de la migración 0017, que vuelven a mirar el rol.
"""

import json
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.domain.models import AdminChange, AdminFeature, AdminPlan, AdminPrice

_IS_ADMIN = text("SELECT iam.is_admin()")

_SELECT_PLANS = text("SELECT code, name, description, tier, is_public FROM billing.plans WHERE is_active ORDER BY tier")

_SELECT_PRICES = text(
    """
    SELECT plans.code AS plan_code, prices.billing_period, prices.currency, prices.amount
    FROM billing.plan_prices AS prices
    JOIN billing.plans AS plans ON plans.id = prices.plan_id
    WHERE prices.is_active
    ORDER BY plans.tier, prices.currency, prices.billing_period
    """
)

_SELECT_FEATURES = text(
    """
    SELECT plans.code AS plan_code, features.key, features.description, features.value_type,
           features.limit_period, coalesce(plan_features.is_enabled, false) AS is_enabled,
           plan_features.limit_value
    FROM billing.plans AS plans
    CROSS JOIN billing.features AS features
    LEFT JOIN billing.plan_features AS plan_features
           ON plan_features.plan_id = plans.id AND plan_features.feature_key = features.key
    ORDER BY plans.tier, features.key
    """
)

_SELECT_SUBSCRIBERS = text("SELECT plan_code, subscribers FROM billing.admin_plan_subscribers()")

_UPDATE_PLAN = text("SELECT billing.admin_update_plan(:code, :name, :description, :is_public)")

_SET_FEATURE = text("SELECT billing.admin_set_feature(:code, :key, :enabled, :limit)")

_SET_PRICE = text("SELECT billing.admin_set_price(:code, :period, :currency, :amount)")

_SELECT_CHANGES = text("SELECT occurred_at, entity, action, changes FROM billing.admin_changes(:limit)")


class SqlAdminPlans:
    """Implementa `AdminPlans` sobre la sesión del usuario."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_admin(self) -> bool:
        return bool((await self._session.execute(_IS_ADMIN)).scalar_one())

    async def plans(self) -> Sequence[AdminPlan]:
        subscribers = {
            row["plan_code"]: int(row["subscribers"])
            for row in (await self._session.execute(_SELECT_SUBSCRIBERS)).mappings()
        }
        prices: dict[str, list[AdminPrice]] = {}
        for row in (await self._session.execute(_SELECT_PRICES)).mappings():
            prices.setdefault(row["plan_code"], []).append(
                AdminPrice(period=row["billing_period"], currency=row["currency"].strip(), amount=row["amount"])
            )
        features: dict[str, list[AdminFeature]] = {}
        for row in (await self._session.execute(_SELECT_FEATURES)).mappings():
            features.setdefault(row["plan_code"], []).append(
                AdminFeature(
                    key=row["key"],
                    description=row["description"],
                    kind=row["value_type"],
                    period=row["limit_period"],
                    enabled=row["is_enabled"],
                    limit=row["limit_value"],
                )
            )
        return [
            AdminPlan(
                code=row["code"],
                name=row["name"],
                description=row["description"],
                tier=row["tier"],
                is_public=row["is_public"],
                subscribers=subscribers.get(row["code"], 0),
                prices=prices.get(row["code"], []),
                features=features.get(row["code"], []),
            )
            for row in (await self._session.execute(_SELECT_PLANS)).mappings()
        ]

    async def update_plan(self, code: str, name: str, description: str | None, is_public: bool) -> bool:
        params = {"code": code, "name": name, "description": description, "is_public": is_public}
        return bool((await self._session.execute(_UPDATE_PLAN, params)).scalar_one())

    async def set_feature(self, code: str, key: str, enabled: bool, limit: int | None) -> bool:
        params = {"code": code, "key": key, "enabled": enabled, "limit": limit}
        return bool((await self._session.execute(_SET_FEATURE, params)).scalar_one())

    async def set_price(self, code: str, period: str, currency: str, amount: Decimal) -> bool:
        params = {"code": code, "period": period, "currency": currency, "amount": amount}
        return bool((await self._session.execute(_SET_PRICE, params)).scalar_one())

    async def changes(self, limit: int) -> Sequence[AdminChange]:
        rows = (await self._session.execute(_SELECT_CHANGES, {"limit": limit})).mappings()
        return [
            AdminChange(
                occurred_at=row["occurred_at"],
                entity=row["entity"],
                action=row["action"],
                changes=row["changes"] if isinstance(row["changes"], dict) else json.loads(row["changes"] or "{}"),
            )
            for row in rows
        ]
