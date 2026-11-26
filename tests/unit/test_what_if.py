"""What If? (spec 009, RF-12 a RF-14) sin base, con el criterio del PRD §6.19."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import NotFound
from app.core.money import Money
from app.modules.finance.domain.models import SafeToSpend
from app.modules.planning.domain.models import GoalPace, GoalPaces
from app.modules.planning.domain.what_if import Change, simulate

TODAY = date(2026, 10, 15)


def _bob(amount: str) -> Money:
    return Money(amount, "BOB", 2)


def _available(balance: str, planned_savings: str = "0") -> SafeToSpend:
    zero = _bob("0")
    return SafeToSpend(
        "BOB", date(2026, 10, 1), date(2026, 10, 31), _bob(balance), zero, _bob(planned_savings), zero, zero
    )


# Viaje: le faltan 1000 a 100 por mes (10 meses). Fondo: le faltan 1200 a 200 (6 meses), prioridad más alta.
TRIP = GoalPace(uuid4(), "Viaje", Decimal(1000), Decimal(0), Decimal(100))
FUND = GoalPace(uuid4(), "Fondo", Decimal(1200), Decimal(0), Decimal(200))
PACES = GoalPaces(TODAY, [TRIP, FUND])  # el orden de recorte: primero el Viaje


def test_un_gasto_recurrente_nuevo_baja_safe_to_spend_y_atrasa_las_metas() -> None:
    result = simulate(_available("100"), PACES, [Change("recurring_expense", Decimal(200))])

    assert (result.safe_to_spend.amount, result.safe_to_spend_after) == (_bob("100"), _bob("-100"))
    # Faltan 100: salen del Viaje, que se queda sin ritmo. El Fondo no cambia.
    trip, fund = result.goals
    assert (trip.estimated_completion, trip.estimated_completion_after) == (date(2027, 8, 15), None)
    assert fund.delay_months == 0
    assert result.monthly_savings_after == _bob("200")


def test_si_alcanza_no_toca_las_metas() -> None:
    result = simulate(_available("500"), PACES, [Change("recurring_expense", Decimal(200))])

    assert result.safe_to_spend_after == _bob("300")
    assert [goal.delay_months for goal in result.goals] == [0, 0]


def test_dos_cambios_combinados() -> None:
    changes = [Change("income", Decimal(300)), Change("goal_contribution", Decimal(400), FUND.goal_id)]
    result = simulate(_available("100", planned_savings="0"), PACES, changes)

    # +300 de ingreso y 200 más al Fondo: 100 + 300 − 200.
    assert result.safe_to_spend_after == _bob("200")
    fund = result.goals[1]
    assert (fund.estimated_completion, fund.estimated_completion_after, fund.delay_months) == (
        date(2027, 4, 15),
        date(2027, 1, 15),
        -3,
    )


def test_ahorro_planificado() -> None:
    result = simulate(_available("500", planned_savings="100"), PACES, [Change("planned_savings", Decimal(250))])
    assert result.safe_to_spend_after == _bob("250")  # 400 libres − 150 más de ahorro


def test_una_meta_que_no_esta_es_404() -> None:
    with pytest.raises(NotFound):
        simulate(_available("100"), PACES, [Change("goal_contribution", Decimal(1), uuid4())])
