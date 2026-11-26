"""El texto de cada aviso push (spec 006, RF-14 a RF-17): Python puro.

Con el modo privado (`hide_amounts`) ningún texto lleva montos ni nombres.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# notify.notifications: title hasta 120 y body hasta 500.
_MAX_BODY = 500


@dataclass(frozen=True, slots=True)
class DuePayment:
    description: str
    amount: Decimal
    symbol: str
    decimals: int


def money(amount: Decimal, symbol: str, decimals: int) -> str:
    return f"{symbol} {amount.quantize(Decimal(1).scaleb(-decimals))}"


def recurring_reminder(due_on: date, today: date, payments: list[DuePayment], private: bool) -> tuple[str, str]:
    """RF-15: un solo aviso para todos los pagos recurrentes del mismo día."""
    when = (
        "hoy" if due_on == today else "mañana" if due_on == today + timedelta(days=1) else due_on.strftime("el %d/%m")
    )
    count = len(payments)
    title = f"Tienes un pago recurrente {when}" if count == 1 else f"Tienes {count} pagos recurrentes {when}"
    if private:
        return title, "Abre MoneyMap para verlo." if count == 1 else "Abre MoneyMap para verlos."
    body = ", ".join(
        f"{payment.description} ({money(payment.amount, payment.symbol, payment.decimals)})" for payment in payments
    )
    return title, f"{body}." if len(body) < _MAX_BODY else body[: _MAX_BODY - 1] + "…"


def money_story_ready(month_name: str) -> tuple[str, str]:
    """RF-17: no lleva montos, así que es igual con el modo privado."""
    return "Tu Money Story está lista", f"Mira cómo te fue en {month_name}."


def goal_milestone(name: str, milestone: int, saved: str, target: str, private: bool) -> tuple[str, str]:
    """RF-16: un aviso al llegar al 25, 50 y 75 % de una meta, y otro al cumplirla."""
    if milestone == 100:
        return "Cumpliste tu meta", "Abre MoneyMap para verla." if private else f"{name}: llegaste a {target}."
    title = f"Vas por el {milestone} % de tu meta"
    return title, "Abre MoneyMap para ver cómo va." if private else f"{name}: llevas {saved} de {target}."


def budget_alert(category: str, threshold: int, spent: str, amount: str, private: bool) -> tuple[str, str]:
    """Spec 009, RF-10 y RF-11: al 80 % y al pasar el 100 % de un presupuesto, en el mes."""
    if private:
        title = "Superaste un presupuesto" if threshold == 100 else "Usaste el 80 % de un presupuesto"
        return title, "Abre MoneyMap para verlo."
    title = f"Superaste tu presupuesto de {category}" if threshold == 100 else f"Usaste el 80 % de {category}"
    return title, f"Llevas {spent} de {amount} este mes."
