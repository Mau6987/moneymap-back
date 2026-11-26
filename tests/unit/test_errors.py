from fastapi.exceptions import RequestValidationError

from app.core.errors import problem_from_db_error, problem_from_validation_error


def test_plan_limit_es_409_con_la_funcionalidad() -> None:
    status, body = problem_from_db_error(
        "MM001", "plan_limit:finance.cards", "Tu plan permite 1 tarjeta(s) y ya tienes 1"
    )
    assert status == 409
    assert body["code"] == "plan_limit"
    assert body["feature"] == "finance.cards"
    assert body["detail"].startswith("Tu plan permite")


def test_hints_de_la_base_se_traducen_a_su_estado() -> None:
    assert problem_from_db_error("23514", "currency_mismatch", "x")[0] == 422  # type: ignore[index]
    assert problem_from_db_error("23514", "account_currency_locked", "x")[0] == 409  # type: ignore[index]


def test_error_desconocido_no_se_traduce() -> None:
    assert problem_from_db_error("23505", None, "duplicate key") is None


def test_las_restricciones_sin_hint_tienen_su_code() -> None:
    repeated = problem_from_db_error("23505", None, "duplicate key", "users_email_uq")
    assert (repeated[0], repeated[1]["code"]) == (409, "email_taken")  # type: ignore[index]
    assert repeated is not None and "cuenta" in repeated[1]["detail"]


def test_los_errores_de_un_movimiento_tienen_su_code() -> None:
    amount = problem_from_db_error("23514", None, "check violation", "transactions_amount_check")
    assert (amount[0], amount[1]["code"]) == (422, "invalid_amount")  # type: ignore[index]

    category = problem_from_db_error("23503", None, "foreign key", "transactions_category_fk")
    assert (category[0], category[1]["code"]) == (422, "validation_error")  # type: ignore[index]


def test_una_cuenta_que_no_existe_es_404_y_no_403() -> None:
    """El trigger de movimientos levanta 23503 sin nombre de restricción."""
    problem = problem_from_db_error("23503", None, "La cuenta 0000 no existe para este usuario")
    assert (problem[0], problem[1]["code"]) == (404, "not_found")  # type: ignore[index]


def test_el_422_del_contrato_lleva_el_campo_y_el_code() -> None:
    exc = RequestValidationError(
        [{"type": "value_error", "loc": ("body", "currency"), "msg": "no es válido", "input": "bob"}]
    )
    problem = problem_from_validation_error(exc)
    assert problem["status"] == 422
    assert problem["code"] == "validation_error"
    assert problem["errors"] == [{"field": "currency", "message": "no es válido"}]
    assert "currency" in problem["detail"]


def test_un_gasto_fijo_sin_cuenta_ni_moneda_es_422() -> None:
    assert problem_from_db_error("23514", "validation_error", "x")[0] == 422  # type: ignore[index]
