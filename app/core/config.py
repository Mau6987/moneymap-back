import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración desde variables de entorno (o .env en desarrollo)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "staging", "prod"] = "dev"
    # La API se conecta con un usuario que hereda de moneymap_app (sujeto a RLS)
    database_url: str = "postgresql+asyncpg://moneymap_api:moneymap@localhost:5436/moneymap"
    # Alembic usa el dueño de las tablas
    migrations_database_url: str = "postgresql+psycopg://moneymap:moneymap@localhost:5436/moneymap"
    # El worker de voz (spec 012): hereda de moneymap_worker para leer las rutas
    # de IA y escribir ai.calls. Solo lo usa ese trabajo, nunca la API.
    worker_database_url: str = "postgresql+asyncpg://moneymap_worker_login:moneymap@localhost:5436/moneymap"
    # La IA propia de docker-compose.ai.yml. En la laptop, el LLM es Ollama de escritorio.
    stt_base_url: str = "http://localhost:8090"
    llm_base_url: str = "http://localhost:11434"
    # Capas del LLM en la GPU. Sin valor decide Ollama, que en una GPU de 4 GB deja
    # dos tercios en la CPU y escribe 5 veces más lento; 99 las pone todas.
    llm_num_gpu: int | None = None
    # Donde la API deja el audio de cada dictado hasta que el worker lo lee y lo
    # borra. En docker-compose.yml es un tmpfs compartido; con uv, la carpeta temporal.
    voice_audio_dir: str = str(Path(tempfile.gettempdir()) / "moneymap-voice")
    redis_url: str = "redis://localhost:6379/0"
    # Firma los tokens de acceso. Se exige: sin él la API no arranca, en lugar de
    # firmar con un secreto por defecto que estaría en el repositorio
    # (constitución §5). En dev vive en .env; en staging y producción, en las variables de Dokploy.
    jwt_secret: SecretStr = Field(min_length=32)
    # El código del restablecimiento de la contraseña (spec 008).
    password_reset_code_ttl_minutes: int = 30
    # Valores propuestos en la spec 001; se cambian sin desplegar código.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Verificación del correo (spec 001, RF-22 a RF-26): el link vence a los
    # 5 minutos, se reenvía después de 1 y el correo verificado sirve 30 minutos
    # para terminar el registro.
    email_verification_ttl_minutes: int = 5
    email_verification_resend_seconds: int = 60
    verified_email_ttl_minutes: int = 30
    # La dirección pública de la API: la base del link que llega por correo.
    # En el emulador de Android la API local es http://10.0.2.2:8000.
    public_base_url: str = "http://localhost:8000"
    # Quién envía los correos. "log" los escribe en el log de la API y solo
    # sirve en dev: fuera de dev la API no arranca con él. "smtp" los manda de
    # verdad (Gmail, el correo de la empresa o un servicio). Ver docs/credenciales.md.
    email_backend: Literal["log", "smtp"] = "log"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    # El remitente que ve quien recibe. En Gmail tiene que ser la misma cuenta.
    email_from: str | None = None
    # El ingreso con Google (spec 001, RF-6): el Client ID de tipo Web. La API lo
    # usa para comprobar que el token es para esta app. Ver docs/credenciales.md.
    google_client_id: str | None = None
    # El ingreso con Apple (spec 001, RF-6): las audiencias que acepta la API,
    # separadas por coma. El bundle ID de la app iOS y, si existe, el Service ID
    # de la web. Ver docs/credenciales.md.
    apple_client_ids: str | None = None
    # Las fotos de los comprobantes (spec 014): el S3 propio del docker-compose (SeaweedFS), solo en
    # la red interna. La API sube y sirve cada foto; el S3 nunca sale a internet.
    receipts_endpoint: str = "localhost:9000"
    receipts_access_key: str = "moneymap"
    receipts_secret_key: SecretStr = SecretStr("moneymap-dev")
    receipts_bucket: str = "receipts"

    @property
    def apple_client_id_list(self) -> list[str]:
        """Las audiencias de Apple configuradas, sin vacíos ni espacios."""
        return [part.strip() for part in (self.apple_client_ids or "").split(",") if part.strip()]

    @model_validator(mode="after")
    def _email_backend_needs_its_settings(self) -> "Settings":
        if self.email_backend == "log" and self.environment != "dev":
            raise ValueError("EMAIL_BACKEND=log solo vale en dev: configurá un proveedor de correo")
        if self.email_backend == "smtp" and (self.smtp_host is None or self.email_from is None):
            raise ValueError("EMAIL_BACKEND=smtp necesita SMTP_HOST y EMAIL_FROM")
        if self.google_client_id is None and self.environment != "dev":
            raise ValueError("Sin GOOGLE_CLIENT_ID no se puede ingresar con Google")
        if self.receipts_secret_key.get_secret_value() == "moneymap-dev" and self.environment != "dev":
            raise ValueError("Fuera de dev hace falta RECEIPTS_SECRET_KEY propia (la clave del S3)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
