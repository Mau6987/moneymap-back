"""Cierra el mes de cada persona y guarda su Money Story (spec 006, RF-1 a RF-4 y RF-7).

Corre todos los días: el mes cierra en la zona horaria de cada persona, no en
UTC, y si el job no corrió el día 1 lo cierra en la corrida siguiente. Se
recorre a las personas como en `recurring.py`, cada una en su transacción con
`app.user_id`; si una falla, queda en `ops.log` y siguen las demás.

Una historia por moneda con movimientos en el mes, nunca sumando monedas, y
un solo aviso de que está lista (RF-17). Es idempotente: si el mes ya tiene
historia no se vuelve a calcular, y el UNIQUE de la tabla impide duplicarla si
dos corridas se cruzan.
"""

import asyncio
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.modules.notify.domain.messages import money_story_ready
from app.modules.notify.infrastructure.outbox import enqueue
from app.modules.reports.domain.money_story import TEMPLATE_VERSION, MonthFacts, build_story, month_name
from app.workers import celery

# ponytail: recorre a todas las personas cada día; con muchas, filtrar las que
# ya tienen la historia del mes con una sola consulta del rol del worker.
_SELECT_PEOPLE = text("SELECT id FROM iam.users WHERE deleted_at IS NULL AND status IN ('active', 'pending_deletion')")

# El último mes cerrado con el "hoy" de su zona horaria, si todavía no tiene historia.
_SELECT_OPEN_MONTH = text(
    """
    SELECT closed.starts_on
    FROM iam.users AS users
    CROSS JOIN LATERAL (
        SELECT (date_trunc('month', now() AT TIME ZONE users.timezone) - INTERVAL '1 month')::date AS starts_on
    ) AS closed
    WHERE users.id = :user_id
      AND NOT EXISTS (
        SELECT 1 FROM reports.money_stories AS stories
        WHERE stories.user_id = users.id AND stories.period_type = 'month' AND stories.period_start = closed.starts_on)
    """
)

# El mes cerrado y el anterior, por moneda: totales, mayor gasto y aportes a
# metas. reports.category_totals ya deja afuera transferencias y borrados.
_SELECT_FACTS = text(
    """
    WITH months (name, starts_on, ends_on) AS (
        VALUES ('current', CAST(:starts_on AS date), (CAST(:starts_on AS date) + INTERVAL '1 month')::date - 1),
               ('previous', (CAST(:starts_on AS date) - INTERVAL '1 month')::date, CAST(:starts_on AS date) - 1)
    ), totals AS (
        SELECT months.name, months.starts_on, months.ends_on, totals.*
        FROM months CROSS JOIN LATERAL reports.category_totals(:user_id, months.starts_on, months.ends_on) AS totals
    ), sums AS (
        SELECT name, starts_on, ends_on, currency,
               coalesce(sum(total) FILTER (WHERE kind = 'income'), 0) AS income,
               coalesce(sum(total) FILTER (WHERE kind = 'expense'), 0) AS expense
        FROM totals
        GROUP BY name, starts_on, ends_on, currency
    ), tops AS (
        SELECT DISTINCT ON (name, currency) name, currency, category_name, total
        FROM totals
        WHERE kind = 'expense'
        ORDER BY name, currency, total DESC, category_name
    )
    SELECT sums.name, sums.starts_on, sums.currency, currencies.decimals, sums.income, sums.expense,
           tops.category_name AS top_name, tops.total AS top_total,
           coalesce((SELECT sum(contributions.amount)
                       FROM goals.goal_contributions AS contributions
                       JOIN goals.goals AS goals
                         ON goals.user_id = contributions.user_id AND goals.id = contributions.goal_id
                      WHERE contributions.user_id = :user_id AND goals.currency = sums.currency
                        AND goals.deleted_at IS NULL
                        AND contributions.contributed_on BETWEEN sums.starts_on AND sums.ends_on), 0) AS goals
    FROM sums
    JOIN catalog.currencies AS currencies ON currencies.code = sums.currency
    LEFT JOIN tops ON tops.name = sums.name AND tops.currency = sums.currency
    """
)

