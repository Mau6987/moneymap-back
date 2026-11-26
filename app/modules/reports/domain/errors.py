"""Errores de los reportes (spec 004)."""

from app.core.errors import ApiError


class PeriodConflict(ApiError):
    """RF-17: se pide un mes (`period`) o el periodo que contiene un día (`on`), no los dos."""

    status_code = 422
    code = "validation_error"

    def __init__(self) -> None:
        super().__init__("Mandá `period` o `on`, no los dos")
