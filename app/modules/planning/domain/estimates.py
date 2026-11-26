"""Las fechas estimadas de las metas, compartidas por Can I Afford It? y What If?: Python puro."""

import calendar
from datetime import date
from decimal import ROUND_CEILING, Decimal

# Más de 100 años no es una estimación: se responde sin fecha.
MAX_MONTHS = 1200


def months_needed(amount: Decimal, per_month: Decimal | None) -> int | None:
    """Los meses para juntar `amount` a `per_month`. None sin ritmo o a más de 100 años."""
    if per_month is None or per_month <= 0:
        return None
    months = int((max(amount, Decimal(0)) / per_month).to_integral_value(ROUND_CEILING))
    return months if months <= MAX_MONTHS else None


def add_months(day: date, months: int) -> date:
    """Como `date + interval` en PostgreSQL: el 31 pasa al último día del mes."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))
