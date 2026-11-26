"""Puertos del módulo de finanzas: lo que la aplicación necesita, sin saber cómo se guarda.

La implementación vive en `infrastructure/`. La aplicación solo ve estos
`Protocol`, así puede probarse y cambiar el SQL sin tocarla.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

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
    TransactionFilters,
    TransactionItem,
    TransactionRecord,
    UserSettings,
)


class AccountRepository(Protocol):
    """Escribe y lee cuentas (RF-3, RF-14, RF-23)."""

    async def list(self, user_id: UUID, archived: bool) -> Sequence[AccountRecord]:
        """Las activas, la de por defecto primero; o solo las archivadas."""
        ...

    async def insert(self, user_id: UUID, account: NewAccount) -> AccountRecord: ...

    async def append_card(
        self,
        user_id: UUID,
        account_id: UUID,
        institution_code: str | None,
        last4: str | None,
    ) -> None: ...

    async def update(self, user_id: UUID, account_id: UUID, changes: AccountChanges) -> AccountRecord | None:
        """Corrige lo que se envió. None si la cuenta no es del usuario o no existe."""
        ...


class BalancesReader(Protocol):
    """Lee los totales por moneda (RF-15)."""

    async def totals(self, user_id: UUID) -> Sequence[BalanceTotal]: ...


class SettingsRepository(Protocol):
    """La configuración financiera del usuario (RF-1; spec 003, RF-7)."""

    async def get(self, user_id: UUID) -> UserSettings | None:
        """None si todavía no eligió la moneda principal."""
        ...

    async def save_main_currency(self, user_id: UUID, main_currency: str) -> UserSettings: ...

    async def update(self, user_id: UUID, changes: SettingsChanges) -> UserSettings | None:
        """El periodo y el ahorro planificado (spec 003, RF-7). None si todavía no hay configuración."""
        ...


class SafeToSpendReader(Protocol):
    """El cálculo de Safe to Spend (spec 003): no guarda nada, se calcula en cada consulta."""

    async def compute(self, user_id: UUID, currency: str | None) -> SafeToSpend | None:
        """En `currency`, o en la principal si no llega. None si no hay moneda principal todavía."""
        ...


class CurrenciesRepository(Protocol):
    """El selector de monedas y Mis monedas (RF-2, RF-19, RF-20, RF-28)."""

    async def options(self, user_id: UUID) -> Sequence[CurrencyOption]: ...

    async def add_to_mine(self, user_id: UUID, currency: str) -> CurrencyOption:
        """Suma la moneda a Mis monedas, si no estaba, y la devuelve como queda en el selector."""
        ...

    async def remove_from_mine(self, user_id: UUID, currency: str) -> bool:
        """Quita una moneda de Mis monedas. False si no estaba."""
        ...

    async def over_plan_limit(self, user_id: UUID, currency: str) -> bool:
        """True si sumarla pasaría el límite de monedas del plan (MM-186). Una que ya está, nunca."""
        ...


class TransactionRepository(Protocol):
    """Movimientos y transferencias (RF-6 a RF-8, RF-10 a RF-13)."""

    async def insert(self, transaction: NewTransaction, user_id: UUID) -> TransactionRecord:
        """Guarda el movimiento. Los saldos los mueve la base."""
        ...

    async def update(
        self,
        transaction_id: UUID,
        user_id: UUID,
        changes: TransactionChanges,
    ) -> TransactionRecord | None:
        """Corrige lo enviado. None si el movimiento no es del usuario o no existe."""
        ...

    async def soft_delete(self, transaction_id: UUID, user_id: UUID) -> bool:
        """Lo marca como borrado y la base devuelve el saldo. False si no estaba."""
        ...


class TransactionHistoryReader(Protocol):
    """El historial de movimientos (RF-26), del más reciente al más viejo."""

    async def page(
        self,
        user_id: UUID,
        filters: TransactionFilters,
        after: TransactionCursor | None,
        limit: int,
    ) -> Sequence[TransactionItem]:
        """Hasta `limit` movimientos después de `after`.

        Con `account_id`, también las transferencias que llegan a esa cuenta.
        """
        ...


class CatalogReader(Protocol):
    """Datos de referencia del onboarding: países y bancos."""

    async def countries(self) -> Sequence[CountryOption]: ...

    async def institutions(self, country_code: str) -> Sequence[Institution]: ...


class CategoryRepository(Protocol):
    """Las categorías del usuario (spec 007, RF-6 a RF-13)."""

    async def list(self, user_id: UUID, category_type: str | None) -> Sequence[CategoryRecord]: ...

    async def insert(self, user_id: UUID, category: NewCategory) -> CategoryRecord: ...

    async def type_in_use(self, user_id: UUID, category_id: UUID, category_type: str) -> bool:
        """True si pasarla a `category_type` dejaría movimientos o recurrentes del otro tipo."""
        ...

    async def update(self, user_id: UUID, category_id: UUID, changes: CategoryChanges) -> CategoryRecord | None:
        """None si la categoría no existe o no es del usuario."""
        ...

    async def soft_delete(self, user_id: UUID, category_id: UUID) -> bool: ...

    async def last_used_for(self, user_id: UUID, description: str, category_type: str) -> CategoryRecord | None:
        """La categoría del último movimiento con esa descripción, sin mayúsculas ni tildes."""
        ...


class RecurringRuleRepository(Protocol):
    """Ingresos y gastos que se repiten (spec 007, pasos 3 y 4; spec 002, RF-29 a RF-31)."""

    async def insert(self, user_id: UUID, rule: NewRecurringRule) -> RecurringRuleRecord | None:
        """None si la cuenta o la categoría no son del usuario."""
        ...

    async def list(self, user_id: UUID) -> Sequence[RecurringRuleRecord]:
        """Los vigentes, el que vence primero arriba."""
        ...

    async def update(self, user_id: UUID, rule_id: UUID, changes: RecurringRuleChanges) -> RecurringRuleRecord | None:
        """None si el recurrente, la cuenta o la categoría nuevas no son del usuario."""
        ...

    async def soft_delete(self, user_id: UUID, rule_id: UUID) -> bool:
        """False si no estaba."""
        ...

    async def register_payment(
        self, user_id: UUID, rule_id: UUID, payment: RecurringPayment
    ) -> RecurringPaymentRecord | None:
        """Registra el vencimiento y avanza `next_due_on` (spec 003, RF-17). None si no es del usuario o no vence."""
        ...

    async def skip_occurrence(self, user_id: UUID, rule_id: UUID) -> RecurringRuleRecord | None:
        """Avanza `next_due_on` sin registrar nada (spec 003, RF-22). None si no es del usuario o no vence."""
        ...


class OnboardingRepository(Protocol):
    """El estado y el cierre del onboarding (spec 007, RF-3 a RF-5)."""

    async def status(self, user_id: UUID) -> OnboardingStatus: ...

    async def summary(self, user_id: UUID) -> OnboardingSummary: ...

    async def mark_completed(self, user_id: UUID) -> None:
        """Marca `onboarding_completed_at` si todavía no lo estaba."""
        ...
