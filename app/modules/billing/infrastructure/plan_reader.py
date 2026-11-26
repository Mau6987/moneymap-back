"""El SQL de los planes: `billing.plans`, `billing.price_catalog` y `billing.user_entitlements`.

Precios y límites son datos (constitución §4): cambiarlos es un UPDATE.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.domain.models import Feature, MyPlan, Plan, Price

_SELECT_PLANS = text(
    "SELECT code, name, description, tier FROM billing.plans WHERE is_active AND is_public ORDER BY tier"
)

_SELECT_PRICES = text(
    """
    SELECT catalog.plan_code, catalog.currency, catalog.monthly_amount, catalog.yearly_amount,
           catalog.yearly_per_month, catalog.yearly_saving_pct,
           (monthly.app_store_product_id IS NOT NULL OR monthly.play_store_product_id IS NOT NULL) AS purchasable
    FROM billing.price_catalog AS catalog
    JOIN billing.plan_prices AS monthly ON monthly.id = catalog.monthly_price_id
    ORDER BY catalog.plan_code, catalog.currency
    """
)

_SELECT_FEATURES = text(
    """
    SELECT plans.code AS plan_code, features.key, features.description, features.limit_period,
           coalesce(plan_features.is_enabled, false) AS is_enabled, plan_features.limit_value
    FROM billing.plans AS plans
    CROSS JOIN billing.features AS features
    LEFT JOIN billing.plan_features AS plan_features
           ON plan_features.plan_id = plans.id AND plan_features.feature_key = features.key
    WHERE plans.is_active AND plans.is_public
    ORDER BY features.key
    """
)

_SELECT_MY_PLAN = text(
    """
    SELECT user_plans.plan_code, plans.name, user_plans.tier, user_plans.status, user_plans.has_paid_access,
           user_plans.billing_period, user_plans.current_period_end, user_plans.auto_renew
    FROM billing.user_plans AS user_plans
    JOIN billing.plans AS plans ON plans.id = user_plans.plan_id
    WHERE user_plans.user_id = :user_id
    """
)

_SELECT_MY_FEATURES = text(
    """
    SELECT entitlements.feature_key AS key, features.description, entitlements.limit_period,
           entitlements.is_enabled, entitlements.limit_value, entitlements.used_in_period
    FROM billing.user_entitlements AS entitlements
    JOIN billing.features AS features ON features.key = entitlements.feature_key
    WHERE entitlements.user_id = :user_id
    ORDER BY entitlements.feature_key
    """
)


class SqlPlanReader:
    """Implementa `PlanReader` sobre la sesión del usuario."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def plans(self) -> Sequence[Plan]:
        prices: dict[str, list[Price]] = {}
        for row in (await self._session.execute(_SELECT_PRICES)).mappings():
            prices.setdefault(row["plan_code"], []).append(
                Price(
                    currency=row["currency"],
                    monthly=row["monthly_amount"],
                    yearly=row["yearly_amount"],
                    yearly_per_month=row["yearly_per_month"],
                    yearly_saving_pct=row["yearly_saving_pct"],
                    purchasable=row["purchasable"],
                )
            )
        features: dict[str, list[Feature]] = {}
        for row in (await self._session.execute(_SELECT_FEATURES)).mappings():
            features.setdefault(row["plan_code"], []).append(_to_feature(row))
        rows = (await self._session.execute(_SELECT_PLANS)).mappings().all()
        return [
            Plan(
                row["code"],
                row["name"],
                row["description"],
                row["tier"],
                prices.get(row["code"], []),
                features[row["code"]],
            )
            for row in rows
        ]

    async def my_plan(self, user_id: UUID) -> MyPlan:
        params = {"user_id": user_id}
        row = (await self._session.execute(_SELECT_MY_PLAN, params)).mappings().one()
        features = [
            _to_feature(feature) for feature in (await self._session.execute(_SELECT_MY_FEATURES, params)).mappings()
        ]
        return MyPlan(
            code=row["plan_code"],
            name=row["name"],
            tier=row["tier"],
            status=row["status"],
            has_paid_access=row["has_paid_access"],
            billing_period=row["billing_period"],
            current_period_end=row["current_period_end"],
            auto_renew=row["auto_renew"],
            features=features,
        )


def _to_feature(row: RowMapping) -> Feature:
    return Feature(
        key=row["key"],
        description=row["description"],
        enabled=row["is_enabled"],
        limit=row["limit_value"],
        period=row["limit_period"],
        used=row.get("used_in_period"),
    )
