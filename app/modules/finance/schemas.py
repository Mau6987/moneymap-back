"""Esquemas HTTP del módulo de finanzas: Pydantic, nada más.

El esquema valida la forma de lo que entra (código de moneda, últimos 4
dígitos, tipo de cuenta) y arma la respuesta. Las reglas del dinero no están
aquí: las aplica la base de datos (constitución §3).
"""

import base64
import binascii
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.core.validation import CurrencyCode, MoneyAmount
from app.modules.finance.domain.errors import InvalidCursor
from app.modules.finance.domain.models import (
    AccountChanges,
    AccountRecord,
    BalanceTotal,
    CategoryChanges,
    CategoryRecord,
    CountryOption,
    CurrencyOption,
    Institution,
    NewAccount,
    NewCategory,
    NewRecurringRule,
    NewTransaction,
    OnboardingStatus,
    OnboardingSummary,
    RecurringPayment,
    RecurringPaymentRecord,
    RecurringRuleChanges,
    RecurringRuleRecord,
    SafeToSpend,
    SettingsChanges,
    TransactionChanges,
    TransactionCursor,
    TransactionItem,
    TransactionPage,
    TransactionRecord,
    UserSettings,
)

# Espeja el CHECK de finance.accounts.name.
ACCOUNT_NAME_MAX_LENGTH = 80

# Espeja el CHECK de finance.transactions.description.
TRANSACTION_DESCRIPTION_MAX_LENGTH = 200

# Espeja numeric(19,4): más dígitos desbordan la columna y saldrían como un 500.
AMOUNT_MAX_DIGITS = 19
AMOUNT_MAX_DECIMALS = 4