_INSERT_STORY = text(
    """
    INSERT INTO reports.money_stories
        (user_id, period_type, period_start, period_end, status, currency, income_total, expense_total,
         savings_total, savings_rate, highlights, comparison, template_version, generated_at)
    VALUES (:user_id, 'month', :starts_on, (CAST(:starts_on AS date) + INTERVAL '1 month')::date - 1, 'ready',
            :currency, :income, :expense, :savings, :savings_rate, CAST(:highlights AS jsonb),
            CAST(:comparison AS jsonb), :template_version, now())
    ON CONFLICT ON CONSTRAINT money_stories_period_uq DO NOTHING
    """
)

_LOG_FAILED = text(
    """
    SELECT ops.log(
        p_level => 'error',
        p_category => 'job',
        p_event_code => 'reports.money_story.failed',
        p_message => 'No se pudo cerrar el mes de una persona',
        p_service => 'worker',
        p_user_id => :user_id,
        p_error_type => :error_type
    )
    """
)


async def close_months() -> int:
    """Guarda la Money Story del último mes cerrado de cada persona y devuelve cuántas quedaron."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            people = (await connection.execute(_SELECT_PEOPLE)).scalars().all()
        created = 0
        for user_id in people:
            created += await _close_for(engine, user_id)
    finally:
        await engine.dispose()
    return created


async def _close_for(engine: AsyncEngine, user_id: UUID) -> int:
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
            return await _close_month(connection, user_id)
    except DBAPIError as error:  # se anota y se sigue con la próxima persona (ver el docstring del módulo)
        async with engine.begin() as connection:
            await connection.execute(_LOG_FAILED, {"user_id": user_id, "error_type": type(error.orig).__name__})
        return 0


async def _close_month(connection: AsyncConnection, user_id: UUID) -> int:
    starts_on: date | None = (await connection.execute(_SELECT_OPEN_MONTH, {"user_id": user_id})).scalar_one_or_none()
    if starts_on is None:
        return 0
    rows = (await connection.execute(_SELECT_FACTS, {"user_id": user_id, "starts_on": starts_on})).mappings().all()
    previous = {row["currency"]: _facts(row) for row in rows if row["name"] == "previous"}
    created = 0
    for row in rows:
        if row["name"] != "current":
            continue
        current = _facts(row)
        story = build_story(current, previous.get(row["currency"]))
        params = {
            "user_id": user_id,
            "starts_on": starts_on,
            "currency": row["currency"],
            "income": current.income,
            "expense": current.expense,
            "savings": current.savings,
            "savings_rate": story.savings_rate,
            "highlights": json.dumps(story.highlights),
            "comparison": None if story.comparison is None else json.dumps(story.comparison),
            "template_version": TEMPLATE_VERSION,
        }
        created += (await connection.execute(_INSERT_STORY, params)).rowcount
    if created:  # RF-17: un aviso por mes, aunque haya una historia por moneda
        title, body = money_story_ready(month_name(starts_on))
        period = starts_on.strftime("%Y-%m")
        data = {"screen": "money_story", "period": period}
        await enqueue(connection, user_id, "money_story.ready", title, body, f"money_story:{period}", data)
    return created


def _facts(row: RowMapping) -> MonthFacts:
    top = None if row["top_name"] is None else (row["top_name"], Decimal(row["top_total"]))
    return MonthFacts(
        month=row["starts_on"],
        decimals=row["decimals"],
        income=Decimal(row["income"]),
        expense=Decimal(row["expense"]),
        goals_contributed=Decimal(row["goals"]),
        top_category=top,
    )


@celery.task(name="reports.close_months")  # type: ignore[untyped-decorator]  # celery no publica tipos
def close_months_task() -> int:
    """La tarea del calendario (`app/workers/__init__.py`): todos los días a las 05:30 UTC."""
    return asyncio.run(close_months())
