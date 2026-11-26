"""El SQL de `planning.budgets` (spec 009, RF-1 a RF-9).

La base aplica las reglas: categoría de gasto viva y del usuario, moneda activa,
decimales, un presupuesto por categoría y moneda, y el límite del plan
(migración 0010).
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.planning.domain.budgets import Budget, BudgetChanges, NewBudget

_INSERT = text(
    """
    INSERT INTO planning.budgets (user_id, category_id, currency, amount, alert_at_80, alert_at_100)
    SELECT :user_id, :category_id, coalesce(CAST(:currency AS char(3)), settings.main_currency), :amount,
           :alert_at_80, :alert_at_100
    FROM finance.user_settings AS settings WHERE settings.user_id = :user_id
    RETURNING id
    """
)

_UPDATE = text(
    """
    UPDATE planning.budgets
    SET amount = coalesce(CAST(:amount AS numeric), amount),
        alert_at_80 = coalesce(CAST(:alert_at_80 AS boolean), alert_at_80),
        alert_at_100 = coalesce(CAST(:alert_at_100 AS boolean), alert_at_100)
    WHERE user_id = :user_id AND id = :budget_id AND deleted_at IS NULL
    RETURNING id
    """
)

_DELETE = text(
    """
    UPDATE planning.budgets SET deleted_at = now()
    WHERE user_id = :user_id AND id = :budget_id AND deleted_at IS NULL
    RETURNING id
    """
)

# RF-3 y RF-4: el mes calendario del usuario, y solo los gastos de la categoría
# en la moneda del presupuesto.
_SELECT = text(
    """
    WITH month AS (
        SELECT (now() AT TIME ZONE users.timezone)::date AS today,
               date_trunc('month', now() AT TIME ZONE users.timezone)::date AS starts_on
        FROM iam.users AS users WHERE users.id = :user_id
    )
    SELECT budgets.id, budgets.category_id, categories.name AS category_name, budgets.amount, budgets.currency,
           budgets.alert_at_80, budgets.alert_at_100, currencies.decimals, month.today, month.starts_on,
           (month.starts_on + INTERVAL '1 month - 1 day')::date AS ends_on,
           coalesce(spent.total, 0) AS spent, daily.days, daily.totals
    FROM planning.budgets AS budgets
    CROSS JOIN month
    JOIN finance.categories AS categories
      ON categories.user_id = budgets.user_id AND categories.id = budgets.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = budgets.currency
    LEFT JOIN LATERAL (
        SELECT sum(totals.total) AS total
        FROM reports.category_totals(:user_id, month.starts_on, (month.starts_on + INTERVAL '1 month - 1 day')::date)
             AS totals
        WHERE totals.category_id = budgets.category_id AND totals.currency = budgets.currency
    ) AS spent ON true
    LEFT JOIN LATERAL (
        -- Los mismos gastos que category_totals, por día: la línea del mes.
        SELECT array_agg(by_day.occurred_on ORDER BY by_day.occurred_on) AS days,
               array_agg(by_day.total ORDER BY by_day.occurred_on) AS totals
        FROM (
            SELECT transactions.occurred_on, sum(transactions.amount) AS total
            FROM finance.transactions AS transactions
            WHERE transactions.user_id = :user_id AND transactions.deleted_at IS NULL
              AND transactions.kind = 'expense'
              AND transactions.category_id = budgets.category_id AND transactions.currency = budgets.currency
              AND transactions.occurred_on BETWEEN month.starts_on
                                               AND (month.starts_on + INTERVAL '1 month - 1 day')::date
            GROUP BY transactions.occurred_on
        ) AS by_day
    ) AS daily ON true
    WHERE budgets.user_id = :user_id AND budgets.deleted_at IS NULL
      AND (CAST(:budget_id AS uuid) IS NULL OR budgets.id = :budget_id)
    ORDER BY categories.name, budgets.currency
    """
)


class SqlBudgetRepository:
    """Implementa `BudgetRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, budget: NewBudget) -> Budget:
        params = {
            "user_id": user_id,
            "category_id": budget.category_id,
            "currency": budget.currency,
            "amount": budget.amount,
            "alert_at_80": budget.alert_at_80,
            "alert_at_100": budget.alert_at_100,
        }
        budget_id: UUID = (await self._session.execute(_INSERT, params)).scalar_one()
        return await self._get(user_id, budget_id)

    async def list(self, user_id: UUID) -> Sequence[Budget]:
        rows = await self._session.execute(_SELECT, {"user_id": user_id, "budget_id": None})
        return [_to_budget(row) for row in rows.mappings()]

    async def update(self, user_id: UUID, budget_id: UUID, changes: BudgetChanges) -> Budget | None:
        params = {
            "user_id": user_id,
            "budget_id": budget_id,
            "amount": changes.amount,
            "alert_at_80": changes.alert_at_80,
            "alert_at_100": changes.alert_at_100,
        }
        if (await self._session.execute(_UPDATE, params)).first() is None:
            return None
        return await self._get(user_id, budget_id)

    async def soft_delete(self, user_id: UUID, budget_id: UUID) -> bool:
        result = await self._session.execute(_DELETE, {"user_id": user_id, "budget_id": budget_id})
        return result.first() is not None

    async def _get(self, user_id: UUID, budget_id: UUID) -> Budget:
        rows = await self._session.execute(_SELECT, {"user_id": user_id, "budget_id": budget_id})
        return _to_budget(rows.mappings().one())


def _to_budget(row: Mapping[Any, Any]) -> Budget:
    currency: str = row["currency"]
    decimals: int = row["decimals"]
    return Budget(
        id=row["id"],
        category_id=row["category_id"],
        category_name=row["category_name"],
        amount=Money(row["amount"], currency, decimals),
        spent=Money(row["spent"], currency, decimals),
        period_starts_on=row["starts_on"],
        period_ends_on=row["ends_on"],
        today=row["today"],
        alert_at_80=row["alert_at_80"],
        alert_at_100=row["alert_at_100"],
        daily=[
            (day, Money(total, currency, decimals))
            for day, total in zip(row["days"] or [], row["totals"] or [], strict=True)
        ],
    )
