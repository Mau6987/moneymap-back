"""El código de una moneda: ISO 4217, tres letras mayúsculas.

Cuántos decimales acepta una moneda y si sigue ofreciéndose son datos de
`catalog.currencies`, no constantes del código (constitución §4). Por eso aquí
solo se valida la forma del código.
"""

import re

CURRENCY_CODE_PATTERN = r"^[A-Z]{3}$"

_CURRENCY_CODE = re.compile(CURRENCY_CODE_PATTERN)


class InvalidCurrencyCode(ValueError):
    """El texto no tiene forma de código ISO 4217."""


def validate_currency_code(value: str) -> str:
    """Devuelve el código si tiene forma válida; si no, lanza `InvalidCurrencyCode`."""
    if _CURRENCY_CODE.match(value) is None:
        raise InvalidCurrencyCode(f"«{value}» no es un código de moneda ISO 4217 (tres letras mayúsculas)")
    return value
