"""Read models de los planes (spec 011): Python puro."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Feature:
    """Lo que un plan habilita o limita. `limit` None = ilimitado; `used` solo en el plan propio."""

    key: str
    description: str
    enabled: bool
    limit: int | None
    period: str | None  # 'total' (recursos vivos), 'month' (usos en el mes) o None (sí o no)
    used: int | None = None


@dataclass(frozen=True, slots=True)
class Price:
    currency: str
    monthly: Decimal
    yearly: Decimal | None
    yearly_per_month: Decimal | None
    yearly_saving_pct: Decimal | None
    purchasable: bool  # tiene producto en App Store o Play Store


@dataclass(frozen=True, slots=True)
class Plan:
    code: str
    name: str
    description: str | None
    tier: int
    prices: list[Price]
    features: list[Feature]


@dataclass(frozen=True, slots=True)
class MyPlan:
    code: str
    name: str
    tier: int
    status: str  # 'free' sin suscripción; si no, el de la suscripción
    has_paid_access: bool
    billing_period: str | None
    current_period_end: datetime | None
    auto_renew: bool | None
    features: list[Feature]


@dataclass(frozen=True, slots=True)
class AdminPrice:
    """Un precio activo de un plan, tal como lo edita el panel (MM-189)."""

    period: str  # 'month' o 'year'
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AdminFeature:
    """Una funcionalidad del catálogo y lo que un plan tiene de ella. `limit` None = ilimitado."""

    key: str
    description: str
    kind: str  # 'limit' o 'boolean'
    period: str | None
    enabled: bool
    limit: int | None


@dataclass(frozen=True, slots=True)
class AdminPlan:
    """Un plan con todo lo que el panel muestra y edita (MM-189)."""

    code: str
    name: str
    description: str | None
    tier: int
    is_public: bool
    subscribers: int
    prices: list[AdminPrice]
    features: list[AdminFeature]


@dataclass(frozen=True, slots=True)
class AdminChange:
    """Una fila del historial: qué tabla, qué acción y qué cambió (antes y después)."""

    occurred_at: datetime
    entity: str
    action: str
    changes: dict[str, object]
