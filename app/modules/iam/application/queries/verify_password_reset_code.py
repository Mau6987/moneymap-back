"""Caso de uso de lectura: si el código del restablecimiento sirve (spec 008, RF-15)."""

from app.modules.iam.application.password_reset import valid_code_owner
from app.modules.iam.domain.ports import PasswordResetRepository, UserRepository


async def verify_password_reset_code(
    email: str,
    code: str,
    users: UserRepository,
    resets: PasswordResetRepository,
) -> None:
    """Comprueba el código sin gastarlo: la app lo pregunta antes de pedir la
    contraseña nueva, y confirm lo vuelve a comprobar al cambiarla."""
    await valid_code_owner(email, code, users, resets)
