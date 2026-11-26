"""Caso de uso de escritura: poner la contraseña nueva con el código (spec 008)."""

from app.core import clock
from app.core.security import hash_password
from app.modules.iam.application.password_reset import valid_code_owner
from app.modules.iam.domain.models import NewPassword
from app.modules.iam.domain.ports import (
    PasswordResetRepository,
    SecurityAudit,
    SessionRepository,
    UserRepository,
)


async def confirm_password_reset(
    new_password: NewPassword,
    users: UserRepository,
    resets: PasswordResetRepository,
    sessions: SessionRepository,
    audit: SecurityAudit,
) -> None:
    """Cambia la contraseña, quema el código y cierra todas las sesiones (RF-5 a RF-8).

    Son cinco parámetros y no cuatro: las tres entradas van juntas en `NewPassword`
    para que se vea, y las cuatro dependencias son las que el flujo necesita (la
    cuenta, el código, las sesiones y la traza). La comprobación del código es la
    misma que usa `verify`, en `application/password_reset.py`.
    """
    user_id = await valid_code_owner(new_password.email, new_password.code, users, resets)
    now = clock.utc_now()

    await users.set_password(user_id, hash_password(new_password.new_password))
    await resets.mark_used(user_id, now)
    await sessions.revoke_all(user_id, now)
    await audit.password_reset(user_id)
