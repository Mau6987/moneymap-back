"""Esquemas HTTP del módulo de identidad: Pydantic, nada más.

El esquema valida la forma de lo que entra. Los términos, el correo repetido y
la moneda los aplica la base (constitución §3).
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.core.security import RESET_CODE_DIGITS
from app.core.validation import Email, Name
from app.modules.iam.domain.models import (
    AuthResult,
    DeletionProof,
    NewPassword,
    Preferences,
    PreferencesChanges,
    ProfileChanges,
    Provider,
    Registration,
    RegistrationRequired,
    SocialRegistration,
    TokenPair,
    UserProfile,
    VerificationState,
    VerificationStatus,
)

# El máximo lo pone la base; el mínimo es una decisión de seguridad a confirmar.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
TERMS_VERSION_MAX_LENGTH = 20


class EmailVerificationRequest(BaseModel):
    """RF-22: el correo que se quiere verificar."""

    email: Email


class EmailVerificationRead(BaseModel):
    """RF-22, RF-23 y RF-25: cómo va la verificación y cuándo se puede reenviar."""

    id: UUID
    email: str
    status: VerificationStatus
    expires_at: datetime
    resend_available_at: datetime

    @classmethod
    def from_state(cls, state: VerificationState) -> "EmailVerificationRead":
        return cls(
            id=state.id,
            email=state.email,
            status=state.status,
            expires_at=state.expires_at,
            resend_available_at=state.resend_available_at,
        )


class RegisterRequest(BaseModel):
    """RF-1 y RF-26: la verificación del correo, contraseña, nombre, apellido, fecha de nacimiento y términos."""

    verification_id: UUID
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    first_name: Name
    last_name: Name
    terms_version: str = Field(min_length=1, max_length=TERMS_VERSION_MAX_LENGTH, examples=["2026-10"])

    def to_registration(self) -> Registration:
        """Pasa al modelo del dominio: el caso de uso no depende de Pydantic."""
        return Registration(
            verification_id=self.verification_id,
            first_name=self.first_name,
            last_name=self.last_name,
            terms_version=self.terms_version,
        )


class ProviderSignInRequest(BaseModel):
    """RF-6 y RF-7: el token de identidad que saca la app del proveedor."""

    id_token: str = Field(min_length=1)


class SignedInRead(BaseModel):
    """RF-6: entró con el proveedor. Los mismos campos que el login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — el tipo del token, no un secreto
    expires_in: int

    @classmethod
    def from_record(cls, tokens: TokenPair) -> "SignedInRead":
        return cls(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )


class RegistrationRequiredRead(BaseModel):
    """RF-7: el correo no tiene cuenta todavía.

    El nombre y el correo pueden venir vacíos si el proveedor no los dio: la app
    los pide y completa el registro (RF-8).
    """

    registration_required: bool = True
    registration_token: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    @classmethod
    def from_record(cls, outcome: RegistrationRequired) -> "RegistrationRequiredRead":
        return cls(
            registration_token=outcome.registration_token,
            email=outcome.identity.email or None,
            first_name=outcome.identity.first_name,
            last_name=outcome.identity.last_name,
        )


class CompleteRegistrationRequest(BaseModel):
    """RF-8: los datos que faltan para crear la cuenta.

    `email` solo hace falta si el proveedor no lo dio.
    """

    registration_token: str = Field(min_length=1)
    first_name: Name
    last_name: Name
    terms_version: str = Field(min_length=1, max_length=TERMS_VERSION_MAX_LENGTH, examples=["2026-10"])
    email: Email | None = None

    def to_registration(self) -> SocialRegistration:
        return SocialRegistration(
            first_name=self.first_name,
            last_name=self.last_name,
            terms_version=self.terms_version,
            email=self.email,
        )


class PasswordResetRequest(BaseModel):
    """RF-1: el correo de la cuenta. La respuesta es la misma exista o no."""

    email: Email


# Los seis dígitos que llegan por correo, iguales en verify y confirm.
ResetCode = Annotated[
    str,
    Field(
        min_length=RESET_CODE_DIGITS,
        max_length=RESET_CODE_DIGITS,
        pattern=rf"^[0-9]{{{RESET_CODE_DIGITS}}}$",
        examples=["123456"],
    ),
]


class PasswordResetVerify(BaseModel):
    """RF-15: el código que llegó por correo, antes de pedir la contraseña nueva."""

    email: Email
    code: ResetCode


class PasswordResetConfirm(BaseModel):
    """RF-5: el código que llegó por correo y la contraseña nueva."""

    email: Email
    code: ResetCode
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    def to_new_password(self) -> NewPassword:
        return NewPassword(email=self.email, code=self.code, new_password=self.new_password)


class LoginRequest(BaseModel):
    """RF-20: las mismas credenciales con las que se registró."""

    email: Email
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(BaseModel):
    """RF-17: el refresh token que devolvió el registro, el login o el refresh anterior."""

    refresh_token: str = Field(min_length=1)


