"""El SQL de Safe to Spend (spec 003, RF-1 a RF-16).

Cuatro agregados en una moneda y en el periodo vigente del usuario, con su "hoy"
en su zona horaria. Nunca se suman monedas distintas (constitución §2) y no se
guarda nada: se recalcula en cada consulta. El resumen del onboarding usa este
mismo cálculo, así la fórmula vive en un solo lugar.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import SafeToSpend

# RF-4 y el caso límite de la moneda desactivada: se pide al catálogo solo si
# el usuario no tiene cuentas en esa moneda; si las tiene, el cálculo sigue.
_ASSERT_CURRENCY = text(
    """
    SELECT catalog.assert_currency_active(:currency)
    WHERE NOT EXISTS (
        SELECT 1 FROM finance.accounts AS accounts
        WHERE accounts.user_id = :user_id AND accounts.currency = :currency AND accounts.deleted_at IS NULL)
    """
)

# Pendientes (RF-11): los recurrentes que vencen en el periodo. Al registrarse,
# `next_due_on` pasa al siguiente y dejan de contar. Un gasto fijo que no se
# pagó (su `next_due_on` quedó antes del periodo) cuenta todas sus veces sin
# pagar hasta el fin del periodo: la de octubre atrasada más la de noviembre.
# Lo de antes del periodo en que se creó el fijo no cuenta. Los ingresos fijos cuentan una
# vez, la que vence en el periodo: a propósito, para que lo que se puede gastar
# nunca salga de más (spec 003, RF-11). Aportes (RF-12): los del
# periodo, de metas vivas en esa moneda; un retiro es un aporte negativo. Los
# que salieron de una cuenta ya bajaron su saldo: no se restan otra vez.
_SELECT = text(
    """
    WITH me AS (
        SELECT coalesce(CAST(:currency AS char(3)), settings.main_currency) AS currency,
               settings.main_currency,
               coalesce(settings.planned_savings, 0) AS planned_savings,
               period.starts_on,
               period.ends_on,
               users.timezone
        FROM iam.users AS users
        LEFT JOIN finance.user_settings AS settings ON settings.user_id = users.id
        CROSS JOIN LATERAL finance.current_period(users.id, (now() AT TIME ZONE users.timezone)::date) AS period
        WHERE users.id = :user_id
    ),
    due AS (
        SELECT categories.kind, rules.is_committed, rules.amount
        FROM finance.recurring_rules AS rules
        JOIN finance.categories AS categories
          ON categories.user_id = rules.user_id AND categories.id = rules.category_id
        JOIN me ON rules.currency = me.currency
               AND rules.next_due_on BETWEEN me.starts_on AND me.ends_on
        WHERE rules.user_id = :user_id AND rules.deleted_at IS NULL AND rules.is_active
          AND (rules.end_date IS NULL OR rules.end_date >= rules.next_due_on)
    ),
    owed AS (
        -- La vez que se debe (`next_due_on`) y las que siguen hasta el fin del
        -- periodo. Lo atrasado cuenta desde el periodo en que se creó el fijo:
        -- registrar hoy un alquiler "desde enero" no arranca con un año
        -- atrasado, y el que vence el 1 y se registra el 3 sí se debe este mes.
        SELECT rules.amount
        FROM finance.recurring_rules AS rules
        JOIN finance.categories AS categories
          ON categories.user_id = rules.user_id AND categories.id = rules.category_id
        JOIN me ON rules.currency = me.currency AND rules.next_due_on <= me.ends_on
        CROSS JOIN LATERAL finance.recurring_occurrences(
            rules.start_date, rules.frequency, rules.next_due_on, me.ends_on) AS occurrence(due_on)
        WHERE rules.user_id = :user_id AND rules.deleted_at IS NULL AND rules.is_active
          AND categories.kind = 'expense' AND rules.is_committed
          AND (rules.end_date IS NULL OR rules.end_date >= occurrence.due_on)
          AND occurrence.due_on >= (
              SELECT created.starts_on
              FROM finance.current_period(rules.user_id, (rules.created_at AT TIME ZONE me.timezone)::date)
                   AS created)
    )
    SELECT me.currency,
           currencies.decimals,
           me.starts_on,
           me.ends_on,
           CASE WHEN me.currency = me.main_currency THEN me.planned_savings ELSE 0 END AS planned_savings,
           coalesce((SELECT sum(amount) FROM due WHERE kind = 'income'), 0) AS income,
           coalesce((SELECT sum(amount) FROM owed), 0) AS pending_recurring,
           coalesce((SELECT totals.total
                       FROM finance.balance_totals AS totals
                      WHERE totals.user_id = :user_id AND totals.currency = me.currency), 0) AS current_balance,
           coalesce((SELECT sum(contributions.amount)
                       FROM goals.goal_contributions AS contributions
                       JOIN goals.goals AS goals
                         ON goals.user_id = contributions.user_id AND goals.id = contributions.goal_id
                      WHERE contributions.user_id = :user_id
                        AND goals.currency = me.currency
                        AND goals.deleted_at IS NULL
                        AND goals.status NOT IN ('achieved', 'archived')
                        AND contributions.account_id IS NULL
                        AND contributions.contributed_on BETWEEN me.starts_on AND me.ends_on), 0)
               AS goal_contributions
    FROM me
    JOIN catalog.currencies AS currencies ON currencies.code = me.currency
    """
)


class SqlSafeToSpendReader:
    """Implementa `SafeToSpendReader` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compute(self, user_id: UUID, currency: str | None) -> SafeToSpend | None:
        if currency is not None:
            await self._session.execute(_ASSERT_CURRENCY, {"user_id": user_id, "currency": currency})
        params = {"user_id": user_id, "currency": currency}
        row = (await self._session.execute(_SELECT, params)).mappings().one_or_none()
        if row is None:
            return None
        code: str = row["currency"]
        decimals: int = row["decimals"]

        def money(column: str) -> Money:
            return Money(row[column], code, decimals)

        return SafeToSpend(
            currency=code,
            period_starts_on=row["starts_on"],
            period_ends_on=row["ends_on"],
            current_balance=money("current_balance"),
            pending_recurring=money("pending_recurring"),
            planned_savings=money("planned_savings"),
            goal_contributions=money("goal_contributions"),
            income=money("income"),
        )
