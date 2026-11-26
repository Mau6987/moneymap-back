"""Errores de los avisos (spec 006)."""

from app.core.errors import ApiError


class UnknownNotificationType(ApiError):
    """RF-12: el tipo de aviso no existe, o es de seguridad o de cobro y no se puede apagar."""

    status_code = 422
    code = "validation_error"

    def __init__(self, type_key: str) -> None:
        super().__init__(f"El aviso «{type_key}» no existe o no se puede cambiar")
