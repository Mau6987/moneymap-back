"""Errores del dominio de finanzas: `code` estable en inglés y `detail` en español."""

from typing import Any

from app.core.errors import ApiError


class InvalidCursor(ApiError):
    """RF-26: el cursor del historial no es uno que haya dado la API."""

    status_code = 422
    code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("El cursor no es válido: pedí el historial desde la primera página")


class OnboardingIncomplete(ApiError):
    """Spec 007, RF-5: no se cierra el onboarding sin moneda principal ni cuentas."""

    status_code = 422
    code = "onboarding_incomplete"

    def __init__(self, missing_step: str) -> None:
        details = {
            "currency": "Elegí tu moneda principal antes de terminar",
            "accounts": "Agregá tu efectivo o tu tarjeta antes de terminar",
        }
        super().__init__(details[missing_step])
        self.missing_step = missing_step

    def to_problem(self) -> dict[str, Any]:
        return {**super().to_problem(), "missing_step": self.missing_step}


class CategoryTypeInUse(ApiError):
    """Spec 007, RF-11: una categoría con movimientos o recurrentes no cambia de tipo."""

    status_code = 409
    code = "category_type_in_use"

    def __init__(self) -> None:
        super().__init__("La categoría tiene movimientos o recurrentes: no puede pasar de ingreso a gasto ni al revés")


class InvalidDateRange(ApiError):
    """RF-32: el historial pedido termina antes de empezar."""

    status_code = 422
    code = "validation_error"

    def __init__(self) -> None:
        super().__init__("`from` no puede ser posterior a `to`")


class InvalidReceipt(ApiError):
    """Spec 014, RF-2: la foto no es JPEG, PNG ni WebP, está vacía o pasa de 5 MB."""

    status_code = 422
    code = "invalid_receipt"

    def __init__(self) -> None:
        super().__init__("Mandá la foto en JPEG, PNG o WebP, de hasta 5 MB")
