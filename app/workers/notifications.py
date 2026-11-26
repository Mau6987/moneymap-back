"""Encola los avisos de recurrentes, hitos de metas (spec 006, RF-13 a RF-16) y presupuestos (spec 009).

Cada recurrente avisa `remind_days_before` días antes de vencer (por defecto 1)
y otra vez el día que vence, con el "hoy" de la zona horaria de cada persona. Los que vencen el mismo día van
en un solo aviso. Cada meta avisa al llegar al 25, 50 y 75 % y al cumplirse, una
sola vez por hito. Cada presupuesto avisa al 80 % y al pasar el 100 %, una vez
por mes. Se recorre a las personas como en `recurring.py`, cada una en
su transacción con `app.user_id`; si una falla, queda en `ops.log`.

Esto solo deja el aviso en `notify.notifications`; el envío es otro trabajo.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from itertools import groupby
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.modules.notify.domain.messages import DuePayment, budget_alert, goal_milestone, money, recurring_reminder
from app.modules.notify.infrastructure.outbox import enqueue, hides_amounts
from app.workers import celery

# ponytail: recorre a todas las personas cada día, como el job de recurrentes.
_SELECT_PEOPLE = text("SELECT id FROM iam.users WHERE deleted_at IS NULL AND status IN ('active', 'pending_deletion')")

# Solo gastos (RF-15): los ingresos recurrentes no son un pago que preparar.
_SELECT_DUE_SOON = text(
    """
    SELECT rules.next_due_on, (now() AT TIME ZONE users.timezone)::date AS today,
           rules.description, rules.amount, currencies.symbol, currencies.decimals
    FROM finance.recurring_rules AS rules
    JOIN iam.users AS users ON users.id = rules.user_id
    JOIN finance.categories AS categories ON categories.user_id = rules.user_id AND categories.id = rules.category_id
    JOIN catalog.currencies AS currencies ON currencies.code = rules.currency
    WHERE rules.user_id = :user_id AND rules.is_active AND rules.deleted_at IS NULL AND categories.kind = 'expense'
      AND (rules.end_date IS NULL OR rules.next_due_on <= rules.end_date)
      AND (rules.next_due_on - rules.remind_days_before = (now() AT TIME ZONE users.timezone)::date
           OR rules.next_due_on = (now() AT TIME ZONE users.timezone)::date)
    ORDER BY rules.next_due_on, rules.description
    """
)

# RF-16: el hito más alto al que llegó cada meta. Si salta del 10 al 60 %, avisa
# solo el 50: el 25 ya no tiene sentido. Una meta cumplida avisa si se cumplió
# en la última semana, para no avisar de metas viejas la primera vez que corre.
_SELECT_MILESTONES = text(
    """
    SELECT * FROM (
        SELECT goals.id, goals.name, goals.current_amount, goals.target_amount,
               currencies.symbol, currencies.decimals,
               CASE WHEN goals.status = 'achieved' THEN 100
                    ELSE (SELECT max(milestone) FROM unnest(ARRAY[25, 50, 75]) AS milestone
                          WHERE goals.current_amount * 100 >= goals.target_amount * milestone)
               END AS milestone
        FROM goals.goals AS goals
        JOIN catalog.currencies AS currencies ON currencies.code = goals.currency
        WHERE goals.user_id = :user_id AND goals.deleted_at IS NULL
          AND (goals.status = 'active'
               OR (goals.status = 'achieved' AND goals.achieved_at >= now() - INTERVAL '7 days'))
    ) AS reached
    WHERE milestone IS NOT NULL
    ORDER BY id
    """
)

# Spec 009, RF-10: lo gastado del mes calendario del usuario en la moneda de cada
# presupuesto. Si salta del 50 al 120 %, avisa solo el 100.
_SELECT_BUDGET_ALERTS = text(
    """
    SELECT * FROM (
        SELECT budgets.id, categories.name AS category_name, budgets.amount, month.month,
               coalesce(spent.total, 0) AS spent, currencies.symbol, currencies.decimals,
               CASE WHEN coalesce(spent.total, 0) > budgets.amount AND budgets.alert_at_100 THEN 100
                    WHEN coalesce(spent.total, 0) * 100 >= budgets.amount * 80 AND budgets.alert_at_80 THEN 80
               END AS threshold
        FROM planning.budgets AS budgets
        CROSS JOIN LATERAL (
            SELECT date_trunc('month', now() AT TIME ZONE users.timezone)::date AS month
            FROM iam.users AS users WHERE users.id = budgets.user_id
        ) AS month
        JOIN finance.categories AS categories
          ON categories.user_id = budgets.user_id AND categories.id = budgets.category_id
        JOIN catalog.currencies AS currencies ON currencies.code = budgets.currency
        LEFT JOIN LATERAL (
            SELECT sum(totals.total) AS total
            FROM reports.category_totals(:user_id, month.month, (month.month + INTERVAL '1 month - 1 day')::date)
                 AS totals
            WHERE totals.category_id = budgets.category_id AND totals.currency = budgets.currency
        ) AS spent ON true
        WHERE budgets.user_id = :user_id AND budgets.deleted_at IS NULL
    ) AS reached
    WHERE threshold IS NOT NULL
    ORDER BY id
    """
)

_LOG_FAILED = text(
    """
    SELECT ops.log(
        p_level => 'error',
        p_category => 'job',
        p_event_code => :event_code,
        p_message => 'No se pudo encolar un aviso de una persona',
        p_service => 'worker',
        p_user_id => :user_id,
        p_error_type => :error_type
    )
    """
)


_PerPerson = Callable[[AsyncConnection, UUID], Awaitable[int]]


async def remind_recurring() -> int:
    """Encola los avisos de recurrentes de todos y devuelve cuántos quedaron en la cola."""
    return await _for_everyone(_remind_for, "notify.recurring_reminder.failed")


async def notify_goal_milestones() -> int:
    """Encola los avisos de hitos de metas de todos y devuelve cuántos quedaron en la cola."""
    return await _for_everyone(_milestones_for, "notify.goal_milestone.failed")


async def notify_budget_alerts() -> int:
    """Encola los avisos de presupuesto de todos y devuelve cuántos quedaron en la cola."""
    return await _for_everyone(_budget_alerts_for, "notify.budget_alert.failed")


async def _for_everyone(per_person: _PerPerson, event_code: str) -> int:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            people = (await connection.execute(_SELECT_PEOPLE)).scalars().all()
        queued = 0
        for user_id in people:
            queued += await _for_person(engine, user_id, per_person, event_code)
    finally:
        await engine.dispose()
    return queued


async def _for_person(engine: AsyncEngine, user_id: UUID, per_person: _PerPerson, event_code: str) -> int:
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            return await per_person(connection, user_id)
    except DBAPIError as error:  # se anota y se sigue con la próxima persona (ver el docstring del módulo)
        params = {"user_id": user_id, "error_type": type(error.orig).__name__, "event_code": event_code}
        async with engine.begin() as connection:
            await connection.execute(_LOG_FAILED, params)
        return 0


async def _remind_for(connection: AsyncConnection, user_id: UUID) -> int:
    rows = (await connection.execute(_SELECT_DUE_SOON, {"user_id": user_id})).mappings().all()
    if not rows:
        return 0
    private = await hides_amounts(connection, user_id)
    today: date = rows[0]["today"]
    queued = 0
    for due_on, group in groupby(rows, key=lambda row: row["next_due_on"]):
        payments = [DuePayment(row["description"], row["amount"], row["symbol"], row["decimals"]) for row in group]
        title, body = recurring_reminder(due_on, today, payments, private)
        data = {"screen": "recurring", "due_on": due_on.isoformat()}
        # El aviso de antes y el del mismo día tienen su clave: uno no frena al otro.
        dedupe_key = f"recurring:{due_on}:today" if due_on == today else f"recurring:{due_on}"
        queued += await enqueue(connection, user_id, "recurring.due_soon", title, body, dedupe_key, data)
    return queued


async def _milestones_for(connection: AsyncConnection, user_id: UUID) -> int:
    rows = (await connection.execute(_SELECT_MILESTONES, {"user_id": user_id})).mappings().all()
    if not rows:
        return 0
    private = await hides_amounts(connection, user_id)
    queued = 0
    for row in rows:
        saved = money(row["current_amount"], row["symbol"], row["decimals"])
        target = money(row["target_amount"], row["symbol"], row["decimals"])
        title, body = goal_milestone(row["name"], row["milestone"], saved, target, private)
        type_key = "goal.achieved" if row["milestone"] == 100 else "goal.milestone"
        data = {"screen": "goal", "goal_id": str(row["id"])}
        dedupe_key = f"goal:{row['id']}:{row['milestone']}"
        queued += await enqueue(connection, user_id, type_key, title, body, dedupe_key, data)
    return queued


async def _budget_alerts_for(connection: AsyncConnection, user_id: UUID) -> int:
    rows = (await connection.execute(_SELECT_BUDGET_ALERTS, {"user_id": user_id})).mappings().all()
    if not rows:
        return 0
    private = await hides_amounts(connection, user_id)
    queued = 0
    for row in rows:
        spent = money(row["spent"], row["symbol"], row["decimals"])
        amount = money(row["amount"], row["symbol"], row["decimals"])
        title, body = budget_alert(row["category_name"], row["threshold"], spent, amount, private)
        type_key = "budget.exceeded" if row["threshold"] == 100 else "budget.threshold"
        data = {"screen": "budgets", "budget_id": str(row["id"])}
        dedupe_key = f"budget:{row['id']}:{row['month']:%Y-%m}:{row['threshold']}"
        queued += await enqueue(connection, user_id, type_key, title, body, dedupe_key, data)
    return queued


@celery.task(name="notify.remind_recurring")  # type: ignore[untyped-decorator]  # celery no publica tipos
def remind_recurring_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): todos los días a las 13:00 UTC."""
    return asyncio.run(remind_recurring())


@celery.task(name="notify.goal_milestones")  # type: ignore[untyped-decorator]  # celery no publica tipos
def goal_milestones_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): cada hora."""
    return asyncio.run(notify_goal_milestones())


@celery.task(name="notify.budget_alerts")  # type: ignore[untyped-decorator]  # celery no publica tipos
def budget_alerts_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): cada hora."""
    return asyncio.run(notify_budget_alerts())