def _clean_text(value: str) -> str:
    """Colapsa los espacios y rechaza el texto que queda vacío."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("No puede quedar vacío")
    return cleaned


def _clean_description(value: str) -> str:
    """La descripción de un movimiento es opcional (BUG-050).

    Se guarda sin espacios de más; si tiene algo, necesita al menos una letra o
    un número: "-", "..." o un emoji solo no (BUG-004, BUG-005).
    """
    cleaned = " ".join(value.split())
    if cleaned and not any(char.isalnum() for char in cleaned):
        raise ValueError("La descripción necesita al menos una letra o un número, no solo símbolos o emojis")
    return cleaned


TransactionDescription = Annotated[
    str, Field(max_length=TRANSACTION_DESCRIPTION_MAX_LENGTH), AfterValidator(_clean_description)
]


def _clean_name(value: str) -> str:
    """Como `_clean_text`, y además pide al menos una letra o un número (BUG-003).

    "Netflix", "Luz 2" o "Netflix 🎬" pasan; "-", "..." o un emoji solo no.
    """
    cleaned = _clean_text(value)
    if not any(char.isalnum() for char in cleaned):
        raise ValueError("Tiene que tener al menos una letra o un número, no solo símbolos o emojis")
    return cleaned


class AccountCreate(BaseModel):
    """RF-3: nombre, tipo, moneda y saldo inicial de una cuenta nueva.

    Solo hay dos tipos de cuenta y son estables (constitución §2, y el CHECK de
    `finance.cards` ya fija `card`). El `Literal` evita que un tipo inventado
    llegue a la base y vuelva como un error sin traducir.
    """

    name: str = Field(min_length=1, max_length=80, examples=["Efectivo Bs"])
    type: Literal["cash", "card"] = Field(examples=["cash"])
    currency: CurrencyCode = Field(examples=["BOB"])
    opening_balance: MoneyAmount = Field(
        default=Decimal("0.00"),
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["2500.00"],
    )
    institution_code: str | None = Field(default=None, examples=["bo.bnb"])
    last4: str | None = Field(default=None, pattern=r"^[0-9]{4}$", examples=["1234"])

    @model_validator(mode="after")
    def _card_needs_last4(self) -> "AccountCreate":
        """Una tarjeta siempre se reconoce por sus últimos 4 (QA BUG-052)."""
        if self.type == "card" and self.last4 is None:
            raise ValueError("Una tarjeta necesita los últimos 4 dígitos")
        return self

    def to_new_account(self) -> NewAccount:
        """Pasa al modelo del dominio: el caso de uso no depende de Pydantic."""
        return NewAccount(
            name=self.name,
            type=self.type,
            currency=self.currency,
            opening_balance=self.opening_balance,
            institution_code=self.institution_code,
            last4=self.last4,
        )


class AccountRead(BaseModel):
    """RF-3: la cuenta como quedó guardada, con el saldo que calculó la base."""

    id: UUID
    name: str
    type: str
    currency: str
    current_balance: MoneyAmount
    is_default: bool
    created_at: datetime
    archived_at: datetime | None = Field(description="Cuándo se archivó; null si está activa")

    @classmethod
    def from_record(cls, record: AccountRecord) -> "AccountRead":
        return cls(
            id=record.id,
            name=record.name,
            type=record.type,
            currency=record.currency,
            current_balance=record.current_balance.amount,
            is_default=record.is_default,
            created_at=record.created_at,
            archived_at=record.archived_at,
        )


class AccountListItemRead(AccountRead):
    """RF-23: la cuenta de la lista; si es tarjeta, con su banco y sus últimos 4 dígitos."""

    institution_code: str | None
    last4: str | None

    @classmethod
    def from_record(cls, record: AccountRecord) -> "AccountListItemRead":
        return cls(
            **AccountRead.from_record(record).model_dump(),
            institution_code=record.institution_code,
            last4=record.last4,
        )


class BalanceTotalRead(BaseModel):
    """RF-15: una fila por moneda. Nunca suma monedas distintas."""

    currency: str
    is_main_currency: bool
    total: MoneyAmount
    cash_total: MoneyAmount
    card_total: MoneyAmount
    accounts: int

    @classmethod
    def from_record(cls, record: BalanceTotal) -> "BalanceTotalRead":
        return cls(
            currency=record.currency,
            is_main_currency=record.is_main_currency,
            total=record.total.amount,
            cash_total=record.cash_total.amount,
            card_total=record.card_total.amount,
            accounts=record.accounts,
        )


class AccountUpdate(BaseModel):
    """RF-14: se corrige solo lo que se envía.

    La moneda solo se puede corregir mientras la cuenta no se haya usado.
    `archived` la archiva (true) o la desarchiva (false). `opening_balance`
    corrige el saldo inicial: la base mueve el saldo actual por la diferencia.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=ACCOUNT_NAME_MAX_LENGTH,
        examples=["Efectivo Bs"],
    )
    currency: CurrencyCode | None = Field(default=None, examples=["USD"])
    archived: bool | None = Field(default=None, examples=[True])
    opening_balance: MoneyAmount | None = Field(
        default=None,
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["2500.00"],
    )

    def to_changes(self) -> AccountChanges:
        return AccountChanges(
            name=self.name,
            currency=self.currency,
            archived=self.archived,
            opening_balance=self.opening_balance,
        )


class SettingsUpdate(BaseModel):
    """RF-1 y spec 003, RF-7: se cambia solo lo que se envía.

    La primera vez va `main_currency` (paso 1 del onboarding). El día de inicio
    depende del periodo: semanal de 0 (domingo) a 6, quincenal de 1 a 13 (la
    segunda quincena empieza el día + 15) y mensual de 1 a 28; lo valida la base.
    """

    main_currency: CurrencyCode | None = Field(default=None, examples=["BOB"])
    period_type: Literal["weekly", "semi_monthly", "monthly"] | None = Field(default=None, examples=["monthly"])
    period_start_day: int | None = Field(default=None, ge=0, le=28, examples=[25])
    planned_savings: MoneyAmount | None = Field(
        default=None,
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["500.00"],
    )

    @model_validator(mode="after")
    def _something(self) -> "SettingsUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Mandá al menos un campo")
        return self

    def to_changes(self) -> SettingsChanges:
        return SettingsChanges(
            main_currency=self.main_currency,
            period_type=self.period_type,
            period_start_day=self.period_start_day,
            planned_savings=self.planned_savings,
        )


