"""El correo de SMTP: el mensaje que se manda, sin servidor de por medio."""

from email.message import EmailMessage

from app.modules.iam.infrastructure.smtp_email_sender import build_verification_message


def test_el_correo_lleva_el_link_y_el_remitente() -> None:
    message = build_verification_message(
        "MoneyMap <no-responder@moneymap.app>",
        "ana@example.com",
        "http://localhost:8000/v1/auth/verify-email?token=abc123",
        5,
    )

    assert isinstance(message, EmailMessage)
    assert message["From"] == "MoneyMap <no-responder@moneymap.app>"
    assert message["To"] == "ana@example.com"
    assert message["Subject"] == "Verificá tu correo en MoneyMap"

    body = message.get_content()
    assert "http://localhost:8000/v1/auth/verify-email?token=abc123" in body
    assert "5 minutos" in body
    # El link es una credencial: el correo avisa que no lo comparta.
    assert "ignorá este correo" in body
