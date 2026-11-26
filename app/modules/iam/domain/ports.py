"""Puertos del módulo de identidad.

`iam.users`, `iam.auth_identities` y `iam.sessions` no tienen RLS: el login
ocurre antes de conocer al usuario. La sesión que usan es la de
`core/dependencies.public_session`.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.iam.domain.models import (
    EmailVerification,
    NewSession,
    NewUser,
    PasswordIdentity,
    Preferences,
    PreferencesChanges,
    ProfileChanges,
    SessionRecord,
    SocialIdentity,
    UserProfile,
)


class UserRepository(Protocol):
    """Usuarios y sus métodos de acceso."""

    async def create(self, user: NewUser) -> UserProfile:
        """RF-1: crea el usuario. Las identidades van aparte."""
        ...

    async def append_password_identity(self, user_id: UUID, email: str, password_hash: str) -> None:
        """La identidad `password` del registro con correo y contraseña."""
        ...

    async def set_password(self, user_id: UUID, password_hash: str) -> None:
        """Cambia la contraseña de esa cuenta (spec 008, RF-5)."""
        ...

    async def link_identity(self, user_id: UUID, social: SocialIdentity) -> None:
        """Vincula una cuenta de Google a un usuario que ya existe (RF-6)."""
        ...

    async def find_id_by_email(self, email: str) -> UUID | None:
        """La cuenta con ese correo, si existe (incluye suspendidas: es para ver si el correo está tomado)."""
        ...

    async def find_sign_in_id_by_email(self, email: str) -> UUID | None:
        """La cuenta que puede entrar con ese correo: activa o con el borrado pendiente.

        Una suspendida no entra a ningún flujo; una con el borrado pendiente sí,
        porque entrar es lo que lo cancela (RF-30).
        """
        ...

    async def find_sign_in_id_by_identity(self, provider: str, subject: str) -> UUID | None:
        """A qué cuenta que puede entrar pertenece esa identidad del proveedor, si ya entró antes."""
        ...

    async def find_password_identity(self, email: str) -> PasswordIdentity | None:
        """La identidad con contraseña de ese correo, si existe y la cuenta puede entrar."""
        ...

    async def find_password_hash(self, user_id: UUID) -> str | None:
        """El hash de la contraseña de esa cuenta; None si entra solo con Google o Apple."""
        ...

    async def has_identity(self, user_id: UUID, provider: str, subject: str) -> bool:
        """Si esa identidad del proveedor es de esa cuenta (RF-28)."""
        ...

    async def schedule_deletion(self, user_id: UUID, now: datetime) -> None:
        """Pasa la cuenta a `pending_deletion` desde `now` (RF-28)."""
        ...

    async def cancel_deletion(self, user_id: UUID) -> None:
        """Vuelve a `active` si el borrado estaba pendiente (RF-30)."""
        ...

    async def get_profile(self, user_id: UUID) -> UserProfile | None: ...

    async def update_profile(self, user_id: UUID, changes: ProfileChanges) -> UserProfile | None:
        """RF-10: corrige lo enviado y devuelve el perfil como quedó guardado."""
        ...

    async def email_taken(self, email: str) -> bool:
        """Si ese correo ya tiene una cuenta viva (RF-22)."""
        ...


class EmailVerificationRepository(Protocol):
    """Los correos que se verifican antes de crear la cuenta (RF-22 a RF-26)."""

    async def create(self, email: str, token_hash: str, expires_at: datetime, now: datetime) -> EmailVerification: ...

    async def get(self, verification_id: UUID, *, for_update: bool = False) -> EmailVerification | None:
        """`for_update` bloquea la fila: dos registros con la misma verificación no pasan los dos."""
        ...

    async def find_by_token_hash(self, token_hash: str) -> EmailVerification | None: ...

    async def renew_token(
        self, verification_id: UUID, token_hash: str, expires_at: datetime, now: datetime
    ) -> EmailVerification:
        """RF-25: un link nuevo; el anterior deja de servir."""
        ...

    async def mark_verified(self, verification_id: UUID, now: datetime) -> None: ...

    async def mark_used(self, verification_id: UUID, now: datetime) -> None: ...


class EmailSender(Protocol):
    """Envía los correos de la identidad. El proveedor es un detalle de infraestructura."""

    async def send_verification_link(self, email: str, link: str, expires_in_minutes: int) -> None: ...

    async def send_password_reset_code(self, email: str, code: str, expires_in_minutes: int) -> None: ...

    async def send_google_account_notice(self, email: str) -> None:
        """Avisa que esa cuenta entra con Google y no tiene contraseña que restablecer (RF-10)."""
        ...


class SessionRepository(Protocol):
    """Sesiones y la rotación del refresh token (RF-17, RF-18)."""

    async def create(self, session: NewSession) -> UUID: ...

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None: ...

    async def unused_replacement(self, session_id: UUID, since: datetime) -> UUID | None:
        """La sesión que reemplazó a `session_id` si se rotó desde `since` y nadie la usó todavía."""
        ...

    async def rotate(self, previous_id: UUID, new_session: NewSession, now: datetime) -> UUID | None:
        """Revoca la sesión anterior y abre la nueva.

        Devuelve None si otro proceso ya la había rotado: el token se está
        reusando y quien llama tiene que cortar la cadena (RF-18).
        """
        ...

    async def revoke_chain(self, session_id: UUID, now: datetime) -> int:
        """Revoca esa sesión y todo lo que la reemplazó, o sea su cadena."""
        ...

    async def revoke_all(self, user_id: UUID, now: datetime) -> int:
        """Revoca todas las sesiones del usuario, en todos sus dispositivos (RF-8)."""
        ...


class PasswordResetRepository(Protocol):
    """Los códigos del restablecimiento, en `iam.verification_tokens` (RF-3, RF-4)."""

    async def replace_code(self, user_id: UUID, code_hash: str, expires_at: datetime, now: datetime) -> None:
        """Invalida el código anterior y guarda el nuevo: el último es el que vale."""
        ...

    async def latest_code_hash(self, user_id: UUID, now: datetime) -> str | None:
        """El código vigente de ese usuario, si hay."""
        ...

    async def mark_used(self, user_id: UUID, now: datetime) -> None:
        """Marca como usados los códigos vigentes de ese usuario."""
        ...


class IdentityProvider(Protocol):
    """Verifica el token de un proveedor de identidad y dice quién es (RF-6)."""

    async def verify(self, id_token: str) -> SocialIdentity: ...


class SecurityAudit(Protocol):
    """La traza de los eventos de seguridad, en `ops.log`."""

    async def refresh_token_reused(self, user_id: UUID, session_id: UUID) -> None: ...

    async def password_reset(self, user_id: UUID) -> None: ...

    async def account_deletion_requested(self, user_id: UUID) -> None: ...


class UnitOfWork(Protocol):
    """Confirma la transacción de la petición antes de tiempo.

    Hace falta cuando una escritura tiene que sobrevivir al error que viene
    después. El corte de seguridad de RF-18 es el caso: la petición termina en
    401, así que la dependencia de sesión nunca llega a confirmar y el corte se
    perdería.
    """

    async def commit(self) -> None: ...


class PreferencesRepository(Protocol):
    """Las preferencias del usuario (RF-15). La fila la crea un trigger al registrarse."""

    async def get(self, user_id: UUID) -> Preferences | None: ...

    async def update(self, user_id: UUID, changes: PreferencesChanges) -> Preferences | None: ...