class SettingsRead(BaseModel):
    """RF-1: la configuración financiera como quedó."""

    main_currency: str
    period_type: str
    period_start_day: int
    planned_savings: MoneyAmount

    @classmethod
    def from_record(cls, settings: UserSettings) -> "SettingsRead":
        return cls(
            main_currency=settings.main_currency,
            period_type=settings.period_type,
            period_start_day=settings.period_start_day,
            planned_savings=settings.planned_savings.amount,
        )


class SafeToSpendBreakdownRead(BaseModel):
    """Spec 003, RF-1: los cuatro conceptos, en la moneda del cálculo."""

    current_balance: MoneyAmount
    pending_recurring: MoneyAmount
    planned_savings: MoneyAmount
    goal_contributions: MoneyAmount


class SafeToSpendRead(BaseModel):
    """Spec 003, RF-1: cuánto queda libre en el periodo, con su desglose.

    Es una estimación (constitución §8): `amount` puede ser negativo si las
    obligaciones pasan el saldo.
    """

    currency: str
    period_starts_on: date
    period_ends_on: date
    amount: MoneyAmount
    breakdown: SafeToSpendBreakdownRead

    @classmethod
    def from_record(cls, computed: SafeToSpend) -> "SafeToSpendRead":
        return cls(
            currency=computed.currency,
            period_starts_on=computed.period_starts_on,
            period_ends_on=computed.period_ends_on,
            amount=computed.amount.amount,
            breakdown=SafeToSpendBreakdownRead(
                current_balance=computed.current_balance.amount,
                pending_recurring=computed.pending_recurring.amount,
                planned_savings=computed.planned_savings.amount,
                goal_contributions=computed.goal_contributions.amount,
            ),
        )


class TransactionCreate(BaseModel):
    """RF-6 a RF-8 y RF-10 a RF-12: un gasto, un ingreso o una transferencia.

    Acá se valida solo la forma —qué campos van juntos—; la moneda de la cuenta,
    los decimales del monto y la cuenta de destino los aplica la base.
    """

    kind: Literal["income", "expense", "transfer"] = Field(examples=["expense"])
    account_id: UUID
    amount: MoneyAmount = Field(examples=["25.50"])
    occurred_on: date = Field(examples=["2026-10-15"])
    category_id: UUID | None = Field(default=None, description="Obligatoria salvo en una transferencia")
    transfer_account_id: UUID | None = Field(default=None, description="Solo en una transferencia")
    currency: CurrencyCode | None = Field(
        default=None, description="La pone la cuenta; se acepta para avisar si no coincide"
    )
    description: TransactionDescription = Field(default="", examples=["Almuerzo"])
    source: Literal["manual", "quick_add", "voice", "scan", "recurring", "onboarding", "adjustment"] = "manual"

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "TransactionCreate":
        if self.kind == "transfer":
            if self.category_id is not None:
                raise ValueError("Una transferencia no lleva categoría")
            if self.transfer_account_id is None:
                raise ValueError("Una transferencia necesita la cuenta de destino")
        elif self.category_id is None:
            raise ValueError("Un gasto o un ingreso necesitan categoría")
        elif self.transfer_account_id is not None:
            raise ValueError("Solo una transferencia lleva cuenta de destino")
        return self

    def to_new_transaction(self) -> NewTransaction:
        return NewTransaction(
            kind=self.kind,
            account_id=self.account_id,
            amount=self.amount,
            occurred_on=self.occurred_on,
            category_id=self.category_id,
            transfer_account_id=self.transfer_account_id,
            currency=self.currency,
            description=self.description,
            source=self.source,
        )


