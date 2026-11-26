"""Errores en application/problem+json (RFC 9457).

La base de datos aplica las reglas del dinero y avisa con SQLSTATE y HINT
(ver db/README.md). Aquí solo se traducen a una respuesta HTTP con un `code`
estable en inglés y el `detail` en español. Tres caminos:

1. Un error de la base con HINT, o con `SQLSTATE MM001` (límite del plan).
2. Un error de la base sin HINT pero con una restricción conocida
   (`CONSTRAINT_PROBLEMS`): el `code` del contrato, con nuestro propio detalle.
3. Un error del dominio (`ApiError`), que ya trae su `code` y su `detail`.

Los errores de forma del esquema (un código de moneda mal escrito, un monto que
no es texto) salen como 422 `validation_error` con el campo que falló.
"""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

# HINT de la base → estado HTTP
HINT_STATUS: dict[str, int] = {
    "currency_unavailable": 422,
    "currency_mismatch": 422,
    "transfer_currency_mismatch": 422,
    "invalid_transfer_target": 422,
    "invalid_amount": 422,
    "terms_outdated": 422,
    "account_currency_locked": 409,
    "currency_in_use": 409,
    "category_in_use": 409,
    "plan_managed_by_store": 409,
    "admin_required": 403,
    "free_plan_required": 409,
    "invalid_limit": 422,
    "goal_insufficient": 422,
    "account_required": 422,
    "validation_error": 422,
    "goal_name_taken": 409,
    "goal_has_saved": 409,
    "account_insufficient": 422,
    # BUG-049: un aporte no pasa lo que falta ni va a una meta cumplida o archivada.
    "contribution_exceeds_remaining": 422,
    "goal_closed": 422,
    # BUG-012: el mismo gasto o ingreso fijo (nombre, monto, frecuencia y moneda).
    "recurring_duplicate": 409,
}

# Restricciones sin HINT, por nombre: estado, `code` y detalle en español.
# Las reglas siguen en la base (constitución §3); aquí solo se les pone nombre.
# Los nombres son los del padre aunque la tabla esté particionada (comprobado).
CONSTRAINT_PROBLEMS: dict[str, tuple[int, str, str]] = {
    "users_email_uq": (409, "email_taken", "Ese correo ya tiene una cuenta"),
    "users_country_code_fkey": (422, "validation_error", "El país no está en el catálogo"),
    "transactions_amount_check": (422, "invalid_amount", "El monto tiene que ser mayor que cero"),
    "accounts_name_uq": (409, "account_name_taken", "Ya tenés una cuenta con ese nombre"),
    "cards_institution_code_fkey": (422, "validation_error", "El banco no está en el catálogo de instituciones"),
    "user_settings_planned_savings_check": (422, "invalid_amount", "El ahorro planificado no puede ser negativo"),
    "goals_target_amount_check": (422, "invalid_amount", "El objetivo tiene que ser mayor que cero"),
    "user_settings_period_start_chk": (
        422,
        "validation_error",
        "El día de inicio no sirve para ese periodo: semanal de 0 a 6, quincenal de 1 a 13, mensual de 1 a 28",
    ),
    "categories_name_uq": (409, "category_name_taken", "Ya tenés una categoría de ese tipo con ese nombre"),
    "categories_flow_chk": (
        422,
        "validation_error",
        "Un gasto necesita su grupo del Money Flow (money_flow_group) y un ingreso no lleva",
    ),
    "budgets_active_uq": (409, "budget_exists", "Ya tenés un presupuesto para esa categoría en esa moneda"),
    "budgets_amount_check": (422, "invalid_amount", "El presupuesto tiene que ser mayor que cero"),
    "budgets_category_fk": (422, "validation_error", "Un presupuesto va en una categoría de gasto"),
    "transactions_category_fk": (
        422,
        "validation_error",
        "La categoría no existe o no es del tipo del movimiento: un gasto va en una de gasto",
    ),
}


def _title(code: str) -> str:
    return code.replace("_", " ").capitalize()


def _problem(status: int, code: str, detail: str) -> dict[str, Any]:
    return {"type": "about:blank", "title": _title(code), "status": status, "code": code, "detail": detail}


