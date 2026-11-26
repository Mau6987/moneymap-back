"""El SQL de `finance.recurring_rules` (spec 007, pasos 3 y 4; spec 002, RF-29 a RF-31).

La moneda la completa un trigger con la de la cuenta (spec 002, RF-21) y la
primera fecha, si no se envía, es el día de hoy del usuario en su zona horaria.
Sin cuenta ni moneda, va a la cuenta por defecto del usuario; con solo la moneda,
queda sin cuenta y se elige al pagar (BUG-027).
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.domain.models import (
    NewRecurringRule,
    RecurringPayment,
    RecurringPaymentRecord,
    RecurringRuleChanges,
    RecurringRuleRecord,
)
from app.modules.finance.infrastructure.recurring_posting import register_payment, skip_occurrence, to_rule_record

# El INSERT … SELECT solo inserta si la categoría (y la cuenta, si se envía) son
# del usuario y están vivas: si no, no devuelve filas y la API responde 404 (nunca 403).
_INSERT_RULE = text(
    """
    WITH created AS (
        INSERT INTO finance.recurring_rules
            (user_id, account_id, category_id, amount, currency, description, frequency, start_date, auto_post)
        SELECT categories.user_id,
               accounts.id,
               categories.id,
               :amount,
               CAST(:currency AS char(3)),
               :description,
               CAST(:frequency AS finance.frequency),
               coalesce(CAST(:start_date AS date), (now() AT TIME ZONE users.timezone)::date),
               :auto_post
        FROM finance.categories AS categories
        JOIN iam.users AS users ON users.id = categories.user_id
        LEFT JOIN finance.accounts AS accounts
          ON accounts.user_id = categories.user_id
         AND accounts.deleted_at IS NULL
         AND accounts.archived_at IS NULL
         AND (accounts.id = CAST(:account_id AS uuid)
              OR (CAST(:account_id AS uuid) IS NULL AND CAST(:currency AS char(3)) IS NULL AND accounts.is_default))
        WHERE categories.user_id = :user_id
          AND categories.id = :category_id
          AND categories.deleted_at IS NULL
          AND (accounts.id IS NOT NULL
               OR (CAST(:account_id AS uuid) IS NULL AND CAST(:currency AS char(3)) IS NOT NULL))
        RETURNING id, account_id, category_id, amount, currency, description,
                  frequency::text AS frequency, next_due_on, auto_post
    )
    SELECT created.*, categories.kind::text AS type, currencies.decimals,
           EXISTS (SELECT 1 FROM finance.recurring_rule_receipts AS rr WHERE rr.user_id = :user_id AND rr.rule_id = created.id) AS has_receipt
    FROM created
    JOIN finance.categories AS categories ON categories.user_id = :user_id AND categories.id = created.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = created.currency
    """
)

# RF-23: `pending_dates` son las mismas veces que suma Cuentas por pagar (RF-11),
# más `next_due_on`, que es la que se paga aunque no cuente. Un ingreso fijo o un
# gasto no comprometido tiene solo `next_due_on`.
_SELECT_RULES = text(
    """
    WITH me AS (
        SELECT period.ends_on, users.timezone
        FROM iam.users AS users
        CROSS JOIN LATERAL finance.current_period(users.id, (now() AT TIME ZONE users.timezone)::date) AS period
        WHERE users.id = :user_id
    )
    SELECT rules.id, rules.account_id, rules.category_id, rules.amount, rules.currency, rules.description,
           rules.frequency::text AS frequency, rules.next_due_on, rules.auto_post,
           categories.kind::text AS type, currencies.decimals,
           EXISTS (SELECT 1 FROM finance.recurring_rule_receipts AS rr WHERE rr.user_id = rules.user_id AND rr.rule_id = rules.id) AS has_receipt,
           ARRAY(
               SELECT occurrence.due_on
               FROM finance.recurring_occurrences(
                   rules.start_date, rules.frequency, rules.next_due_on, me.ends_on) AS occurrence(due_on)
               WHERE occurrence.due_on = rules.next_due_on
                  OR (categories.kind = 'expense' AND rules.is_committed
                      AND (rules.end_date IS NULL OR rules.end_date >= occurrence.due_on)
                      AND occurrence.due_on >= (
                          SELECT created.starts_on
                          FROM finance.current_period(rules.user_id, (rules.created_at AT TIME ZONE me.timezone)::date)
                               AS created))
               ORDER BY occurrence.due_on
           ) AS pending_dates
    FROM finance.recurring_rules AS rules
    JOIN finance.categories AS categories ON categories.user_id = rules.user_id AND categories.id = rules.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = rules.currency
    CROSS JOIN me
    WHERE rules.user_id = :user_id AND rules.deleted_at IS NULL AND rules.is_active
    ORDER BY rules.next_due_on, rules.id
    """
)

# Como el alta: la cuenta y la categoría nuevas tienen que ser del usuario y
# estar vivas, o no se actualiza nada y la API responde 404. La moneda no está
# en el SET: si la cuenta nueva es de otra, el trigger responde currency_mismatch.
_UPDATE_RULE = text(
    """
    WITH updated AS (
        UPDATE finance.recurring_rules AS rules
        SET account_id = coalesce(CAST(:account_id AS uuid), rules.account_id),
            category_id = coalesce(CAST(:category_id AS uuid), rules.category_id),
            amount = coalesce(:amount, rules.amount),
            description = coalesce(:description, rules.description),
            frequency = coalesce(CAST(:frequency AS finance.frequency), rules.frequency),
            auto_post = coalesce(CAST(:auto_post AS boolean), rules.auto_post)
        WHERE rules.user_id = :user_id AND rules.id = :rule_id AND rules.deleted_at IS NULL
          AND (CAST(:account_id AS uuid) IS NULL OR EXISTS (
                SELECT 1 FROM finance.accounts AS accounts
                WHERE accounts.user_id = :user_id AND accounts.id = CAST(:account_id AS uuid)
                  AND accounts.deleted_at IS NULL AND accounts.archived_at IS NULL))
          AND (CAST(:category_id AS uuid) IS NULL OR EXISTS (
                SELECT 1 FROM finance.categories AS categories
                WHERE categories.user_id = :user_id AND categories.id = CAST(:category_id AS uuid)
                  AND categories.deleted_at IS NULL))
        RETURNING rules.id, rules.account_id, rules.category_id, rules.amount, rules.currency,
                  rules.description, rules.frequency::text AS frequency, rules.next_due_on,
                  rules.auto_post
    )
    SELECT updated.*, categories.kind::text AS type, currencies.decimals,
           EXISTS (SELECT 1 FROM finance.recurring_rule_receipts AS rr WHERE rr.user_id = :user_id AND rr.rule_id = updated.id) AS has_receipt
    FROM updated
    JOIN finance.categories AS categories ON categories.user_id = :user_id AND categories.id = updated.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = updated.currency
    """
)

_SOFT_DELETE_RULE = text(
    """
    UPDATE finance.recurring_rules SET deleted_at = now()
    WHERE user_id = :user_id AND id = :rule_id AND deleted_at IS NULL
    RETURNING id
    """
)


class SqlRecurringRuleRepository:
    """Implementa `RecurringRuleRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, user_id: UUID, rule: NewRecurringRule) -> RecurringRuleRecord | None:
        row = (
            (
                await self._session.execute(
                    _INSERT_RULE,
                    {
                        "user_id": user_id,
                        "account_id": rule.account_id,
                        "currency": rule.currency,
                        "category_id": rule.category_id,
                        "amount": rule.amount,
                        "description": rule.description,
                        "frequency": rule.frequency,
                        "start_date": rule.start_date,
                        "auto_post": rule.auto_post,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else to_rule_record(row)

    async def list(self, user_id: UUID) -> list[RecurringRuleRecord]:
        rows = (await self._session.execute(_SELECT_RULES, {"user_id": user_id})).mappings().all()
        return [to_rule_record(row) for row in rows]

    async def update(self, user_id: UUID, rule_id: UUID, changes: RecurringRuleChanges) -> RecurringRuleRecord | None:
        params = {
            "user_id": user_id,
            "rule_id": rule_id,
            "account_id": changes.account_id,
            "category_id": changes.category_id,
            "amount": changes.amount,
            "description": changes.description,
            "frequency": changes.frequency,
            "auto_post": changes.auto_post,
        }
        row = (await self._session.execute(_UPDATE_RULE, params)).mappings().one_or_none()
        return None if row is None else to_rule_record(row)

    async def register_payment(
        self, user_id: UUID, rule_id: UUID, payment: RecurringPayment
    ) -> RecurringPaymentRecord | None:
        return await register_payment(self._session, user_id, rule_id, payment)

    async def skip_occurrence(self, user_id: UUID, rule_id: UUID) -> RecurringRuleRecord | None:
        return await skip_occurrence(self._session, user_id, rule_id)

    async def soft_delete(self, user_id: UUID, rule_id: UUID) -> bool:
        params = {"user_id": user_id, "rule_id": rule_id}
        return (await self._session.execute(_SOFT_DELETE_RULE, params)).scalar_one_or_none() is not None
