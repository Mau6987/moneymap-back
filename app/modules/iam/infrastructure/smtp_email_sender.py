"""El correo de verdad, por SMTP (Gmail, el correo de la empresa o un servicio).

Lo elige `EMAIL_BACKEND=smtp`. `smtplib` es de la biblioteca estándar, así que no
agrega dependencias; bloquéa, así que se manda en un hilo para no frenar la
petición.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import Settings

# Si el servidor no contesta, la petición no puede quedarse colgada.
SMTP_TIMEOUT_SECONDS = 10

SUBJECT = "Verificá tu correo en MoneyMap"
RESET_SUBJECT = "Tu código para entrar a MoneyMap"
GOOGLE_NOTICE_SUBJECT = "Tu cuenta de MoneyMap entra con Google"


def build_verification_message(
    sender: str,
    recipient: str,
    link: str,
    expires_in_minutes: int,
) -> EmailMessage:
    """Arma el correo con el link. Se separa para poder probarlo sin servidor."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = SUBJECT
    message.set_content(
        "Entrá a este link para verificar tu correo y terminar de crear tu cuenta:\n"
        f"\n{link}\n\n"
        f"El link vence en {expires_in_minutes} minutos y sirve una sola vez.\n"
        "Si no fuiste vos, ignorá este correo.\n"
    )
    return message


def build_reset_code_message(
    sender: str,
    recipient: str,
    code: str,
    expires_in_minutes: int,
) -> EmailMessage:
    """El correo con el código del restablecimiento (spec 008, RF-2)."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = RESET_SUBJECT
    message.set_content(
        "Escribí este código en la app para poner una contraseña nueva:\n"
        f"\n    {code}\n\n"
        f"Vence en {expires_in_minutes} minutos y sirve una sola vez.\n"
        "Si no fuiste vos, ignorá este correo: tu contraseña sigue como estaba.\n"
    )
    return message


def build_google_notice_message(sender: str, recipient: str) -> EmailMessage:
    """El aviso de que esa cuenta entra con Google y no tiene contraseña (RF-10)."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = GOOGLE_NOTICE_SUBJECT
    message.set_content(
        "Pediste restablecer tu contraseña, pero esa cuenta de MoneyMap entra con Google:\n"
        "no tiene contraseña que restablecer.\n\n"
        "Entrá con el botón de Google.\n\n"
        "Si no fuiste vos, ignorá este correo.\n"
    )
    return message


class SmtpEmailSender:
    """Implementa `EmailSender` por SMTP.

    `SMTP_STARTTLS=true` usa el puerto 587 (STARTTLS) y `false` el 465 (TLS
    directo), que es lo que ofrecen Gmail y la mayoría de los proveedores.
    """

    def __init__(self, settings: Settings) -> None:
        if settings.smtp_host is None or settings.email_from is None:
            raise ValueError("EMAIL_BACKEND=smtp necesita SMTP_HOST y EMAIL_FROM")
        self._settings = settings
        self._host = settings.smtp_host
        self._sender = settings.email_from

    async def send_verification_link(self, email: str, link: str, expires_in_minutes: int) -> None:
        message = build_verification_message(self._sender, email, link, expires_in_minutes)
        await asyncio.to_thread(self._send, message)

    async def send_password_reset_code(self, email: str, code: str, expires_in_minutes: int) -> None:
        message = build_reset_code_message(self._sender, email, code, expires_in_minutes)
        await asyncio.to_thread(self._send, message)

    async def send_google_account_notice(self, email: str) -> None:
        message = build_google_notice_message(self._sender, email)
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        settings = self._settings
        if settings.smtp_starttls:
            with smtplib.SMTP(self._host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
                server.starttls()
                self._login(server)
                server.send_message(message)
            return
        with smtplib.SMTP_SSL(self._host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            self._login(server)
            server.send_message(message)

    def _login(self, server: smtplib.SMTP) -> None:
        settings = self._settings
        if settings.smtp_user is not None and settings.smtp_password is not None:
            server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