class TransactionUpdate(BaseModel):
    """RF-13: se corrige solo lo que se envía.

    La moneda no se cambia: es la de su cuenta, y la base avisa si la cuenta
    nueva es de otra.
    """

    account_id: UUID | None = None
    category_id: UUID | None = None
    amount: MoneyAmount | None = None
    occurred_on: date | None = None
    description: TransactionDescription | None = None
    transfer_account_id: UUID | None = None

    def to_changes(self) -> TransactionChanges:
        return TransactionChanges(
            account_id=self.account_id,
            category_id=self.category_id,
            amount=self.amount,
            occurred_on=self.occurred_on,
            description=self.description,
            transfer_account_id=self.transfer_account_id,
        )


class TransactionRead(BaseModel):
    """RF-6: el movimiento y el saldo nuevo de cada cuenta involucrada."""

    id: UUID
    kind: str
    account_id: UUID
    category_id: UUID | None
    transfer_account_id: UUID | None
    amount: MoneyAmount
    currency: str
    occurred_on: date
    description: str
    source: str
    created_at: datetime
    account_balance: MoneyAmount
    transfer_account_balance: MoneyAmount | None

    @classmethod
    def from_record(cls, record: TransactionRecord) -> "TransactionRead":
        destination = record.transfer_account_balance
        return cls(
            id=record.id,
            kind=record.kind,
            account_id=record.account_id,
            category_id=record.category_id,
            transfer_account_id=record.transfer_account_id,
            amount=record.amount.amount,
            currency=record.amount.currency,
            occurred_on=record.occurred_on,
            description=record.description,
            source=record.source,
            created_at=record.created_at,
            account_balance=record.account_balance.amount,
            transfer_account_balance=None if destination is None else destination.amount,
        )


# Cuántos movimientos trae una página del historial si la app no lo pide.
TRANSACTION_PAGE_DEFAULT_SIZE = 50
TRANSACTION_PAGE_MAX_SIZE = 100


def encode_cursor(cursor: TransactionCursor) -> str:
    """El cursor viaja opaco: la app lo devuelve tal cual, sin interpretarlo."""
    return base64.urlsafe_b64encode(f"{cursor.occurred_on.isoformat()}_{cursor.id}".encode()).decode()


def decode_cursor(value: str) -> TransactionCursor:
    """El cursor que dio `encode_cursor`; cualquier otro texto es 422 `invalid_cursor`."""
    try:
        occurred_on, transaction_id = base64.urlsafe_b64decode(value.encode()).decode().split("_")
        return TransactionCursor(occurred_on=date.fromisoformat(occurred_on), id=UUID(transaction_id))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursor from error


class TransactionItemRead(BaseModel):
    """RF-26: un movimiento del historial, en la moneda de su cuenta."""

    id: UUID
    kind: str
    account_id: UUID
    category_id: UUID | None
    transfer_account_id: UUID | None
    amount: MoneyAmount
    currency: str
    occurred_on: date
    description: str
    source: str
    created_at: datetime
    has_receipt: bool = Field(description="Si el gasto tiene la foto del comprobante (spec 014)")

    @classmethod
    def from_record(cls, item: TransactionItem) -> "TransactionItemRead":
        return cls(
            id=item.id,
            kind=item.kind,
            account_id=item.account_id,
            category_id=item.category_id,
            transfer_account_id=item.transfer_account_id,
            amount=item.amount.amount,
            currency=item.amount.currency,
            occurred_on=item.occurred_on,
            description=item.description,
            source=item.source,
            created_at=item.created_at,
            has_receipt=item.has_receipt,
        )


class TransactionPageRead(BaseModel):
    """RF-26: una página del historial. Con `next_cursor` null, no hay más."""

    items: list[TransactionItemRead]
    next_cursor: str | None

    @classmethod
    def from_record(cls, page: TransactionPage) -> "TransactionPageRead":
        cursor = page.next_cursor
        return cls(
            items=[TransactionItemRead.from_record(item) for item in page.items],
            next_cursor=None if cursor is None else encode_cursor(cursor),
        )


