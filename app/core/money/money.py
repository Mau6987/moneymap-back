"""Un monto exacto en una sola moneda.

Decodifica la constitución §2: decimales exactos (nunca `float`), los decimales
de la moneda como dato (`catalog.currencies.decimals`) y ninguna operación
entre monedas distintas, porque MoneyMap no convierte.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.money.currency import validate_currency_code

# catalog.currencies.decimals va de 0 (CLP, PYG) a 4 (el numeric(19,4) de la base)
MIN_DECIMALS = 0
MAX_DECIMALS = 4


class CurrencyMismatchError(ValueError):
    """Se intentó operar con montos de monedas distintas (constitución §2)."""


class Money:
    """Un monto exacto: la cantidad, su moneda y cuántos decimales acepta esa moneda."""

    __slots__ = ("_amount", "_currency", "_decimals")

    def __init__(self, amount: Decimal | int | str, currency: str, decimals: int) -> None:
        if isinstance(amount, float):
            raise TypeError("Los montos van en Decimal, nunca en float (constitución §2)")
        if not MIN_DECIMALS <= decimals <= MAX_DECIMALS:
            raise ValueError(f"Decimales fuera del rango {MIN_DECIMALS}–{MAX_DECIMALS}: {decimals}")
        self._decimals = decimals
        self._currency = validate_currency_code(currency)
        self._amount = _quantize(Decimal(amount), decimals)

    @property
    def amount(self) -> Decimal:
        """La cantidad, ya redondeada a los decimales de la moneda."""
        return self._amount

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def decimals(self) -> int:
        return self._decimals

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self._amount + other._amount, self._currency, self._decimals)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self._amount - other._amount, self._currency, self._decimals)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount == other._amount and self._currency == other._currency

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __str__(self) -> str:
        return f"{format(self._amount, 'f')} {self._currency}"

    def __repr__(self) -> str:
        return f"Money(amount={self._amount!r}, currency={self._currency!r}, decimals={self._decimals})"

    def _assert_same_currency(self, other: Money) -> None:
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"No se pueden operar montos en {self._currency} y {other._currency}: MoneyMap no convierte monedas"
            )


def _quantize(amount: Decimal, decimals: int) -> Decimal:
    """Redondea a los decimales de la moneda, como el round() de la base."""
    return amount.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
