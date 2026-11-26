"""Validar lo que devuelve el LLM (spec 012, RF-6)."""

import json
from datetime import date

import pytest

from app.modules.ai.domain.extraction import Account, Category, Context, InvalidOutput, build_messages, parse

CONTEXT = Context(
    today=date(2026, 10, 23),
    categories=[Category("food", "Comida", "expense"), Category("salary", "Sueldo", "income")],
    accounts=[Account("cash", "Efectivo", "BOB", "cash"), Account("visa", "Visa", "USD", "card")],
    currencies=["BOB", "USD"],
)


def _movement(**fields: object) -> dict[str, object]:
    """Como responde el modelo: categoría y cuenta por nombre."""
    base = {"kind": "expense", "amount": "50", "currency": "BOB", "category": "comida", "account": "Efectivo"}
    return base | {"description": "Almuerzo", "occurred_on": "2026-10-22", **fields}


def _parse(**fields: object) -> dict[str, object]:
    return parse(json.dumps({"movements": [_movement(**fields)]}), CONTEXT).to_json()


def test_una_frase_completa_no_deja_nada_pendiente() -> None:
    movement = {
        "kind": "expense",
        "amount": "50",
        "currency": "BOB",
        "category_id": "food",
        "account_id": "cash",
        "description": "Almuerzo",
        "occurred_on": "2026-10-22",
        "missing": [],
    }
    assert _parse() == {**movement, "multiple": False, "movements": [movement]}


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"category": "Inventada"}, ["category_id"]),
        ({"category": "Sueldo"}, ["category_id"]),  # una categoría de ingreso en un gasto
        ({"account": "Visa"}, ["account_id"]),  # la Visa es en USD y la frase dice BOB
        ({"amount": "-5"}, ["amount"]),
        ({"currency": "EUR", "account": None}, ["currency", "account_id"]),
        ({"occurred_on": "2026-12-01"}, ["occurred_on"]),  # en el futuro
        ({"category": "food"}, ["category_id"]),  # el id en vez del nombre
    ],
    ids=["nombre_ajeno", "otro_tipo", "otra_moneda", "negativo", "moneda_ajena", "futuro", "id"],
)
def test_lo_que_no_es_del_usuario_pasa_a_missing(fields: dict[str, object], missing: list[str]) -> None:
    result = _parse(**fields)

    assert result["missing"] == missing
    assert all(result[name] is None for name in missing)


def test_sin_moneda_usa_la_de_la_cuenta_y_sin_fecha_es_hoy() -> None:
    result = _parse(currency=None, account="visa", occurred_on=None)

    assert (result["currency"], result["occurred_on"], result["missing"]) == ("USD", "2026-10-23", [])


@pytest.mark.parametrize("raw", ["no es json", "[1, 2]", '{"movements": []}', '{"kind": "expense"}'])
def test_lo_que_no_es_un_objeto_json_es_invalido(raw: str) -> None:
    with pytest.raises(InvalidOutput):
        parse(raw, CONTEXT)


def test_al_llm_no_van_saldos_ni_ids_solo_nombres() -> None:
    _, user = build_messages("gasté 50 en comida", CONTEXT)

    data = json.loads(user["content"])
    assert (data["categorias_gasto"], data["categorias_ingreso"]) == (["Comida"], ["Sueldo"])
    assert data["cuentas"][0] == {
        "nombre": "Efectivo",
        "moneda": "BOB",
        "tipo": "cash",
    }


def test_las_fechas_van_calculadas_y_las_instrucciones_no_cambian_de_un_dia_a_otro() -> None:
    """2026-10-23 es viernes: un modelo chico se equivoca contando días."""
    system, user = build_messages("gasté 50 el lunes", CONTEXT)

    fechas = json.loads(user["content"])["fechas"]
    assert (fechas["hoy"], fechas["ayer"], fechas["anteayer"]) == ("2026-10-23", "2026-10-22", "2026-10-21")
    assert (fechas["el lunes"], fechas["el viernes"]) == ("2026-10-19", "2026-10-16")
    assert system == build_messages("otra frase", Context(date(2027, 1, 1), [], [], []))[0]


@pytest.mark.parametrize(
    ("said", "amount"),
    [
        ("50", "50"),
        ("15.50", "15.50"),
        ("3.000", "3000"),
        ("1.250,50", "1250.50"),
        ("12,5", "12.5"),
        ("2.500.000", "2500000"),
    ],
)
def test_el_monto_se_lee_como_se_escribe_en_bolivia(said: str, amount: str) -> None:
    assert _parse(amount=said)["amount"] == amount


def test_si_dicta_varios_movimientos_vienen_todos_y_el_primero_arriba() -> None:
    said = [
        _movement(amount="15", description="Pollo"),
        _movement(amount="13", description="Aceite", category="Inventada"),
        _movement(kind="income", amount="4500", category="Sueldo", description="Sueldo"),
    ]

    result = parse(json.dumps({"movements": said}), CONTEXT).to_json()

    assert (result["multiple"], result["amount"], result["description"]) == (True, "15", "Pollo")
    movements = result["movements"]
    assert [(m["kind"], m["amount"]) for m in movements] == [("expense", "15"), ("expense", "13"), ("income", "4500")]
    assert (movements[1]["missing"], movements[2]["category_id"]) == (["category_id"], "salary")


def test_mas_de_cinco_movimientos_se_cortan() -> None:
    raw = json.dumps({"movements": [_movement(amount=str(n)) for n in range(1, 8)]})

    assert len(parse(raw, CONTEXT).movements) == 5