class CurrencyRead(BaseModel):
    """RF-2 y RF-20: una moneda del selector.

    `is_active` y `is_mine` no los pide el RF: sin ellos la app no puede
    desactivar en pantalla una moneda que el catálogo ya retiró (RF-20) ni
    separar Mis monedas.
    """

    code: str
    name: str
    symbol: str
    decimals: int
    is_active: bool
    is_mine: bool
    is_main_currency: bool

    @classmethod
    def from_record(cls, currency: CurrencyOption) -> "CurrencyRead":
        return cls(
            code=currency.code,
            name=currency.name,
            symbol=currency.symbol,
            decimals=currency.decimals,
            is_active=currency.is_active,
            is_mine=currency.is_mine,
            is_main_currency=currency.is_main_currency,
        )


class CountryRead(BaseModel):
    """Un país con su moneda local: el onboarding la sugiere como principal."""

    code: str
    name: str
    currency: str | None

    @classmethod
    def from_record(cls, country: CountryOption) -> "CountryRead":
        return cls(code=country.code, name=country.name, currency=country.currency)


class InstitutionRead(BaseModel):
    """Un banco o billetera del catálogo (`institution_code` de una tarjeta)."""

    code: str
    name: str
    short_name: str
    kind: str

    @classmethod
    def from_record(cls, institution: Institution) -> "InstitutionRead":
        return cls(
            code=institution.code,
            name=institution.name,
            short_name=institution.short_name,
            kind=institution.kind,
        )


CategoryType = Literal["income", "expense"]
FlowGroup = Literal["needs", "lifestyle"]

CATEGORY_NAME_MAX_LENGTH = 60


def _clean_category_name(value: str) -> str:
    """Una letra o un número como mínimo y ningún emoji: la categoría ya tiene su ícono (BUG-010, BUG-011)."""
    cleaned = _clean_name(value)
    if any(_is_emoji(char) for char in cleaned):
        raise ValueError("El nombre de una categoría va sin emojis: el ícono ya la identifica")
    return cleaned


def _is_emoji(char: str) -> bool:
    """Los bloques de emojis: pictogramas, técnicos (⌚, ⏰), símbolos, dingbats, banderas y el selector de variante."""
    code = ord(char)
    return code == 0xFE0F or any(start <= code <= end for start, end in _EMOJI_BLOCKS)


_EMOJI_BLOCKS = ((0x1F000, 0x1FAFF), (0x2300, 0x23FF), (0x2600, 0x27BF), (0x2B00, 0x2BFF))


CategoryName = Annotated[str, Field(max_length=CATEGORY_NAME_MAX_LENGTH), AfterValidator(_clean_category_name)]
CategoryIcon = Annotated[str, Field(min_length=1, max_length=40, examples=["pets"])]
CategoryColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#F59E0B"])]


class CategoryCreate(BaseModel):
    """Spec 007, RF-7 a RF-9: un gasto lleva su grupo del Money Flow; un ingreso, no.

    Sin ícono ni color quedan los de la base: `label` y `#6B7280`.
    """

    name: CategoryName = Field(examples=["Mascotas"])
    type: CategoryType = Field(examples=["expense"])
    money_flow_group: FlowGroup | None = Field(default=None, examples=["lifestyle"])
    icon: CategoryIcon = "label"
    color: CategoryColor = "#6B7280"

    @model_validator(mode="after")
    def _check_flow_group(self) -> "CategoryCreate":
        if self.type == "expense" and self.money_flow_group is None:
            raise ValueError("Un gasto necesita su grupo del Money Flow: needs o lifestyle")
        if self.type == "income" and self.money_flow_group is not None:
            raise ValueError("Un ingreso no lleva grupo del Money Flow")
        return self

    def to_new_category(self) -> NewCategory:
        return NewCategory(
            name=self.name,
            type=self.type,
            flow_group=self.money_flow_group,
            icon=self.icon,
            color=self.color,
        )


