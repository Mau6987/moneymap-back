"""Caso de uso de escritura: pedir el código para restablecer la contraseña (spec 008)."""

from datetime import timedelta

from app.core import clock
from app.core.config import get_settings
from app.core.security import create_reset_code, hash_code
from app.modules.iam.domain.ports import EmailSender, PasswordResetRepository, UserRepository


async def request_password_reset(
    email: str,
    users: UserRepository,
    resets: PasswordResetRepository,
    sender: EmailSender,
) -> None:
    """Responde siempre lo mismo y solo manda el correo si corresponde (RF-1, RF-2).

    Si el correo no tiene cuenta no pasa nada; si la cuenta entra con Google se
    avisa (RF-10); si tiene contraseña se guarda un código nuevo y el anterior
    deja de servir (RF-4). Nada de eso se le cuenta a quien pregunta (RF-12).
    """
    # Una cuenta suspendida o a medio borrar se trata como si no existiera (RF-11).
    if await users.find_sign_in_id_by_email(email) is None:
        return
    identity = await users.find_password_identity(email)
    if identity is None:
        await sender.send_google_account_notice(email)
        return

    settings = get_settings()
    now = clock.utc_now()
    code = create_reset_code()
    await resets.replace_code(
        identity.user_id,
        hash_code(code),
        now + timedelta(minutes=settings.password_reset_code_ttl_minutes),
        now,
    )
    await sender.send_password_reset_code(email, code, settings.password_reset_code_ttl_minutes)
