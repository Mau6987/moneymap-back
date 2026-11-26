"""Registrar un vencimiento de un recurrente (spec 003, RF-17, RF-19 y RF-20).

Un solo SQL para la API (la persona lo marca pagado) y para el job (`auto_post`):
inserta el movimiento y avanza `next_due_on` en la misma transacción. Funciona
con la sesión de la petición o con una conexión del worker, siempre con
`app.user_id` puesto: las dos tablas tienen RLS.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import RecurringPayment, RecurringPaymentRecord, RecurringRuleRecord
from app.modules.finance.infrastructure.transaction_history_reader import to_transaction_item

# FOR UPDATE: dos pagos al mismo tiempo no registran el mismo vencimiento dos
# veces; el segundo espera y ve el `next_due_on` ya avanzado. Ingreso o gasto
# sale de la categoría. La cuenta es la elegida al pagar o la del recurrente
# (BUG-027); la moneda es la del recurrente, y una cuenta de otra moneda es
# `currency_mismatch`. Un gasto que pasa el saldo es `account_insufficient` (BUG-028).
_INSERT_PAYMENT = text(
    """
    WITH rule AS (
        SELECT rules.id, rules.user_id, rules.account_id, rules.category_id, rules.amount,
               rules.currency, rules.description, rules.next_due_on, categories.kind,
               (now() AT TIME ZONE users.timezone)::date AS today
        FROM finance.recurring_rules AS rules
        JOIN finance.categories AS categories
          ON categories.user_id = rules.user_id AND categories.id = rules.category_id
        JOIN iam.users AS users ON users.id = rules.user_id
        WHERE rules.user_id = :user_id AND rules.id = :rule_id
          AND rules.deleted_at IS NULL AND rules.is_active
        FOR UPDATE OF rules
    )
    INSERT INTO finance.transactions
        (user_id, kind, account_id, currency, category_id, amount, occurred_on, description, source,
         recurring_rule_id)
    SELECT user_id, kind,
           finance.require_payment_account(coalesce(CAST(:account_id AS uuid), account_id)),
           currency, category_id,
           coalesce(CAST(:amount AS numeric), amount),
           CASE WHEN CAST(:on_due_date AS boolean) THEN next_due_on
                ELSE coalesce(CAST(:occurred_on AS date), today) END,
           description, 'recurring', id
    FROM rule
    RETURNING id, kind, account_id, category_id, transfer_account_id, amount, currency,
              occurred_on, description, source, created_at
    """
)

# RF-19: si el vencimiento siguiente pasa la `end_date`, el recurrente termina.
# Solo avanza uno vivo: así omitir una vez (RF-22) no toca uno dado de baja.
_ADVANCE = text(
    """
    WITH advanced AS (
        UPDATE finance.recurring_rules AS rules
        SET next_due_on = finance.next_occurrence(rules.start_date, rules.frequency, rules.next_due_on),
            is_active = rules.end_date IS NULL
                     OR finance.next_occurrence(rules.start_date, rules.frequency, rules.next_due_on) <= rules.end_date
        WHERE rules.user_id = :user_id AND rules.id = :rule_id
          AND rules.deleted_at IS NULL AND rules.is_active
        RETURNING rules.id, rules.account_id, rules.category_id, rules.amount, rules.currency,
                  rules.description, rules.frequency::text AS frequency, rules.next_due_on, rules.auto_post
    )
    SELECT advanced.*, categories.kind::text AS type, currencies.decimals
    FROM advanced
    JOIN finance.categories AS categories ON categories.user_id = :user_id AND categories.id = advanced.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = advanced.currency
    """
)

Executor = AsyncSession | AsyncConnection


async def register_payment(
    executor: Executor, user_id: UUID, rule_id: UUID, payment: RecurringPayment
) -> RecurringPaymentRecord | None:
    """RF-17: con el monto y la fecha que eligió la persona, o los del recurrente y hoy."""
    params = {
        "amount": payment.amount,
        "occurred_on": payment.occurred_on,
        "on_due_date": False,
        "account_id": payment.account_id,
    }
    return await _post(executor, user_id, rule_id, params)


async def post_on_due_date(executor: Executor, user_id: UUID, rule_id: UUID) -> RecurringPaymentRecord | None:
    """RF-20: lo que hace el job con un `auto_post`, en la fecha en que vencía."""
    params = {"amount": None, "occurred_on": None, "on_due_date": True, "account_id": None}
    return await _post(executor, user_id, rule_id, params)


async def _post(
    executor: Executor, user_id: UUID, rule_id: UUID, params: Mapping[str, object]
) -> RecurringPaymentRecord | None:
    keys = {"user_id": user_id, "rule_id": rule_id}
    transaction = (await executor.execute(_INSERT_PAYMENT, {**keys, **params})).mappings().one_or_none()
    if transaction is None:
        return None
    rule = (await executor.execute(_ADVANCE, keys)).mappings().one()
    item = to_transaction_item({**transaction, "decimals": rule["decimals"]})
    return RecurringPaymentRecord(transaction=item, rule=to_rule_record(rule))


async def skip_occurrence(executor: Executor, user_id: UUID, rule_id: UUID) -> RecurringRuleRecord | None:
    """RF-22: pasa al vencimiento siguiente sin registrar nada (ya se pagó por fuera)."""
    keys = {"user_id": user_id, "rule_id": rule_id}
    row = (await executor.execute(_ADVANCE, keys)).mappings().one_or_none()
    return None if row is None else to_rule_record(row)


def to_rule_record(row: Mapping[Any, Any]) -> RecurringRuleRecord:
    currency: str = row["currency"]
    return RecurringRuleRecord(
        id=row["id"],
        account_id=row["account_id"],
        category_id=row["category_id"],
        type=row["type"],
        amount=Money(row["amount"], currency, row["decimals"]),
        description=row["description"],
        frequency=row["frequency"],
        next_due_on=row["next_due_on"],
        auto_post=row["auto_post"],
        has_receipt=row.get("has_receipt", False),
        pending_dates=tuple(row.get("pending_dates") or ()),
    )
