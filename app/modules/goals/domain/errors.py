"""Errores del dominio de metas: `code` estable en inglés y `detail` en español."""

from app.core.errors import ApiError


class NonPositiveContribution(ApiError):
    """RF-8: un retiro va por su propio endpoint, con monto positivo."""

    status_code = 422
    code = "invalid_amount"

    def __init__(self) -> None:
        super().__init__("El aporte tiene que ser mayor que cero")


class InvalidGoalMovementCursor(ApiError):
    """REQ-056: el cursor no es uno que haya dado la API (como el del historial)."""

    status_code = 422
    code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("El cursor no es válido: pide la lista desde el principio")


class InvalidGoalMovementRange(ApiError):
    """REQ-056: la lista pedida termina antes de empezar."""

    status_code = 422
    code = "validation_error"

    def __init__(self) -> None:
        super().__init__("La fecha final es anterior a la inicial")