def problem_from_db_error(
    sqlstate: str | None,
    hint: str | None,
    message: str,
    constraint: str | None = None,
) -> tuple[int, dict[str, Any]] | None:
    """Traduce un error de PostgreSQL. None si no es un error de negocio conocido."""
    if sqlstate == "MM001":  # límite del plan: HINT plan_limit:<funcionalidad>
        feature = (hint or "").removeprefix("plan_limit:")
        return 409, {
            "type": "about:blank",
            "title": "Plan limit",
            "status": 409,
            "code": "plan_limit",
            "feature": feature,
            "detail": message,
        }
    if constraint is not None and constraint in CONSTRAINT_PROBLEMS:
        status, code, detail = CONSTRAINT_PROBLEMS[constraint]
        return status, _problem(status, code, detail)
    # El trigger de finance.transactions levanta foreign_key_violation sin nombre
    # de restricción cuando la cuenta no existe o no es del usuario. La spec pide
    # 404 y nunca 403: un 403 revelaría que la cuenta de otro existe.
    if sqlstate == "23503" and constraint is None and hint is None:
        return 404, _problem(404, "not_found", message)
    if hint in HINT_STATUS:
        status = HINT_STATUS[hint]
        return status, _problem(status, hint, message)
    return None


def problem_from_validation_error(exc: RequestValidationError) -> dict[str, Any]:
    """El 422 del contrato: problem+json con `validation_error` y los campos."""
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part != "body"),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    fields = ", ".join(f"«{error['field']}»" for error in errors if error["field"])
    return {
        "type": "about:blank",
        "title": "Validation error",
        "status": 422,
        "code": "validation_error",
        "detail": f"Revisá los campos enviados: {fields}" if fields else "Revisá los datos enviados",
        "errors": errors,
    }


class ApiError(Exception):
    """Un error del dominio: `code` estable en inglés y `detail` en español."""

    status_code: int = 422
    code: str = "domain_error"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or _title(self.code)
        super().__init__(self.detail)

    def to_problem(self) -> dict[str, Any]:
        return _problem(self.status_code, self.code, self.detail)


class Unauthorized(ApiError):
    """Sin token, con un token vencido o con uno que no sirve."""

    status_code = 401
    code = "unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}


class NotFound(ApiError):
    """El recurso no existe o es de otro usuario.

    404 y nunca 403: un 403 revelaría que existe (spec 002, seguridad).
    """

    status_code = 404
    code = "not_found"


class PlanLimitReached(ApiError):
    """Lo que el plan ya no permite (MM-186): 409 `plan_limit` con la funcionalidad.

    Igual que el `SQLSTATE MM001` de la base, para los límites que se miden en
    Python (Mis monedas, consultas de Can I Afford It?).
    """

    status_code = 409
    code = "plan_limit"

    def __init__(self, feature: str, detail: str) -> None:
        super().__init__(detail)
        self.feature = feature

    def to_problem(self) -> dict[str, Any]:
        return {**super().to_problem(), "feature": self.feature}


class TooManyRequests(ApiError):
    """Se pasó del límite de intentos; el cliente puede reintentar después."""

    status_code = 429
    code = "too_many_requests"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Demasiados intentos. Probá de nuevo en {retry_after_seconds} segundos")
        self.headers = {"Retry-After": str(retry_after_seconds)}


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        exc.to_problem(),
        status_code=exc.status_code,
        media_type="application/problem+json",
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        problem_from_validation_error(exc),
        status_code=422,
        media_type="application/problem+json",
    )


async def db_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    cause = exc.orig.__cause__ if exc.orig is not None else None  # excepción original de asyncpg
    sqlstate = getattr(cause, "sqlstate", None)
    hint = getattr(cause, "hint", None)
    constraint = getattr(cause, "constraint_name", None)
    message = getattr(cause, "message", None) or str(exc.orig)
    problem = problem_from_db_error(sqlstate, hint, message, constraint)
    if problem is None:
        raise exc  # error inesperado: 500 y Sentry
    status, body = problem
    return JSONResponse(body, status_code=status, media_type="application/problem+json")
