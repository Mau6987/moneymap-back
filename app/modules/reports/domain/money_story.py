"""La Money Story de un mes en una moneda (spec 006, RF-1 a RF-4): Python puro.

El worker arma las frases destacadas como claves y parámetros, sin texto ni IA;
la API las vuelve texto con las plantillas de `catalog.story_templates`. Así se
cambia una frase sin regenerar las historias guardadas.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

TEMPLATE_VERSION = "1"

# Los parámetros que son montos o meses: al renderizar llevan símbolo o nombre.
_AMOUNT_PARAMS = frozenset({"income", "expense", "savings", "deficit", "amount", "difference"})
_MONTH_PARAMS = frozenset({"month", "previous_month"})
_MONTH_NAMES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()

# reports.money_stories.savings_rate es numeric(7,4): un mes con ingresos casi
# nulos y muchos gastos no entra, y la tasa queda en null.
_MAX_RATE = Decimal("999.9999")


@dataclass(frozen=True, slots=True)
class MonthFacts:
    """Lo que pasó en un mes en una moneda. `top_category` es (nombre, total) del mayor gasto."""

    month: date
    decimals: int
    income: Decimal
    expense: Decimal
    goals_contributed: Decimal
    top_category: tuple[str, Decimal] | None

    @property
    def savings(self) -> Decimal:
        return self.income - self.expense


@dataclass(frozen=True, slots=True)
class Story:
    """Lo que se guarda en `reports.money_stories`."""

    savings_rate: Decimal | None
    highlights: list[dict[str, Any]]
    comparison: dict[str, Any] | None


def build_story(current: MonthFacts, previous: MonthFacts | None) -> Story:
    """RF-1 a RF-3. `previous` es None si el mes anterior no tuvo movimientos en la moneda."""
    amount = _formatter(current.decimals)
    highlights: list[dict[str, Any]] = [
        _line("summary", month=_period(current.month), income=amount(current.income), expense=amount(current.expense))
    ]
    if current.savings > 0:
        rate = (current.savings / current.income * 100).quantize(Decimal(1))
        highlights.append(_line("saved", savings=amount(current.savings), rate=str(rate)))
    elif current.savings < 0:
        highlights.append(_line("overspent", deficit=amount(-current.savings)))
    else:
        highlights.append(_line("balanced"))
    if current.top_category is not None:
        name, total = current.top_category
        highlights.append(_line("top_expense_category", category=name, amount=amount(total)))
    if current.goals_contributed > 0:
        highlights.append(_line("goals_contributed", amount=amount(current.goals_contributed)))

    comparison = None
    if previous is None:
        highlights.append(_line("first_month"))
    else:
        for key, now, before in (
            ("income", current.income, previous.income),
            ("savings", current.savings, previous.savings),
        ):
            change = "up" if now > before else "down" if now < before else "same"
            params: dict[str, str] = {"previous_month": _period(previous.month)}
            if change != "same":
                params["difference"] = amount(abs(now - before))
            highlights.append(_line(f"{key}_{change}", **params))
        comparison = {
            "period": _period(previous.month),
            "income_total": amount(previous.income),
            "expense_total": amount(previous.expense),
            "savings_total": amount(previous.savings),
            "goals_contributed": amount(previous.goals_contributed),
            "top_expense_category": None
            if previous.top_category is None
            else {"name": previous.top_category[0], "total": amount(previous.top_category[1])},
        }
    return Story(_savings_rate(current), highlights, comparison)


def render(body: str, params: dict[str, str], symbol: str) -> str:
    """El texto de una frase: su plantilla con los montos con símbolo y los meses con nombre."""
    shown = {
        name: f"{symbol} {value}"
        if name in _AMOUNT_PARAMS
        else _MONTH_NAMES[int(value[5:7]) - 1]
        if name in _MONTH_PARAMS
        else value
        for name, value in params.items()
    }
    return body.format_map(shown)


def month_name(month: date) -> str:
    return _MONTH_NAMES[month.month - 1]


def _savings_rate(facts: MonthFacts) -> Decimal | None:
    if facts.income == 0:
        return None
    rate = (facts.savings / facts.income).quantize(Decimal("0.0001"))
    return rate if abs(rate) <= _MAX_RATE else None


def _line(key: str, **params: str) -> dict[str, Any]:
    return {"key": key, "params": params}


def _period(month: date) -> str:
    return month.strftime("%Y-%m")


def _formatter(decimals: int) -> Callable[[Decimal], str]:
    step = Decimal(1).scaleb(-decimals)
    return lambda value: str(Decimal(value).quantize(step))
