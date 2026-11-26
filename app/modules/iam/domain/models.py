"""Modelos del módulo de identidad.

Los read models y los datos que viajan entre las capas. Los comandos no cargan
agregados: `iam.users` no tiene RLS a propósito (el login ocurre antes de
conocer al usuario) y las reglas del registro las aplica la base.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

# Los proveedores de identidad que atiende la API (spec 001, RF-6).
Provider = Literal["google", "apple"]


@dataclass(frozen=True, slots=True)
class Registration:
    """Lo que la persona escribe en "Tus datos" (RF-1). El correo sale de la verificación."""

    verification_id: UUID
    first_name: str
    last_name: str
    terms_version: str


@dataclass(frozen=True, slots=True)
class NewUser:
    """Un registro ya validado en la forma (RF-1). La contraseña va aparte."""

    email: str
    first_name: str
    last_name: str
    terms_version: str
    # Cuándo verificó el correo con el link (RF-22): el registro lo exige.
    email_verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserProfile:
    """El perfil como quedó guardado (RF-9)."""

    id: UUID
    email: str
    first_name: str
    last_name: str
    display_name: str
    avatar_object_key: str | None
    country_code: str | None
    city: str | None
    occupation: str | None
    locale: str
    timezone: str
    # MM-189: el único administrador ve el panel de planes con el mismo login.
    is_admin: bool = False


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    """Lo que se corrige del perfil (RF-10). `sent` dice qué campos llegaron.

    Un campo que llegó en None borra el dato (o, en `display_name`, vuelve al
    nombre); uno que no llegó queda como estaba.
    """

    sent: frozenset[str]
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    country_code: str | None = None
    city: str | None = None
    occupation: str | None = None
    locale: str | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class Preferences:
    """Tema, color de acento, modo privado e inicio de semana (RF-15)."""

    theme: str
    accent_color: str | None
    hide_amounts: bool
    week_starts_on: int


@dataclass(frozen=True, slots=True)
class PreferencesChanges:
    """Lo que se cambia de las preferencias (RF-15). `accent_color` en None vuelve al de la marca."""

    sent: frozenset[str]
    theme: str | None = None
    accent_color: str | None = None
    hide_amounts: bool | None = None
    week_starts_on: int | None = None


@dataclass(frozen=True, slots=True)
class PasswordIdentity:
    """Lo que hace falta para verificar una contraseña, y si el correo está verificado."""

    user_id: UUID
    password_hash: str
    # Vacío = la cuenta no confirmó el correo: el login no la deja entrar (MM-88).
    email_verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeletionProof:
    """Con qué demuestra la persona que es ella al borrar su cuenta (RF-28).

    O la contraseña, o un `id_token` recién pedido al proveedor con el que entra.
    """

    password: str | None = None
    provider: Provider | None = None
    id_token: str | None = None


@dataclass(frozen=True, slots=True)
class NewSession:
    """Una sesión por abrir: del token solo se guarda su hash."""

    user_id: UUID
    refresh_token_hash: str
    expires_at: datetime
    device_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Una sesión de la base, para decidir si se rota o se corta la cadena."""

    id: UUID
    user_id: UUID
    device_id: UUID | None
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Lo que recibe la app en cada inicio de sesión (RF-1, RF-17)."""

    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class NewPassword:
    """Lo que la persona manda para poner una contraseña nueva (spec 008, RF-5)."""

    email: str
    code: str
    new_password: str


@dataclass(frozen=True, slots=True)
class SocialRegistration:
    """Lo que la app manda para terminar el registro social (RF-8).

    El correo solo hace falta si el proveedor no lo dio (RF-8).
    """

    first_name: str
    last_name: str
    terms_version: str
    email: str | None = None


@dataclass(frozen=True, slots=True)
class SocialIdentity:
    """Quién dice el proveedor que es (RF-6). El nombre puede faltar (RF-7)."""

    provider: str
    subject: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True, slots=True)
class SignedIn:
    """Entró con el proveedor: sus tokens (RF-6)."""

    tokens: TokenPair


@dataclass(frozen=True, slots=True)
class RegistrationRequired:
    """El correo no tiene cuenta: la app pide los datos que falten y completa (RF-7)."""

    identity: SocialIdentity
    registration_token: str


# O entró, o hay que completar el registro. No es un error: los dos son un 200.
SocialSignIn = SignedIn | RegistrationRequired


@dataclass(frozen=True, slots=True)
class AuthResult:
    """El registro devuelve además el perfil (RF-1)."""

    profile: UserProfile
    tokens: TokenPair


class VerificationStatus(StrEnum):
    """Lo que la app muestra mientras espera el link (RF-23)."""

    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class EmailVerification:
    """Un correo que se está verificando, todavía sin cuenta (RF-22)."""

    id: UUID
    email: str
    expires_at: datetime
    last_sent_at: datetime
    verified_at: datetime | None
    used_at: datetime | None

    def status(self, now: datetime, verified_ttl: timedelta) -> VerificationStatus:
        """Vencido si el link no se abrió a tiempo o si el correo verificado no se usó a tiempo."""
        if self.verified_at is not None:
            if now - self.verified_at > verified_ttl:
                return VerificationStatus.EXPIRED
            return VerificationStatus.VERIFIED
        if now >= self.expires_at:
            return VerificationStatus.EXPIRED
        return VerificationStatus.PENDING

    def resend_available_at(self, cooldown: timedelta) -> datetime:
        return self.last_sent_at + cooldown


@dataclass(frozen=True, slots=True)
class VerificationState:
    """Lo que la app recibe de una verificación (RF-22, RF-23, RF-25)."""

    id: UUID
    email: str
    status: VerificationStatus
    expires_at: datetime
    resend_available_at: datetime