def _check_timezone(value: str) -> str:
    """Una zona IANA (`America/La_Paz`): con ella se calculan los días y los periodos."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("No es una zona horaria: usá una como America/La_Paz") from exc
    return value


_REQUIRED_PROFILE_FIELDS = ("first_name", "last_name", "locale", "timezone")
Occupation = Literal["student", "employee", "self_employed", "entrepreneur", "unemployed", "retired", "other"]


class ProfileUpdate(BaseModel):
    """RF-10 a RF-12: se corrige solo lo que se envía.

    `country_code`, `city` y `occupation` se borran enviándolos en null.
    `display_name` vacío o null vuelve a ser el nombre. El país se guarda en
    mayúsculas.
    """

    first_name: Name | None = Field(default=None, examples=["Ana"])
    last_name: Name | None = Field(default=None, examples=["Quispe"])
    display_name: str | None = Field(default=None, max_length=120, examples=["Anita"])
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$", examples=["BO"])
    city: str | None = Field(default=None, max_length=80, examples=["La Paz"])
    occupation: Occupation | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$", examples=["es-BO"])
    timezone: Annotated[str, AfterValidator(_check_timezone)] | None = Field(default=None, examples=["America/La_Paz"])

    @model_validator(mode="after")
    def _required_stay_set(self) -> "ProfileUpdate":
        cleared = [
            field
            for field in _REQUIRED_PROFILE_FIELDS
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if cleared:
            raise ValueError(f"No se pueden borrar: {', '.join(cleared)}")
        return self

    def to_changes(self) -> ProfileChanges:
        return ProfileChanges(
            sent=frozenset(self.model_fields_set),
            first_name=self.first_name,
            last_name=self.last_name,
            display_name=self.display_name,
            country_code=self.country_code,
            city=self.city,
            occupation=self.occupation,
            locale=self.locale,
            timezone=self.timezone,
        )


class UserProfileRead(BaseModel):
    """RF-9: el perfil completo."""

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
    is_admin: bool = Field(default=False, description="MM-189: el administrador del panel de planes")

    @classmethod
    def from_record(cls, profile: UserProfile) -> "UserProfileRead":
        return cls(
            id=profile.id,
            email=profile.email,
            first_name=profile.first_name,
            last_name=profile.last_name,
            display_name=profile.display_name,
            avatar_object_key=profile.avatar_object_key,
            country_code=profile.country_code,
            city=profile.city,
            occupation=profile.occupation,
            locale=profile.locale,
            timezone=profile.timezone,
            is_admin=profile.is_admin,
        )


class TokenPairRead(BaseModel):
    """Un token de acceso corto y el refresh con el que se pide el siguiente."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — es el tipo del token (RFC 6749), no un secreto
    expires_in: int

    @classmethod
    def from_record(cls, tokens: TokenPair) -> "TokenPairRead":
        return cls(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )


class AuthRead(TokenPairRead):
    """RF-1: el registro devuelve además el perfil, para no pedirlo enseguida."""

    profile: UserProfileRead

    @classmethod
    def from_result(cls, result: AuthResult) -> "AuthRead":
        return cls(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            expires_in=result.tokens.expires_in,
            profile=UserProfileRead.from_record(result.profile),
        )


class AccountDeletionRequest(BaseModel):
    """RF-28: la contraseña, o el proveedor y un `id_token` recién pedido."""

    password: str | None = Field(default=None, min_length=1, max_length=128)
    provider: Provider | None = None
    id_token: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_proof(self) -> "AccountDeletionRequest":
        with_provider = self.provider is not None or self.id_token is not None
        if (self.password is not None) == with_provider:
            raise ValueError("Mandá la contraseña, o el proveedor y su id_token")
        if with_provider and (self.provider is None or self.id_token is None):
            raise ValueError("Con un proveedor van `provider` e `id_token` juntos")
        return self

    def to_proof(self) -> DeletionProof:
        return DeletionProof(password=self.password, provider=self.provider, id_token=self.id_token)


class AccountDeletionRead(BaseModel):
    """RF-28: cuándo se borra la cuenta si la persona no vuelve a entrar."""

    deletion_scheduled_at: datetime


Theme = Literal["system", "light", "dark"]


class PreferencesRead(BaseModel):
    """RF-15. `accent_color` en null es el color de la marca; `week_starts_on`, 0 domingo a 6 sábado."""

    theme: Theme
    accent_color: str | None
    hide_amounts: bool
    week_starts_on: int

    @classmethod
    def from_record(cls, preferences: Preferences) -> "PreferencesRead":
        return cls.model_validate(
            {
                "theme": preferences.theme,
                "accent_color": preferences.accent_color,
                "hide_amounts": preferences.hide_amounts,
                "week_starts_on": preferences.week_starts_on,
            }
        )


class PreferencesUpdate(BaseModel):
    """RF-15 y RF-16: se cambia solo lo que se envía; lo que no sirve es 422 y no cambia nada.

    `accent_color` en null vuelve al color de la marca. Los demás no se borran.
    """

    theme: Theme | None = Field(default=None, examples=["dark"])
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#7C3AED"])
    hide_amounts: bool | None = None
    week_starts_on: int | None = Field(default=None, ge=0, le=6, examples=[1])

    @model_validator(mode="after")
    def _required_stay_set(self) -> "PreferencesUpdate":
        cleared = [
            field
            for field in ("theme", "hide_amounts", "week_starts_on")
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if cleared:
            raise ValueError(f"No se pueden borrar: {', '.join(cleared)}")
        return self

    def to_changes(self) -> PreferencesChanges:
        return PreferencesChanges(
            sent=frozenset(self.model_fields_set),
            theme=self.theme,
            accent_color=self.accent_color,
            hide_amounts=self.hide_amounts,
            week_starts_on=self.week_starts_on,
        )
