"""Las reglas del dinero (constitución §2), sin base de datos."""

from decimal import Decimal

import pytest

from app.core.money import CurrencyMismatchError, InvalidCurrencyCode, Money, validate_currency_code


def test_cuantiza_a_los_decimales_de_su_moneda() -> None:
    assert Money("1000", "CLP", 0).amount == Decimal("1000")
    assert Money("1000.005", "BOB", 2).amount == Decimal("1000.01")


def test_no_acepta_un_monto_en_float() -> None:
    with pytest.raises(TypeError):
        Money(10.5, "BOB", 2)


def test_no_opera_monedas_distintas() -> None:
    with pytest.raises(CurrencyMismatchError):
        Money("10.00", "BOB", 2) + Money("10.00", "USD", 2)
    with pytest.raises(CurrencyMismatchError):
        Money("10.00", "BOB", 2) - Money("10.00", "USD", 2)


def test_suma_y_resta_en_la_misma_moneda() -> None:
    assert Money("2500.00", "BOB", 2) - Money("700.00", "BOB", 2) == Money("1800.00", "BOB", 2)
    assert Money("2500.00", "BOB", 2) + Money("700.00", "BOB", 2) == Money("3200.00", "BOB", 2)


def test_dos_montos_son_iguales_por_cantidad_y_moneda() -> None:
    assert Money("10", "BOB", 2) == Money("10.00", "BOB", 2)
    assert Money("10.00", "BOB", 2) != Money("10.00", "USD", 2)
    assert Money("10.00", "BOB", 2) != "10.00"


def test_el_texto_lleva_los_decimales_de_la_moneda() -> None:
    assert str(Money("1000", "CLP", 0)) == "1000 CLP"
    assert str(Money("69.6", "BOB", 2)) == "69.60 BOB"


def test_rechaza_un_codigo_de_moneda_que_no_es_iso_4217() -> None:
    with pytest.raises(InvalidCurrencyCode):
        validate_currency_code("bob")
    with pytest.raises(InvalidCurrencyCode):
        Money("10.00", "BOLIVIANOS", 2)


def test_rechaza_decimales_fuera_del_rango_de_la_base() -> None:
    with pytest.raises(ValueError):
        Money("10", "BOB", 5)
