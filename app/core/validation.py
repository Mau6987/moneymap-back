"""Tipos Pydantic que comparten los esquemas de todos los módulos.

La regla del dinero (constitución §2) se cumple también en el borde HTTP: los
montos entran y salen como texto y las monedas como código ISO 4217.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field

from app.core.money import InvalidCurrencyCode, validate_currency_code

# Espeja el CHECK de iam.users: los nombres van de 1 a 60 caracteres.
NAME_MAX_LENGTH = 60

# Espeja el CHECK de iam.users.email.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _reject_float(value: object) -> object:
    """Un monto en JSON viaja como texto ("69.60"), nunca como número decimal."""
    if isinstance(value, float):
        raise ValueError("Los montos van como texto, nunca como número decimal")
    return value


def _check_currency_code(value: str) -> str:
    try:
        return validate_currency_code(value)
    except InvalidCurrencyCode as exc:
        raise ValueError(str(exc)) from exc


def _clean_name(value: str) -> str:
    """Colapsa los espacios como el trigger de la base y rechaza el nombre vacío."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("No puede quedar vacío")
    return cleaned


def _normalize_email(value: object) -> object:
    """El correo identifica a la persona: se compara sin espacios ni mayúsculas.

    Va antes de validar la forma, porque "  Ana@X.com " es el mismo correo que
    "ana@x.com" y así choca con el correo repetido (RF-4) en vez de con un error
    de formato.
    """
    return value.strip().lower() if isinstance(value, str) else value


# Un monto: Decimal exacto, en texto. Pydantic lo serializa como texto.
MoneyAmount = Annotated[Decimal, BeforeValidator(_reject_float)]

# Una moneda: el código ISO 4217. Si existe y está activa lo responde la base.
CurrencyCode = Annotated[str, AfterValidator(_check_currency_code)]

# Un nombre: sin espacios de sobra y con la forma que acepta la base.
Name = Annotated[str, Field(max_length=NAME_MAX_LENGTH), AfterValidator(_clean_name)]

# Un correo: normalizado y con forma de correo.
Email = Annotated[str, BeforeValidator(_normalize_email), Field(pattern=EMAIL_PATTERN, max_length=320)]
