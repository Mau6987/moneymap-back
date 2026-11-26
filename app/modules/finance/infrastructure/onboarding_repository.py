"""El SQL del estado y del cierre del onboarding (spec 007, RF-3 a RF-5).

`iam.users` no tiene RLS (el login ocurre antes de saber quién es), así que
cada consulta filtra por el usuario del token. El resto de las tablas sí la
tienen.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.domain.models import OnboardingStatus, OnboardingSummary
from app.modules.finance.infrastructure.safe_to_spend_reader import SqlSafeToSpendReader

_SELECT_STATUS = text(
    """
    SELECT users.onboarding_completed_at,
           settings.main_currency,
           (SELECT count(*)
              FROM finance.accounts AS accounts
             WHERE accounts.user_id = users.id
               AND accounts.deleted_at IS NULL
               AND accounts.archived_at IS NULL) AS accounts,
           (SELECT count(*)
              FROM finance.recurring_rules AS rules
              JOIN finance.categories AS categories
                ON categories.user_id = rules.user_id AND categories.id = rules.category_id
             WHERE rules.user_id = users.id AND rules.deleted_at IS NULL AND rules.is_active
               AND categories.kind = 'income') AS income_rules,
           (SELECT count(*)
              FROM finance.recurring_rules AS rules
              JOIN finance.categories AS categories
                ON categories.user_id = rules.user_id AND categories.id = rules.category_id
             WHERE rules.user_id = users.id AND rules.deleted_at IS NULL AND rules.is_active
               AND categories.kind = 'expense') AS expense_rules
    FROM iam.users AS users
    LEFT JOIN finance.user_settings AS settings ON settings.user_id = users.id
    WHERE users.id = :user_id
    """
)

_MARK_COMPLETED = text(
    """
    UPDATE iam.users
    SET onboarding_completed_at = now()
    WHERE id = :user_id AND onboarding_completed_at IS NULL
    """
)


class SqlOnboardingRepository:
    """Implementa `OnboardingRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def status(self, user_id: UUID) -> OnboardingStatus:
        row = (await self._session.execute(_SELECT_STATUS, {"user_id": user_id})).mappings().one()
        return OnboardingStatus(
            completed_at=row["onboarding_completed_at"],
            main_currency=row["main_currency"],
            accounts=row["accounts"],
            income_rules=row["income_rules"],
            expense_rules=row["expense_rules"],
        )

    async def summary(self, user_id: UUID) -> OnboardingSummary:
        """Safe to Spend de la moneda principal (spec 003): el mismo cálculo, no una copia."""
        computed = await SqlSafeToSpendReader(self._session).compute(user_id, None)
        if computed is None:  # complete_onboarding ya comprobó que hay moneda principal
            raise LookupError("El usuario no tiene moneda principal")
        return OnboardingSummary(
            currency=computed.currency,
            period_starts_on=computed.period_starts_on,
            period_ends_on=computed.period_ends_on,
            income=computed.income,
            committed=computed.pending_recurring,
            balance=computed.current_balance,
            planned_savings=computed.planned_savings,
            goal_contributions=computed.goal_contributions,
            safe_to_spend=computed.amount,
        )

    async def mark_completed(self, user_id: UUID) -> None:
        await self._session.execute(_MARK_COMPLETED, {"user_id": user_id})
