"""Financial Forecast (spec 010) con el criterio del PRD §6.18."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.core.money import Money
from app.modules.planning.domain.forecast import ForecastInputs, GoalFlow, RecurringFlow, project

TODAY = date(2026, 10, 21)


def _bob(amount: str) -> Money:
    return Money(amount, "BOB", 2)


def _monthly(kind: str, amount: int, in_days: int) -> RecurringFlow:
    due = TODAY + timedelta(days=in_days)
    return RecurringFlow(kind, Decimal(amount), "monthly", due, due, None)  # type: ignore[arg-type]


def _inputs(balance: int, **overrides: object) -> ForecastInputs:
    values: dict[str, object] = {
        "currency": "BOB",
        "decimals": 2,
        "today": TODAY,
        "balance": Decimal(balance),
        "recurring": [_monthly("income", 3000, 5), _monthly("expense", 700, 10)],
        "goals": [GoalFlow(uuid4(), Decimal(10000), Decimal(300))],
        "variable_monthly": Decimal(1500),
        "history_months": 3,
    }
    values.update(overrides)
    return ForecastInputs(**values)  # type: ignore[arg-type]


def test_el_ejemplo_del_prd() -> None:
    forecast = project(_inputs(2500))

    # 2500 + 3000 − 700 − 300 − 1500 = 3000 a 30 días; 500 más cada 30.
    assert [point.balance for point in forecast.points] == [_bob("3000"), _bob("3500"), _bob("4000")]
    assert forecast.goes_negative_on is None
    assert (forecast.recurring_income, forecast.recurring_expenses) == (_bob("3000"), _bob("700"))
    assert not forecast.limited_history
    # El desglose a 90 días: tres meses de cada cosa.
    last = forecast.points[-1]
    assert (last.recurring_income, last.recurring_expenses, last.goal_contributions, last.variable_spending) == (
        _bob("9000"),
        _bob("2100"),
        _bob("900"),
        _bob("4500"),
    )


def test_la_fecha_en_que_bajaria_de_cero() -> None:
    forecast = project(_inputs(100, recurring=[_monthly("expense", 700, 10)]))

    # 100 − 60 por día (1800 / 30) llega a −20 el día 2.
    assert forecast.goes_negative_on == TODAY + timedelta(days=2)


def test_una_meta_deja_de_restar_cuando_se_cumple() -> None:
    goal = GoalFlow(uuid4(), Decimal(150), Decimal(300))
    forecast = project(_inputs(0, recurring=[], goals=[goal], variable_monthly=Decimal(0)))
    assert forecast.points[0].balance == _bob("-150")


def test_sin_un_mes_de_historial_avisa() -> None:
    assert project(_inputs(0, history_months=0)).limited_history


def test_recurrentes_semanales_y_lo_vencido() -> None:
    weekly = RecurringFlow(
        "expense", Decimal(10), "weekly", TODAY - timedelta(days=14), TODAY - timedelta(days=7), None
    )
    occurrences = weekly.occurrences(TODAY + timedelta(days=30))
    assert occurrences[0] == TODAY - timedelta(days=7)  # vencido y pendiente: cuenta hoy
    assert len(occurrences) == 6


def test_what_if_suma_por_mes() -> None:
    forecast = project(_inputs(2500, extra_monthly=Decimal(-200)))
    assert forecast.points[0].balance == _bob("2800")


def test_un_ingreso_vencido_sin_recibir_no_suma() -> None:
    """Pedido de QA, 2026-10-30: el sueldo vencido no entra hoy; el del mes que viene sí."""
    overdue = RecurringFlow(
        "income", Decimal(4500), "monthly", TODAY - timedelta(days=3), TODAY - timedelta(days=3), None
    )  # type: ignore[arg-type]

    forecast = project(_inputs(641, recurring=[overdue], goals=[], variable_monthly=Decimal(0)))

    # Sin el vencido: 641 + el sueldo del mes que viene (día 18 de noviembre). Con él, 9641.
    assert forecast.points[0].balance == _bob("5141.00")
    assert forecast.recurring_income == _bob("4500.00")
