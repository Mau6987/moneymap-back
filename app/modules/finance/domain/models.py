"""Modelos del módulo de finanzas.

Los read models que devuelven los comandos y las consultas. No hay agregados
con reglas: las del dinero las aplica PostgreSQL (constitución §3) y el módulo
solo las traduce.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.core.money import Money


@dataclass(frozen=True, slots=True)
class NewAccount:
    """Una cuenta por crear, con lo que ya validó el esquema (RF-3)."""

    name: str
    type: str
    currency: str
    opening_balance: Decimal
    institution_code: str | None = None
    last4: str | None = None


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """La cuenta como quedó guardada; el saldo lo puso la base.

    El banco y los últimos 4 dígitos solo los trae la lista (RF-23).
    """

    id: UUID
    name: str
    type: str
    currency: str
    current_balance: Money
    is_default: bool
    created_at: datetime
    archived_at: datetime | None = None
    institution_code: str | None = None
    last4: str | None = None


@dataclass(frozen=True, slots=True)
class BalanceTotal:
    """Los totales de una moneda (RF-15): nunca se suman monedas distintas."""

    currency: str
    is_main_currency: bool
    total: Money
    cash_total: Money
    card_total: Money
    accounts: int


@dataclass(frozen=True, slots=True)
class AccountChanges:
    """Lo que se puede corregir de una cuenta (RF-14). `None` = no se envió."""

    name: str | None = None
    currency: str | None = None
    archived: bool | None = None
    # BUG-036: corregir el saldo inicial (en el onboarding, al volver a un paso).
    opening_balance: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UserSettings:
    """La configuración financiera del usuario (RF-1)."""

    main_currency: str
    period_type: str
    period_start_day: int
    planned_savings: Money


@dataclass(frozen=True, slots=True)
class SettingsChanges:
    """Lo que se puede cambiar de la configuración (spec 003, RF-7). `None` = no se envió."""

    main_currency: str | None = None
    period_type: str | None = None
    period_start_day: int | None = None
    planned_savings: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SafeToSpend:
    """Cuánto queda libre en el periodo, en una sola moneda (spec 003, RF-1 y RF-2).

    `income` no entra en la cuenta: lo muestra el resumen del onboarding.
    """

    currency: str
    period_starts_on: date
    period_ends_on: date
    current_balance: Money
    pending_recurring: Money
    planned_savings: Money
    goal_contributions: Money
    income: Money

    @property
    def amount(self) -> Money:
        """RF-2: saldo − recurrentes pendientes − ahorro planificado − aportes a metas."""
        return self.current_balance - self.pending_recurring - self.planned_savings - self.goal_contributions


@dataclass(frozen=True, slots=True)
class CurrencyOption:
    """Una moneda del selector (RF-2): las del usuario primero."""

    code: str
    name: str
    symbol: str
    decimals: int
    is_active: bool
    is_mine: bool
    is_main_currency: bool


@dataclass(frozen=True, slots=True)
class NewTransaction:
    """Un movimiento por registrar (RF-6, RF-10).

    `kind` es `income`, `expense` o `transfer`; `currency` va vacío cuando la
    pone la cuenta, que es lo normal.
    """

    kind: str
    account_id: UUID
    amount: Decimal
    occurred_on: date
    category_id: UUID | None = None
    transfer_account_id: UUID | None = None
    currency: str | None = None
    description: str = ""
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class TransactionChanges:
    """Lo que se puede corregir de un movimiento (RF-13). `None` = no se envió.

    La moneda no se corrige: es la de su cuenta.
    """

    account_id: UUID | None = None
    category_id: UUID | None = None
    amount: Decimal | None = None
    occurred_on: date | None = None
    description: str | None = None
    transfer_account_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """El movimiento y el saldo que quedó en cada cuenta involucrada (RF-6)."""

    id: UUID
    kind: str
    account_id: UUID
    category_id: UUID | None
    transfer_account_id: UUID | None
    amount: Money
    occurred_on: date
    description: str
    source: str
    created_at: datetime
    account_balance: Money
    transfer_account_balance: Money | None


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    """Qué movimientos muestra el historial (RF-26 y RF-32). None es "sin filtro".

    `search` busca en la descripción sin distinguir mayúsculas; las fechas
    incluyen los dos extremos.
    """

    account_id: UUID | None = None
    category_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None
    search: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionCursor:
    """Dónde sigue el historial (RF-26): el último movimiento de la página anterior."""

    occurred_on: date
    id: UUID


@dataclass(frozen=True, slots=True)
class TransactionItem:
    """Un movimiento del historial (RF-26), sin saldos: esos los da `GET /v1/accounts`."""

    id: UUID
    kind: str
    account_id: UUID
    category_id: UUID | None
    transfer_account_id: UUID | None
    amount: Money
    occurred_on: date
    description: str
    source: str
    created_at: datetime
    # Spec 014: si tiene la foto del comprobante. Solo lo calcula el historial.
    has_receipt: bool = False


@dataclass(frozen=True, slots=True)
class TransactionPage:
    """Una página del historial; sin `next_cursor`, no hay más."""

    items: Sequence[TransactionItem]
    next_cursor: TransactionCursor | None


@dataclass(frozen=True, slots=True)
class CountryOption:
    """Un país del catálogo con su moneda local: la moneda sugerida del onboarding."""

    code: str
    name: str
    currency: str | None


@dataclass(frozen=True, slots=True)
class Institution:
    """Un banco o billetera del catálogo, para elegir el emisor de una tarjeta."""

    code: str
    name: str
    short_name: str
    kind: str


@dataclass(frozen=True, slots=True)
class CategoryRecord:
    """Una categoría del usuario (spec 007, RF-6). `flow_group` solo en gastos."""

    id: UUID
    name: str
    type: str
    flow_group: str | None
    icon: str
    color: str
    template_key: str | None


@dataclass(frozen=True, slots=True)
class NewCategory:
    """Una categoría que crea el usuario (spec 007, RF-7). `flow_group` solo en gastos."""

    name: str
    type: str
    flow_group: str | None
    icon: str
    color: str


@dataclass(frozen=True, slots=True)
class CategoryChanges:
    """Lo que se corrige de una categoría (RF-10): None es "no se envió"."""

    name: str | None = None
    type: str | None = None
    flow_group: str | None = None
    icon: str | None = None
    color: str | None = None


@dataclass(frozen=True, slots=True)
class NewRecurringRule:
    """Un ingreso o gasto que se repite. Ingreso o gasto sale de su categoría.

    Sin `account_id` ni `currency`, va a la cuenta por defecto del usuario. Con
    solo `currency`, queda sin cuenta: se elige al pagar (BUG-027).
    """

    account_id: UUID | None
    category_id: UUID
    amount: Decimal
    description: str
    frequency: str
    start_date: date | None = None
    auto_post: bool = False
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class RecurringRuleChanges:
    """Lo que se puede corregir de un recurrente (RF-30). `None` = no se envió.

    La moneda no se corrige: es la de su cuenta.
    """

    account_id: UUID | None = None
    category_id: UUID | None = None
    amount: Decimal | None = None
    description: str | None = None
    frequency: str | None = None
    auto_post: bool | None = None


@dataclass(frozen=True, slots=True)
class RecurringRuleRecord:
    """El recurrente como quedó guardado. Sin cuenta, la cuenta se elige al pagar."""

    id: UUID
    account_id: UUID | None
    category_id: UUID
    type: str
    amount: Money
    description: str
    frequency: str
    next_due_on: date
    auto_post: bool = False
    has_receipt: bool = False
    # RF-23: lo calcula solo la lista; vacío, se entiende `next_due_on`.
    pending_dates: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class RecurringPayment:
    """Un pago de un recurrente (spec 003, RF-17). `None` = el monto del recurrente y la fecha de hoy.

    `account_id` es la cuenta con la que se paga; sin ella, la del recurrente (BUG-027).
    """

    amount: Decimal | None = None
    occurred_on: date | None = None
    account_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RecurringPaymentRecord:
    """El movimiento que registró el pago y el recurrente con su próximo vencimiento."""

    transaction: TransactionItem
    rule: RecurringRuleRecord


@dataclass(frozen=True, slots=True)
class OnboardingStatus:
    """Hasta dónde llegó el onboarding (spec 007, RF-3): la app retoma desde ahí."""

    completed_at: datetime | None
    main_currency: str | None
    accounts: int
    income_rules: int
    expense_rules: int


@dataclass(frozen=True, slots=True)
class OnboardingSummary:
    """Resumen de "Tu MoneyMap está listo" (spec 007, RF-4), en la moneda principal.

    Safe to Spend = saldo − comprometido − ahorro planificado − aportes a metas
    del periodo (PRD §6.10).
    """

    currency: str
    period_starts_on: date
    period_ends_on: date
    income: Money
    committed: Money
    balance: Money
    planned_savings: Money
    goal_contributions: Money
    safe_to_spend: Money
