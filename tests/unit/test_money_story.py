"""Las frases de la Money Story sin base de datos (spec 006, RF-2 a RF-4)."""

from datetime import date
from decimal import Decimal

from app.modules.reports.domain.money_story import MonthFacts, build_story, render


def _facts(month: int, income: str, expense: str, decimals: int = 2) -> MonthFacts:
    return MonthFacts(date(2026, month, 1), decimals, Decimal(income), Decimal(expense), Decimal(0), None)


def test_compara_a_la_baja_y_sin_cambios() -> None:
    story = build_story(_facts(10, "100", "100"), _facts(9, "100", "50"))

    assert [line["key"] for line in story.highlights] == ["summary", "balanced", "income_same", "savings_down"]
    assert story.highlights[3]["params"] == {"previous_month": "2026-09", "difference": "50.00"}
    assert story.savings_rate == Decimal(0)


def test_respeta_los_decimales_y_deja_la_tasa_en_null_si_no_cabe() -> None:
    story = build_story(_facts(10, "1", "5000000", decimals=0), None)

    assert story.highlights[1] == {"key": "overspent", "params": {"deficit": "4999999"}}
    assert story.savings_rate is None


def test_render_pone_simbolo_y_nombre_del_mes() -> None:
    text = render("En {month} entraron {income}.", {"month": "2026-09", "income": "10.50"}, "Bs")

    assert text == "En septiembre entraron Bs 10.50."