class CategoryUpdate(BaseModel):
    """Spec 007, RF-10 y RF-11: se corrige solo lo que se envía.

    Pasar a ingreso quita el grupo; pasar a gasto necesita `money_flow_group`.
    El tipo no cambia si la categoría ya tiene movimientos o recurrentes.
    """

    name: CategoryName | None = Field(default=None, examples=["Mascotas"])
    type: CategoryType | None = None
    money_flow_group: FlowGroup | None = None
    icon: CategoryIcon | None = None
    color: CategoryColor | None = None

    @model_validator(mode="after")
    def _check_flow_group(self) -> "CategoryUpdate":
        if self.type == "income" and self.money_flow_group is not None:
            raise ValueError("Un ingreso no lleva grupo del Money Flow")
        return self

    def to_changes(self) -> CategoryChanges:
        return CategoryChanges(
            name=self.name,
            type=self.type,
            flow_group=self.money_flow_group,
            icon=self.icon,
            color=self.color,
        )


class CategoryRead(BaseModel):
    """Spec 007, RF-6: la categoría con su grupo del Money Flow, su ícono y su color.

    `template_key` dice de qué categoría inicial salió (`salary`, `housing`…), o
    null si la creó el usuario: así la app la reconoce sin depender del nombre,
    que el usuario puede editar.
    """

    id: UUID
    name: str
    type: CategoryType
    money_flow_group: FlowGroup | None
    icon: str
    color: str
    template_key: str | None

    @classmethod
    def from_record(cls, category: CategoryRecord) -> "CategoryRead":
        return cls(
            id=category.id,
            name=category.name,
            type=category.type,
            money_flow_group=category.flow_group,
            icon=category.icon,
            color=category.color,
            template_key=category.template_key,
        )


class RecurringRuleCreate(BaseModel):
    """Un ingreso o gasto que se repite: el sueldo, el alquiler.

    Ingreso o gasto sale de la categoría; la moneda, de la cuenta (spec 002,
    RF-21). Sin `account_id` ni `currency`, va a la cuenta por defecto. Con solo
    `currency`, queda sin cuenta y la cuenta se elige al pagar (BUG-027). Sin
    `start_date`, el primer vencimiento es hoy.
    """

    account_id: UUID | None = None
    currency: CurrencyCode | None = Field(default=None, description="Sin cuenta: la moneda del gasto fijo")
    category_id: UUID
    amount: MoneyAmount = Field(
        gt=0,
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["450.00"],
    )
    description: Annotated[str, Field(min_length=1, max_length=120), AfterValidator(_clean_name)] = Field(
        examples=["Alquiler"]
    )
    frequency: Literal["weekly", "biweekly", "monthly", "yearly"] = "monthly"
    start_date: date | None = None
    auto_post: bool = Field(
        default=False,
        description="Obsoleto: los recurrentes son recordatorios y siempre se guarda false",
    )

    def to_new_rule(self) -> NewRecurringRule:
        return NewRecurringRule(
            account_id=self.account_id,
            category_id=self.category_id,
            amount=self.amount,
            description=self.description,
            frequency=self.frequency,
            start_date=self.start_date,
            auto_post=False,
            currency=self.currency,
        )


class RecurringRuleUpdate(BaseModel):
    """RF-30: se corrige solo lo que se envía; la moneda es la de la cuenta."""

    account_id: UUID | None = None
    category_id: UUID | None = None
    amount: MoneyAmount | None = Field(
        default=None,
        gt=0,
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["480.00"],
    )
    description: Annotated[str, Field(min_length=1, max_length=120), AfterValidator(_clean_name)] | None = None
    frequency: Literal["weekly", "biweekly", "monthly", "yearly"] | None = None
    auto_post: bool | None = Field(default=None, description="Obsoleto: se ignora")

    def to_changes(self) -> RecurringRuleChanges:
        return RecurringRuleChanges(
            account_id=self.account_id,
            category_id=self.category_id,
            amount=self.amount,
            description=self.description,
            frequency=self.frequency,
            auto_post=None,
        )


