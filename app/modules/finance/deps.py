"""Cableado del módulo: quién construye cada pieza con la sesión de la petición.

La aplicación no conoce la infraestructura; esto es el único lugar donde se
encuentran.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.finance.domain.receipts import ReceiptStorage
from app.modules.finance.infrastructure.account_repository import SqlAccountRepository
from app.modules.finance.infrastructure.balances_reader import SqlBalancesReader
from app.modules.finance.infrastructure.catalog_reader import SqlCatalogReader
from app.modules.finance.infrastructure.category_repository import SqlCategoryRepository
from app.modules.finance.infrastructure.currencies_repository import SqlCurrenciesRepository
from app.modules.finance.infrastructure.onboarding_repository import SqlOnboardingRepository
from app.modules.finance.infrastructure.receipt_repository import SqlReceiptRepository
from app.modules.finance.infrastructure.recurring_receipt_repository import SqlRecurringReceiptRepository
from app.modules.finance.infrastructure.recurring_rule_repository import SqlRecurringRuleRepository
from app.modules.finance.infrastructure.s3_receipt_storage import s3_receipt_storage
from app.modules.finance.infrastructure.safe_to_spend_reader import SqlSafeToSpendReader
from app.modules.finance.infrastructure.settings_repository import SqlSettingsRepository
from app.modules.finance.infrastructure.transaction_history_reader import SqlTransactionHistoryReader
from app.modules.finance.infrastructure.transaction_repository import SqlTransactionRepository


def get_account_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlAccountRepository:
    return SqlAccountRepository(session)


def get_balances_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlBalancesReader:
    return SqlBalancesReader(session)


def get_settings_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlSettingsRepository:
    return SqlSettingsRepository(session)


def get_safe_to_spend_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlSafeToSpendReader:
    return SqlSafeToSpendReader(session)


def get_currencies_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlCurrenciesRepository:
    return SqlCurrenciesRepository(session)


def get_transaction_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlTransactionRepository:
    return SqlTransactionRepository(session)


def get_transaction_history_reader(
    session: Annotated[AsyncSession, Depends(current_session)],
) -> SqlTransactionHistoryReader:
    return SqlTransactionHistoryReader(session)


def get_catalog_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlCatalogReader:
    return SqlCatalogReader(session)


def get_category_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlCategoryRepository:
    return SqlCategoryRepository(session)


def get_recurring_rule_repository(
    session: Annotated[AsyncSession, Depends(current_session)],
) -> SqlRecurringRuleRepository:
    return SqlRecurringRuleRepository(session)


def get_onboarding_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlOnboardingRepository:
    return SqlOnboardingRepository(session)


def get_receipt_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlReceiptRepository:
    return SqlReceiptRepository(session)


def get_recurring_receipt_repository(
    session: Annotated[AsyncSession, Depends(current_session)],
) -> SqlRecurringReceiptRepository:
    return SqlRecurringReceiptRepository(session)


def get_receipt_storage() -> ReceiptStorage:
    return s3_receipt_storage()
