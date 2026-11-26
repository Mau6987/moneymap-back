"""Esquemas de los planes (spec 011)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.validation import MoneyAmount
from app.modules.billing.domain.models import (
    AdminChange,
    AdminFeature,
    AdminPlan,
    AdminPrice,
    Feature,
    MyPlan,
    Plan,
    Price,
)


class FeatureRead(BaseModel):
    key: str = Field(examples=["finance.cards"])
    description: str
    enabled: bool
    limit: int | None = Field(description="null: ilimitado")
    period: str | None = Field(description="total: recursos vivos; month: usos en el mes; null: sí o no")

    @classmethod
    def from_record(cls, feature: Feature) -> "FeatureRead":
        return cls(
            key=feature.key,
            description=feature.description,
            enabled=feature.enabled,
            limit=feature.limit,
            period=feature.period,
        )


class MyFeatureRead(FeatureRead):
    used: int | None = Field(description="Cuánto lleva usado; null en las de sí o no")

    @classmethod
    def from_record(cls, feature: Feature) -> "MyFeatureRead":
        return cls(**FeatureRead.from_record(feature).model_dump(), used=feature.used)


class PriceRead(BaseModel):
    currency: str
    monthly: MoneyAmount
    yearly: MoneyAmount | None
    yearly_per_month: MoneyAmount | None
    yearly_saving_pct: MoneyAmount | None = Field(description="Cuánto ahorra pagando el año, en %")
    purchasable: bool = Field(description="false: todavía no está en App Store ni en Play Store")

    @classmethod
    def from_record(cls, price: Price) -> "PriceRead":
        return cls(
            currency=price.currency,
            monthly=price.monthly,
            yearly=price.yearly,
            yearly_per_month=price.yearly_per_month,
            yearly_saving_pct=price.yearly_saving_pct,
            purchasable=price.purchasable,
        )


class PlanRead(BaseModel):
    code: str = Field(examples=["paid_1"])
    name: str
    description: str | None
    tier: int = Field(description="0 es el gratuito; mayor es un plan superior")
    prices: list[PriceRead]
    features: list[FeatureRead]

    @classmethod
    def from_record(cls, plan: Plan) -> "PlanRead":
        return cls(
            code=plan.code,
            name=plan.name,
            description=plan.description,
            tier=plan.tier,
            prices=[PriceRead.from_record(price) for price in plan.prices],
            features=[FeatureRead.from_record(feature) for feature in plan.features],
        )


class MyPlanRead(BaseModel):
    code: str
    name: str
    tier: int
    status: str = Field(description="free sin suscripción; si no, trialing, active, grace_period, on_hold o paused")
    has_paid_access: bool
    billing_period: str | None
    current_period_end: datetime | None
    auto_renew: bool | None
    features: list[MyFeatureRead]

    @classmethod
    def from_record(cls, plan: MyPlan) -> "MyPlanRead":
        return cls(
            code=plan.code,
            name=plan.name,
            tier=plan.tier,
            status=plan.status,
            has_paid_access=plan.has_paid_access,
            billing_period=plan.billing_period,
            current_period_end=plan.current_period_end,
            auto_renew=plan.auto_renew,
            features=[MyFeatureRead.from_record(feature) for feature in plan.features],
        )


class PlanChange(BaseModel):
    """El plan elegido en Planes (MM-186). Sin cobro todavía."""

    code: str = Field(examples=["paid_1"], min_length=1, max_length=40)


class AdminPriceRead(BaseModel):
    period: str = Field(description="month o year")
    currency: str
    amount: MoneyAmount

    @classmethod
    def from_record(cls, price: AdminPrice) -> "AdminPriceRead":
        return cls(period=price.period, currency=price.currency, amount=price.amount)


class AdminFeatureRead(BaseModel):
    key: str = Field(examples=["goals.active"])
    description: str
    kind: str = Field(description="limit (con límite) o boolean (sí o no)")
    period: str | None = Field(description="total, month o null")
    enabled: bool
    limit: int | None = Field(description="null: ilimitado")

    @classmethod
    def from_record(cls, feature: AdminFeature) -> "AdminFeatureRead":
        return cls(
            key=feature.key,
            description=feature.description,
            kind=feature.kind,
            period=feature.period,
            enabled=feature.enabled,
            limit=feature.limit,
        )


class AdminPlanRead(BaseModel):
    """Un plan como lo ve el panel de administración (MM-189)."""

    code: str
    name: str
    description: str | None
    tier: int
    is_public: bool
    subscribers: int = Field(description="Usuarios con este plan vigente (el gratuito: los que no pagan)")
    prices: list[AdminPriceRead]
    features: list[AdminFeatureRead]

    @classmethod
    def from_record(cls, plan: AdminPlan) -> "AdminPlanRead":
        return cls(
            code=plan.code,
            name=plan.name,
            description=plan.description,
            tier=plan.tier,
            is_public=plan.is_public,
            subscribers=plan.subscribers,
            prices=[AdminPriceRead.from_record(p) for p in plan.prices],
            features=[AdminFeatureRead.from_record(f) for f in plan.features],
        )


class AdminChangeRead(BaseModel):
    occurred_at: datetime
    entity: str = Field(examples=["billing.plan_features"])
    action: str = Field(examples=["update"])
    changes: dict[str, object] = Field(description="Por campo, [antes, después]; en un alta, la fila")

    @classmethod
    def from_record(cls, change: AdminChange) -> "AdminChangeRead":
        return cls(occurred_at=change.occurred_at, entity=change.entity, action=change.action, changes=change.changes)


class AdminPlanUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    is_public: bool


class AdminFeatureUpdate(BaseModel):
    enabled: bool
    limit: int | None = Field(default=None, ge=0, description="null: ilimitado; las de sí o no no llevan")


class AdminPriceUpdate(BaseModel):
    amount: MoneyAmount = Field(gt=0, examples=["29.00"])
