"""El adaptador de desarrollo: escribe el correo en el log en vez de mandarlo.

Existe para poder trabajar sin proveedor. El de verdad es `smtp_email_sender.py`;
los dos implementan `EmailSender`, así que los casos de uso no saben cuál corre.
"""

import logging

# El logger de uvicorn ya tiene handler a nivel INFO; uno propio no se vería
# sin configurar el logging de toda la API.
_log = logging.getLogger("uvicorn.error")


class LogEmailSender:
    """Solo dev: escribe el link en el log de la API en vez de enviarlo.

    Fuera de dev la API no arranca con este adaptador (`Settings`), porque el
    link es una credencial y no puede quedar en los logs (constitución §5).
    """

    async def send_verification_link(self, email: str, link: str, expires_in_minutes: int) -> None:
        _log.info("[correo de dev] Link para verificar %s (vence en %s min): %s", email, expires_in_minutes, link)

    async def send_password_reset_code(self, email: str, code: str, expires_in_minutes: int) -> None:
        _log.info("[correo de dev] Código para %s (vence en %s min): %s", email, expires_in_minutes, code)

    async def send_google_account_notice(self, email: str) -> None:
        _log.info("[correo de dev] Aviso para %s: esa cuenta entra con Google", email)
