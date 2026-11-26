"""Las reglas de Can I Afford It? (PRD §6.13) sin base: Safe to Spend, metas y flujo falsos.

El caso base: periodo del 1 al 31 de octubre, hoy el 15. Safe to Spend de 500
(saldo 1.700, 700 de alquiler pendiente y 500 de metas), sueldo de 3.000 el día
20 y un gasto variable de 600 al mes.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.money import Money
from app.modules.finance.domain.models import SafeToSpend
from app.modules.planning.application.queries.check_affordability import check_affordability
from app.modules.planning.domain.forecast import RecurringFlow
from app.modules.planning.domain.models import Affordability, GoalPace, GoalPaces, PurchaseCheck

TODAY = date(2026, 10, 15)
STARTS_ON = date(2026, 10, 1)
ENDS_ON = date(2026, 10, 31)


def _bob(amount: str) -> Money:
    return Money(amount, "BOB", 2)


class _SafeToSpend:
    """1.700 de saldo menos 700 de alquiler y 500 de metas: 500 libres."""

    async def compute(self, user_id: UUID, currency: str | None) -> SafeToSpend:
        zero = _bob("0")
        return SafeToSpend("BOB", STARTS_ON, ENDS_ON, _bob("1700"), _bob("700"), zero, _bob("500"), _bob("3000"))


class _Planning:
    def __init__(self, goals: list[GoalPace]) -> None:
        self._goals = goals

    async def is_expense_category(self, user_id: UUID, category_id: UUID) -> bool:
        return True

    async def assert_amount(self, amount: Decimal, currency: str) -> None:
        return None

    async def goal_paces(self, user_id: UUID, currency: str, starts_on: date, ends_on: date) -> GoalPaces:
        return GoalPaces(TODAY, self._goals)

    async def consume_check(self, user_id: UUID) -> bool:
        return True


class _Forecast:
    def __init__(self, recurring: list[RecurringFlow], variable: str = "600", history: int = 3) -> None:
        self._recurring = recurring
        self._variable = Decimal(variable)
        self._history = history

    async def recurring(self, user_id: UUID, currency: str) -> list[RecurringFlow]:
        return self._recurring

    async def variable_spending(self, user_id: UUID, currency: str) -> tuple[date, Decimal, int]:
        return TODAY, self._variable, self._history


SALARY = RecurringFlow("income", Decimal("3000"), "monthly", date(2026, 1, 20), date(2026, 10, 20), None)
RENT = RecurringFlow("expense", Decimal("700"), "monthly", date(2026, 1, 25), date(2026, 10, 25), None)

# Ya en el orden en que se informan: la de menor prioridad primero.
TRIP = GoalPace(uuid4(), "Viaje", Decimal("4800"), Decimal("200"), Decimal("200"))
FUND = GoalPace(uuid4(), "Fondo", Decimal("4700"), Decimal("300"), Decimal("300"))


async def _check(
    amount: str,
    goals: list[GoalPace] | None = None,
    recurring: list[RecurringFlow] | None = None,
    variable: str = "600",
    history: int = 3,
) -> Affordability:
    return await check_affordability(
        PurchaseCheck(Decimal(amount), "BOB", None),
        uuid4(),
        _SafeToSpend(),
        _Planning(goals if goals is not None else [TRIP, FUND]),
        _Forecast([SALARY, RENT] if recurring is None else recurring, variable, history),
    )


async def test_lo_que_entra_en_el_disponible_es_affordable() -> None:
    # 500 libres + 3.000 del sueldo − 340 de gasto variable (17 días): 3.160.
    result = await _check("3160")

    assert (result.verdict, result.available, result.available_after, result.goal_impacts) == (
        "affordable",
        _bob("3160"),
        _bob("0"),
        [],
    )


async def test_el_sueldo_que_falta_llegar_cuenta_para_la_compra() -> None:
    # Sin el sueldo, 2.000 no entrarían en el Safe to Spend de 500.
    result = await _check("2000")

    assert (result.verdict, result.income_in_period, result.available_after) == (
        "affordable",
        _bob("3000"),
        _bob("1160"),
    )


async def test_la_fecha_es_el_dia_en_que_alcanza() -> None:
    # Faltan 840. El 15 de noviembre hay 2.610 (3.160 menos 15 días de variable
    # y metas, a 1.100 al mes); el 20 llega el sueldo y alcanza.
    result = await _check("4000")

    assert (result.verdict, result.estimated_on) == ("not_yet", date(2026, 11, 20))
    assert result.monthly_surplus == _bob("1200")
    assert [impact.name for impact in result.goal_impacts] == ["Viaje", "Fondo"]


async def test_la_curva_va_mes_a_mes_desde_el_disponible_y_cierra_el_dia_que_alcanza() -> None:
    # Empieza en el disponible (3.160), no en el saldo (1.700), y no vuelve a
    # contar el sueldo del 20 de octubre ni el variable de octubre: ya están ahí.
    result = await _check("4000")

    # El 15 de noviembre no queda: el 20 es del mismo mes y la app y la web
    # rotulan los puntos por mes.
    assert [(point.on, point.balance) for point in result.projection] == [
        (TODAY, _bob("3160")),
        (date(2026, 11, 20), _bob("5426.67")),
    ]


async def test_la_curva_no_repite_el_mes() -> None:
    # Sin el sueldo de noviembre alcanza más tarde: un punto por mes y el último
    # reemplaza al de su mes.
    result = await _check("12000", goals=[])

    months = [(point.on.year, point.on.month) for point in result.projection[1:]]
    assert len(months) == len(set(months))
    assert result.projection[-1].on == result.estimated_on
    assert result.projection[-1].balance.amount >= Decimal("12000")


async def test_las_metas_son_informacion_no_una_forma_de_pagar() -> None:
    # Faltan 340: salen del Viaje (200) y del Fondo (140), pero el veredicto es not_yet.
    result = await _check("3500")

    assert result.verdict == "not_yet"
    assert [(i.name, i.amount) for i in result.goal_impacts] == [("Viaje", _bob("200")), ("Fondo", _bob("140"))]


async def test_sin_metas_igual_hay_fecha_por_el_sobrante() -> None:
    # Sin metas, el 20 de noviembre hay 2.760 + 3.000 de sueldo: alcanza.
    result = await _check("5000", goals=[])

    assert (result.verdict, result.estimated_on, result.goal_impacts) == ("not_yet", date(2026, 11, 20), [])


async def test_si_el_sobrante_no_es_positivo_no_hay_fecha() -> None:
    result = await _check("5000", variable="3000")

    assert (result.verdict, result.estimated_on, result.monthly_surplus) == ("not_yet", None, _bob("-1200"))


async def test_sin_historial_lo_avisa() -> None:
    result = await _check("5000", history=0)

    assert result.limited_history is True


async def test_el_gasto_variable_que_falta_resta_del_disponible() -> None:
    # 17 días de 30 con 600 al mes: 340. Sin gasto variable el disponible es 3.500.
    with_variable = await _check("3400")
    without_variable = await _check("3400", variable="0")

    assert (with_variable.verdict, with_variable.remaining_variable_spending, with_variable.available) == (
        "not_yet",
        _bob("340"),
        _bob("3160"),
    )
    assert (without_variable.verdict, without_variable.available) == ("affordable", _bob("3500"))


async def test_un_gasto_anual_cuenta_en_el_ritmo_y_en_la_fecha() -> None:
    # Un seguro de 12.000 el 1 de diciembre: el ritmo mensual le resta 1.000 y
    # la compra de 6.000 se corre hasta que el sueldo lo recupera.
    insurance = RecurringFlow("expense", Decimal("12000"), "yearly", date(2025, 12, 1), date(2026, 12, 1), None)
    without = await _check("6000", goals=[])
    with_insurance = await _check("6000", goals=[], recurring=[SALARY, RENT, insurance])

    assert with_insurance.monthly_surplus == _bob("700")
    assert without.estimated_on is not None and with_insurance.estimated_on is not None
    assert with_insurance.estimated_on > without.estimated_on
    assert with_insurance.projection[-1].balance.amount >= Decimal("6000")


async def test_si_no_se_junta_en_5_anios_no_hay_fecha_ni_curva() -> None:
    # Sobran 100 al mes sin metas: 100.000 no se juntan en 60 meses.
    result = await _check("100000", goals=[], variable="2200")

    assert (result.verdict, result.estimated_on, result.projection) == ("not_yet", None, [])
