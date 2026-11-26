"""Errores de planning: `code` estable en inglés y `detail` en español."""

from app.core.errors import ApiError, NotFound


class ExpenseCategoryRequired(ApiError):
    """Caso límite de la spec 005: una compra va en una categoría de gasto."""

    status_code = 422
    code = "validation_error"

    def __init__(self) -> None:
        super().__init__("La categoría no existe o no es de gasto")


class AccountNotInCurrency(NotFound):
    """RF-21: la cuenta no existe, es de otro usuario, está borrada o es de otra moneda."""

    def __init__(self) -> None:
        super().__init__("La cuenta no existe o no es de esa moneda")
