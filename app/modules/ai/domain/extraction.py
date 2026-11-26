"""De la frase al movimiento prellenado (spec 012, RF-5 y RF-6).

Al LLM van solo la frase, el "hoy" del usuario y los nombres de sus categorías,
cuentas activas y monedas: nunca saldos ni historial. Responde con nombres y
acá se cambian por los ids. Lo que
devuelve se valida contra esas listas: un id que no es del usuario se descarta
y el campo pasa a `missing`, para que la app lo pida en vez de adivinarlo.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

# Cambia cuando cambian las instrucciones: queda en cada dictado para comparar precisión.
PROMPT_VERSION = "extract-v4"
FIELDS = ("kind", "amount", "currency", "category_id", "account_id", "description", "occurred_on")
# Lo que escribe el modelo: categoría y cuenta por nombre, que un modelo chico elige mejor que un id.
_ANSWER = ("kind", "amount", "currency", "category", "account", "description", "occurred_on")
DESCRIPTION_MAX_LENGTH = 120
# Más que esto en una frase es raro; lo que sobra se dicta aparte.
MAX_MOVEMENTS = 5


class InvalidOutput(Exception):
    """El modelo respondió algo que no es el JSON pedido: se prueba el siguiente."""


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    kind: str  # income o expense


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    name: str
    currency: str
    type: str  # cash o card


@dataclass(frozen=True, slots=True)
class Context:
    today: date
    categories: list[Category]
    accounts: list[Account]
    currencies: list[str]


@dataclass(frozen=True, slots=True)
class Movement:
    kind: str | None = None
    amount: str | None = None
    currency: str | None = None
    category_id: str | None = None
    account_id: str | None = None
    description: str | None = None
    occurred_on: str | None = None
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Extraction(Movement):
    """El primer movimiento arriba, como antes, y todos en `movements`."""

    multiple: bool = False
    movements: list[Movement] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


_NULLABLE_STRING = {"type": ["string", "null"]}

# Ollama obliga a que la respuesta siga este esquema.
_MOVEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {name: _NULLABLE_STRING for name in _ANSWER},
    "required": list(_ANSWER),
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "movements": {"type": "array", "items": _MOVEMENT_SCHEMA, "minItems": 1, "maxItems": MAX_MOVEMENTS},
    },
    "required": ["movements"],
}

_INSTRUCTIONS = """Sos el asistente de MoneyMap, una app de finanzas personales de Bolivia.
Convertí la frase del usuario en sus movimientos y respondé solo con el JSON pedido.
- movements: uno por cada gasto o ingreso que dice la frase, en el orden en que los dice
  ("pollo 15, aceite 13 y mi sueldo 4500" son tres). Cada uno con los campos de abajo.
- kind: "expense" si gastó o pagó, "income" si recibió o le pagaron.
- amount: el monto como texto, solo dígitos y punto decimal, sin separador de miles ni símbolo de moneda.
  En Bolivia el punto separa los miles y la coma los decimales: "3.000" es "3000" y "1.250,50" es "1250.50".
  Un monto dicho en palabras va en dígitos: "veinte" es "20".
- currency: el código de una de las monedas del usuario. "Bs" o "bolivianos" es BOB y "dólares" es USD.
  Si la frase no dice la moneda, usá la de la cuenta elegida.
- category: el nombre exacto de una categoría, de "categorias_gasto" si kind es "expense" o de
  "categorias_ingreso" si es "income". Elegí la más parecida aunque el nombre no sea igual: lo que
  compró para cocinar ("pollo", "aceite") va en súper, lo que comió afuera ("cena", "almuerzo") en
  restaurantes, "taxi" en transporte y "sueldo" o "me pagaron" en salario o sueldo. Dejala en null
  solo si ninguna tiene que ver.
- account: el nombre exacto de una de las cuentas. "Efectivo" es una cuenta cash; "con tarjeta" o
  el nombre de una tarjeta es una cuenta card.
