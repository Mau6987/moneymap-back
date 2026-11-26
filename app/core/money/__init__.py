"""Vocabulario compartido del dinero (constitución §2).

Los módulos de finanzas, metas, planificación y reportes usan estos tipos en
lugar de reimplementar las reglas: montos exactos en `Decimal`, una sola moneda
por operación y ninguna suma entre monedas distintas.
"""

from app.core.money.currency import (
    CURRENCY_CODE_PATTERN,
    InvalidCurrencyCode,
    validate_currency_code,
)
from app.core.money.money import CurrencyMismatchError, Money

__all__ = [
    "CURRENCY_CODE_PATTERN",
    "CurrencyMismatchError",
    "InvalidCurrencyCode",
    "Money",
    "validate_currency_code",
]
