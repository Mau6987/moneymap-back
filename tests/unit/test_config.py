"""La configuración que no puede llegar a producción, sin base de datos."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SECRET = "s" * 32


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_el_correo_de_dev_no_arranca_fuera_de_dev(environment: str) -> None:
    """El adaptador "log" escribe el link en el log: fuera de dev sería filtrar credenciales."""
    with pytest.raises(ValidationError, match="EMAIL_BACKEND=log"):
        Settings(_env_file=None, environment=environment, jwt_secret=SECRET, email_backend="log")  # type: ignore[arg-type]


def test_en_dev_el_correo_va_al_log() -> None:
    settings = Settings(_env_file=None, environment="dev", jwt_secret=SECRET)  # type: ignore[arg-type]

    assert settings.email_backend == "log"


def test_smtp_necesita_su_configuracion() -> None:
    """Sin host ni remitente, la API no arranca: fallaría al mandar el primer correo."""
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        Settings(_env_file=None, environment="staging", jwt_secret=SECRET, email_backend="smtp")  # type: ignore[arg-type]


def test_smtp_con_host_y_remitente_arranca() -> None:
    settings = Settings(
        _env_file=None,
        environment="staging",
        jwt_secret=SECRET,
        email_backend="smtp",
        smtp_host="smtp.example.com",
        email_from="no-responder@moneymap.app",
        google_client_id="1234-abc.apps.googleusercontent.com",
        receipts_secret_key=SECRET,
    )

    assert (settings.email_backend, settings.smtp_port, settings.smtp_starttls) == ("smtp", 587, True)


def test_sin_client_id_de_google_no_arranca_fuera_de_dev() -> None:
    """Sin el Client ID la API no puede comprobar que el token de Google sea para ella."""
    with pytest.raises(ValidationError, match="GOOGLE_CLIENT_ID"):
        Settings(
            _env_file=None,
            environment="prod",
            jwt_secret=SECRET,
            email_backend="smtp",
            smtp_host="smtp.example.com",
            email_from="no-responder@moneymap.app",
        )


def test_sin_clave_propia_del_s3_no_arranca_fuera_de_dev() -> None:
    """Spec 014: las fotos de los comprobantes no quedan con la clave de desarrollo."""
    with pytest.raises(ValidationError, match="RECEIPTS_SECRET_KEY"):
        Settings(
            _env_file=None,
            environment="prod",
            jwt_secret=SECRET,
            email_backend="smtp",
            smtp_host="smtp.example.com",
            email_from="no-responder@moneymap.app",
            google_client_id="1234-abc.apps.googleusercontent.com",
        )