- description: el concepto en pocas palabras ("Almuerzo", "Netflix", "Taxi").
- occurred_on: copiá la fecha de "fechas" que corresponde a lo que dice la frase ("ayer", "anteayer",
  "el lunes"). Si la frase no dice ninguna fecha, usá la de "hoy". Solo si dice una fecha exacta
  ("el 3 de octubre"), escribila en formato AAAA-MM-DD.
- Lo que la frase no dice y no podés deducir va en null; no lo adivines.
"""

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _calendar(today: date) -> dict[str, str]:
    """Las fechas ya calculadas: un modelo chico se equivoca contando días."""
    days = {"hoy": today, "ayer": today - timedelta(days=1), "anteayer": today - timedelta(days=2)}
    for back in range(1, 8):
        day = today - timedelta(days=back)
        days.setdefault(f"el {_WEEKDAYS[day.weekday()]}", day)
    return {name: day.isoformat() for name, day in days.items()}


def build_messages(phrase: str, context: Context) -> list[dict[str, str]]:
    """Las instrucciones fijas primero, así Ollama las reusa de un dictado a otro."""
    # Sin ids: un UUID son decenas de tokens que el modelo escribe uno por uno.
    data = {
        "categorias_gasto": [c.name for c in context.categories if c.kind == "expense"],
        "categorias_ingreso": [c.name for c in context.categories if c.kind == "income"],
        "cuentas": [{"nombre": a.name, "moneda": a.currency, "tipo": a.type} for a in context.accounts],
        "monedas": context.currencies,
        "fechas": _calendar(context.today),
        "frase": phrase,
    }
    return [
        {"role": "system", "content": _INSTRUCTIONS},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
    ]


def parse(raw: str, context: Context) -> Extraction:
    """Valida la respuesta del modelo contra lo que el usuario tiene."""
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise InvalidOutput("no es JSON") from error
    items = data.get("movements") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
        raise InvalidOutput("no trae movimientos")

    movements = [_movement(item, context) for item in items[:MAX_MOVEMENTS]]
    return Extraction(**asdict(movements[0]), multiple=len(movements) > 1, movements=movements)


def _movement(data: dict[str, Any], context: Context) -> Movement:
    kind = data.get("kind") if data.get("kind") in ("income", "expense") else None
    # El nombre es único por usuario y tipo (categories_name_uq).
    categories = {(c.kind, c.name.casefold()): c for c in context.categories}
    accounts = {a.name.casefold(): a for a in context.accounts}
    category = categories.get((str(kind), str(data.get("category")).casefold()))
    account = accounts.get(str(data.get("account")).casefold())
    currency = data.get("currency") if data.get("currency") in context.currencies else None
    values = {
        "kind": kind,
        "amount": _amount(data.get("amount")),
        "currency": currency or (account.currency if account else None),
        "category_id": category.id if category else None,
        "account_id": account.id if account and (currency is None or account.currency == currency) else None,
        "description": _description(data.get("description")),
        "occurred_on": _date(data.get("occurred_on"), context.today),
    }
    missing = [name for name in FIELDS if values[name] is None]
    return Movement(**values, missing=missing)


# "1.250" o "3.000.000": el punto separa miles, como se escribe en Bolivia.
_THOUSANDS = re.compile(r"\d{1,3}(\.\d{3})+")


def _amount(value: object) -> str | None:
    """Por si el modelo copia el monto como lo escribió el usuario: "1.250,50" es 1250.50."""
    text = str(value).strip()
    if "," in text or _THOUSANDS.fullmatch(text):
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return str(amount) if amount.is_finite() and amount > 0 else None


def _description(value: object) -> str | None:
    text = " ".join(str(value).split())[:DESCRIPTION_MAX_LENGTH] if isinstance(value, str) else ""
    return text or None


def _date(value: object, today: date) -> str | None:
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        return today.isoformat() if value is None else None
    return day.isoformat() if day <= today else None
