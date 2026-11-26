"""El aporte sugerido por periodo de ahorro (spec 005, RF-23)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.goals.domain.suggested_contribution import (
    PeriodType,
    periods_until,
    suggested_contribution,
)

TODAY = date(2026, 11, 5)


def test_el_ejemplo_del_pedido_mil_en_dos_meses_quincenal_son_250() -> None:
    assert suggested_contribution(Decimal(1000), TODAY, date(2027, 1, 5), "semi_monthly") == Decimal(250)


def test_se_calcula_sobre_lo_que_falta() -> None:
    assert suggested_contribution(Decimal(600), TODAY, date(2027, 1, 5), "semi_monthly") == Decimal(150)


@pytest.mark.parametrize(
    ("today", "target", "period_type", "periods"),
    [
        (date(2027, 1, 1), date(2027, 3, 1), "semi_monthly", 4),  # 59 días con febrero: siguen siendo 4
        (date(2027, 1, 31), date(2027, 2, 28), "monthly", 1),  # el 31 cae en el último día de febrero
        (TODAY, date(2027, 1, 20), "semi_monthly", 5),  # 2 meses y 15 días
        (TODAY, date(2027, 1, 19), "semi_monthly", 4),  # 2 meses y 14 días
        (TODAY, date(2027, 1, 5), "monthly", 2),
        (TODAY, date(2027, 1, 4), "monthly", 1),
        (TODAY, date(2026, 11, 26), "weekly", 3),
        (TODAY, date(2028, 11, 5), "monthly", 24),
    ],
)
def test_cuenta_los_periodos_completos(today: date, target: date, period_type: PeriodType, periods: int) -> None:
    assert periods_until(today, target, period_type) == periods


@pytest.mark.parametrize("period_type", ["weekly", "semi_monthly", "monthly"])
def test_con_menos_de_un_periodo_es_todo_lo_que_falta(period_type: PeriodType) -> None:
    assert suggested_contribution(Decimal("120.50"), TODAY, TODAY, period_type) == Decimal("120.50")


def test_redondea_hacia_arriba_a_la_unidad() -> None:
    assert suggested_contribution(Decimal(1000), TODAY, date(2027, 2, 5), "monthly") == Decimal(334)


def test_el_redondeo_no_pasa_de_lo_que_falta() -> None:
    assert suggested_contribution(Decimal("0.50"), TODAY, date(2027, 1, 5), "monthly") == Decimal("0.50")


@pytest.mark.parametrize(
    ("remaining", "target"),
    [
        (Decimal(1000), None),  # sin fecha
        (Decimal(1000), date(2026, 11, 4)),  # vencida
        (Decimal(0), date(2027, 1, 5)),  # ya está todo
        (Decimal(-5), date(2027, 1, 5)),
    ],
)
def test_sin_con_que_calcular_no_hay_sugerencia(remaining: Decimal, target: date | None) -> None:
    assert suggested_contribution(remaining, TODAY, target, "monthly") is None
