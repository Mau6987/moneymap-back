"""El cierre de mes que guarda la Money Story (spec 006, RF-1 a RF-4 y RF-7).

Los movimientos se fechan contra el "hoy" de la base en la zona horaria del
usuario, como en `test_workers_recurring.py`: la prueba no depende del reloj.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.core.db import user_session
from app.workers import celery
from app.workers.money_story import close_months

# `months_ago` 1 es el mes que acaba de cerrar; 0, el mes en curso.
_INSERT_MOVE = text(
    """
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
    SELECT :user_id, CAST(:kind AS catalog.money_kind), accounts.id, categories.id, :amount,
           (date_trunc('month', now() AT TIME ZONE users.timezone) - make_interval(months => :months_ago))::date,
           'Prueba'
    FROM iam.users AS users, finance.accounts AS accounts, finance.categories AS categories
    WHERE users.id = :user_id AND accounts.user_id = :user_id AND accounts.currency = :currency
      AND categories.user_id = :user_id AND categories.template_key = :category
    """
)


async def _account(user_id: UUID, currency: str) -> None:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)"
                " VALUES (:user_id, :name, 'cash', :currency, 100000)"
            ),
            {"user_id": user_id, "name": f"Efectivo {currency}", "currency": currency},
        )


async def _move(user_id: UUID, kind: str, category: str, amount: str, months_ago: int, currency: str = "BOB") -> None:
    params = {
        "user_id": user_id,
        "kind": kind,
        "category": category,
        "amount": Decimal(amount),
        "months_ago": months_ago,
        "currency": currency,
    }
    async with user_session(user_id) as session:
        await session.execute(_INSERT_MOVE, params)


async def _stories(user_id: UUID) -> dict[str, Any]:
    async with user_session(user_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT currency, status, income_total, expense_total, savings_total, savings_rate,"
                    " highlights, comparison FROM reports.money_stories WHERE user_id = :user_id"
                ),
                {"user_id": user_id},
            )
        ).mappings()
        return {row["currency"]: dict(row) for row in rows}


@pytest.mark.usefixtures("allow_more_currencies")
async def test_guarda_una_historia_por_moneda_con_la_comparacion(user_id: UUID) -> None:
    await _account(user_id, "BOB")
    await _account(user_id, "USD")
    await _move(user_id, "income", "salary", "4000", months_ago=2)
    await _move(user_id, "expense", "groceries", "1000", months_ago=2)
    await _move(user_id, "income", "salary", "5000", months_ago=1)
    await _move(user_id, "expense", "groceries", "1200", months_ago=1)
    await _move(user_id, "expense", "restaurants", "300", months_ago=1)
    await _move(user_id, "expense", "restaurants", "999", months_ago=0)  # el mes en curso no cierra
    await _move(user_id, "expense", "subscriptions", "20", months_ago=1, currency="USD")

    assert await close_months() >= 2

    stories = await _stories(user_id)
    bob, usd = stories["BOB"], stories["USD"]
    assert (bob["status"], bob["income_total"], bob["expense_total"], bob["savings_total"], bob["savings_rate"]) == (
        "ready",
        Decimal("5000"),
        Decimal("1500"),
        Decimal("3500"),
        Decimal("0.7"),
    )
    assert [line["key"] for line in bob["highlights"]] == [
        "summary",
        "saved",
        "top_expense_category",
        "income_up",
        "savings_up",
    ]
    assert bob["highlights"][1]["params"] == {"savings": "3500.00", "rate": "70"}
    assert bob["highlights"][3]["params"]["difference"] == "1000.00"
    assert bob["comparison"]["income_total"] == "4000.00"
    assert bob["comparison"]["top_expense_category"]["total"] == "1000.00"
    # En USD es el primer mes: sin comparación (RF-3) y sin sumar nada de BOB (RF-7).
    assert usd["comparison"] is None
    assert usd["savings_rate"] is None
    usd_keys = [line["key"] for line in usd["highlights"]]
    assert usd_keys == ["summary", "overspent", "top_expense_category", "first_month"]


async def test_no_duplica_ni_crea_historias_sin_movimientos(user_id: UUID, new_financial_user: Any) -> None:
    await _account(user_id, "BOB")
    await _move(user_id, "expense", "groceries", "100", months_ago=1)
    quiet = await new_financial_user("BOB")

    await close_months()
    await close_months()  # otra corrida: el mes ya tiene historia

    assert list(await _stories(user_id)) == ["BOB"]
    assert await _stories(quiet) == {}


def test_la_tarea_esta_en_el_calendario() -> None:
    assert celery.conf.beat_schedule["close-money-story-months"]["task"] == "reports.close_months"
    assert "reports.close_months" in celery.tasks
