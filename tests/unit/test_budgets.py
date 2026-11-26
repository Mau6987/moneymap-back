"""Spending Pace (spec 009, RF-5 a RF-7) con el ejemplo del PRD §6.17."""

from datetime import date
from uuid import uuid4

import pytest

from app.core.money import Money
from app.modules.planning.domain.budgets import Budget


def _budget(spent: str, today: date, amount: str = "400") -> Budget:
    return Budget(
        id=uuid4(),
        category_id=uuid4(),
        category_name="Comida",
        amount=Money(amount, "USD", 2),
        spent=Money(spent, "USD", 2),
        period_starts_on=date(2026, 11, 1),
        period_ends_on=date(2026, 11, 30),
        today=today,
    )


def test_el_ejemplo_del_prd() -> None:
    budget = _budget("240", date(2026, 11, 12))

    assert (budget.remaining, budget.percent_used) == (Money("160", "USD", 2), 60)
    assert budget.pace.status == "too_fast"
    assert budget.pace.projected_total == Money("600", "USD", 2)


@pytest.mark.parametrize(
    ("spent", "status"),
    [("160", "on_track"), ("180", "a_bit_fast"), ("200", "a_bit_fast"), ("204", "too_fast")],
)
def test_los_tres_estados(spent: str, status: str) -> None:
    # Día 12 de 30: va el 40 % del mes. 160 es el 40 %, 200 el 50 % (10 puntos más).
    assert _budget(spent, date(2026, 11, 12)).pace.status == status


def test_los_primeros_tres_dias_no_hay_estado() -> None:
    assert _budget("300", date(2026, 11, 3)).pace.status is None
    assert _budget("300", date(2026, 11, 4)).pace.status == "too_fast"


def test_pasado_del_presupuesto() -> None:
    budget = _budget("450", date(2026, 11, 30))
    assert (budget.remaining, budget.percent_used) == (Money("-50", "USD", 2), 112)
