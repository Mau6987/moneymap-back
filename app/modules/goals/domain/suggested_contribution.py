"""Cuánto aportar en cada periodo de ahorro para llegar a la fecha de la meta: Python puro."""

import calendar
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Literal

PeriodType = Literal["weekly", "semi_monthly", "monthly"]

_DAYS_IN_WEEK = 7
_DAYS_IN_FORTNIGHT = 15


def add_months(day: date, months: int) -> date:
    """El 31 pasa al último día del mes."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def periods_until(today: date, target: date, period_type: PeriodType) -> int:
    """Los periodos completos hasta `target`, al menos uno.

    Se cuenta por meses y no por días: dos meses son cuatro quincenas aunque
    uno sea febrero.
    """
    if period_type == "weekly":
        return max((target - today).days // _DAYS_IN_WEEK, 1)
    months = (target.year - today.year) * 12 + target.month - today.month
    if add_months(today, months) > target:
        months -= 1
    if period_type == "monthly":
        return max(months, 1)
    extra_fortnight = (target - add_months(today, months)).days >= _DAYS_IN_FORTNIGHT
    return max(months * 2 + int(extra_fortnight), 1)


def suggested_contribution(
    remaining: Decimal, today: date, target: date | None, period_type: PeriodType
) -> Decimal | None:
    """Lo que falta entre los periodos, hacia arriba a la unidad para no quedar corto.

    None si no hay con qué calcular: sin fecha, con la fecha vencida o sin nada por juntar.
    """
    if target is None or target < today or remaining <= 0:
        return None
    per_period = (remaining / periods_until(today, target, period_type)).to_integral_value(ROUND_CEILING)
    return min(per_period, remaining)