class RecurringRuleRead(BaseModel):
    """El recurrente como quedó, en su moneda (la de su cuenta, si tiene)."""

    id: UUID
    account_id: UUID | None = Field(description="Cuenta sugerida; null: se elige al pagar (BUG-027)")
    category_id: UUID
    type: CategoryType
    amount: MoneyAmount
    currency: str
    description: str
    frequency: str
    next_due_on: date
    auto_post: bool
    has_receipt: bool = Field(default=False, description="Tiene la foto del comprobante (spec 014 + recurrentes)")
    pending_dates: list[date] = Field(
        description="Las veces por pagar, la más vieja primero. La primera es `next_due_on`, la única que se puede "
        "pagar. Solo `GET /v1/recurring-rules` trae las siguientes (spec 003, RF-23)",
    )

    @classmethod
    def from_record(cls, rule: RecurringRuleRecord) -> "RecurringRuleRead":
        return cls(
            id=rule.id,
            account_id=rule.account_id,
            category_id=rule.category_id,
            type=rule.type,
            amount=rule.amount.amount,
            currency=rule.amount.currency,
            description=rule.description,
            frequency=rule.frequency,
            next_due_on=rule.next_due_on,
            auto_post=rule.auto_post,
            has_receipt=rule.has_receipt,
            pending_dates=list(rule.pending_dates) or [rule.next_due_on],
        )


class RecurringPaymentCreate(BaseModel):
    """Spec 003, RF-17: sin campos, el monto del recurrente y la fecha de hoy."""

    amount: MoneyAmount | None = Field(
        default=None,
        gt=0,
        max_digits=AMOUNT_MAX_DIGITS,
        decimal_places=AMOUNT_MAX_DECIMALS,
        examples=["185.40"],
    )
    occurred_on: date | None = Field(default=None, examples=["2026-10-05"])
    account_id: UUID | None = Field(
        default=None,
        description="Con qué cuenta se paga, en la moneda del gasto fijo. Sin ella, la del gasto fijo (BUG-027)",
    )

    def to_payment(self) -> RecurringPayment:
        return RecurringPayment(amount=self.amount, occurred_on=self.occurred_on, account_id=self.account_id)


class RecurringPaymentRead(BaseModel):
    """Spec 003, RF-17: el movimiento registrado y el recurrente con su próximo vencimiento."""

    transaction: TransactionItemRead
    recurring_rule: RecurringRuleRead

    @classmethod
    def from_record(cls, record: RecurringPaymentRecord) -> "RecurringPaymentRead":
        return cls(
            transaction=TransactionItemRead.from_record(record.transaction),
            recurring_rule=RecurringRuleRead.from_record(record.rule),
        )


class OnboardingStatusRead(BaseModel):
    """Spec 007, RF-3: si terminó y qué pasos guardó, para retomar donde quedó."""

    completed: bool
    completed_at: datetime | None
    main_currency: str | None
    accounts: int
    income_rules: int
    expense_rules: int

    @classmethod
    def from_record(cls, status: OnboardingStatus) -> "OnboardingStatusRead":
        return cls(
            completed=status.completed_at is not None,
            completed_at=status.completed_at,
            main_currency=status.main_currency,
            accounts=status.accounts,
            income_rules=status.income_rules,
            expense_rules=status.expense_rules,
        )


class OnboardingSummaryRead(BaseModel):
    """Spec 007, RF-4 y RF-19: "Tu MoneyMap está listo", con los montos en texto."""

    currency: str
    period_starts_on: date
    period_ends_on: date
    income: MoneyAmount
    committed: MoneyAmount
    balance: MoneyAmount
    planned_savings: MoneyAmount
    goal_contributions: MoneyAmount
    safe_to_spend: MoneyAmount

    @classmethod
    def from_record(cls, summary: OnboardingSummary) -> "OnboardingSummaryRead":
        return cls(
            currency=summary.currency,
            period_starts_on=summary.period_starts_on,
            period_ends_on=summary.period_ends_on,
            income=summary.income.amount,
            committed=summary.committed.amount,
            balance=summary.balance.amount,
            planned_savings=summary.planned_savings.amount,
            goal_contributions=summary.goal_contributions.amount,
            safe_to_spend=summary.safe_to_spend.amount,
        )
