"""Cableado del módulo de identidad.

La aplicación no conoce la infraestructura; esto es el único lugar donde se
encuentran. El registro, el login y el refresh ocurren antes de saber quién es
la persona, así que usan la sesión pública.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import current_session, public_session
from app.modules.iam.application.commands.request_account_deletion import AccountDeletionServices
from app.modules.iam.domain.models import Provider
from app.modules.iam.domain.ports import (
    IdentityProvider,
    PasswordResetRepository,
    SecurityAudit,
    SessionRepository,
    UserRepository,
)
from app.modules.iam.infrastructure.apple_identity import APPLE_JWKS_URL, AppleIdentityProvider
from app.modules.iam.infrastructure.email_sender import LogEmailSender
from app.modules.iam.infrastructure.email_verification_repository import SqlEmailVerificationRepository
from app.modules.iam.infrastructure.google_identity import GOOGLE_JWKS_URL, GoogleIdentityProvider
from app.modules.iam.infrastructure.jwks import CachedKeySet
from app.modules.iam.infrastructure.password_reset_repository import SqlPasswordResetRepository
from app.modules.iam.infrastructure.preferences_repository import SqlPreferencesRepository
from app.modules.iam.infrastructure.security_audit import SqlSecurityAudit
from app.modules.iam.infrastructure.session_repository import SqlSessionRepository
from app.modules.iam.infrastructure.smtp_email_sender import SmtpEmailSender
from app.modules.iam.infrastructure.unit_of_work import SqlUnitOfWork
from app.modules.iam.infrastructure.user_repository import SqlUserRepository


@dataclass(frozen=True, slots=True)
class PasswordResetServices:
    """Las cuatro piezas del restablecimiento, juntas para no llenar de parámetros."""

    users: UserRepository
    resets: PasswordResetRepository
    sessions: SessionRepository
    audit: SecurityAudit


# Las claves públicas de cada proveedor se cachean una vez por proceso: cambian poco.
_google_key_set = CachedKeySet(GOOGLE_JWKS_URL)
_apple_key_set = CachedKeySet(APPLE_JWKS_URL)

PublicSession = Annotated[AsyncSession, Depends(public_session)]
UserSession = Annotated[AsyncSession, Depends(current_session)]


def get_user_repository(session: PublicSession) -> SqlUserRepository:
    """Para el registro y el login: `iam.users` no tiene RLS (el login va antes)."""
    return SqlUserRepository(session)


def get_current_user_repository(session: UserSession) -> SqlUserRepository:
    """Para lo que ya tiene usuario: la sesión trae `app.user_id`."""
    return SqlUserRepository(session)


def get_preferences_repository(session: UserSession) -> SqlPreferencesRepository:
    return SqlPreferencesRepository(session)


def get_session_repository(session: PublicSession) -> SqlSessionRepository:
    return SqlSessionRepository(session)


def get_security_audit(session: PublicSession) -> SqlSecurityAudit:
    return SqlSecurityAudit(session)


def get_unit_of_work(session: PublicSession) -> SqlUnitOfWork:
    return SqlUnitOfWork(session)


def get_password_reset_repository(session: PublicSession) -> SqlPasswordResetRepository:
    """El código del restablecimiento va antes de entrar: sesión pública."""
    return SqlPasswordResetRepository(session)


def get_password_reset_services(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    resets: Annotated[PasswordResetRepository, Depends(get_password_reset_repository)],
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
    audit: Annotated[SecurityAudit, Depends(get_security_audit)],
) -> PasswordResetServices:
    return PasswordResetServices(users=users, resets=resets, sessions=sessions, audit=audit)


def get_identity_provider(provider: Provider) -> IdentityProvider:
    """El proveedor de identidad que pide la ruta (Google o Apple)."""
    match provider:
        case "google":
            return GoogleIdentityProvider(get_settings().google_client_id or "", _google_key_set)
        case "apple":
            return AppleIdentityProvider(get_settings().apple_client_id_list, _apple_key_set)


def get_identity_providers() -> Callable[[Provider], IdentityProvider]:
    """Para cuando el proveedor viene en el cuerpo y no en la ruta (RF-28)."""
    return get_identity_provider


def get_account_deletion_services(
    session: UserSession,
    identities: Annotated[Callable[[Provider], IdentityProvider], Depends(get_identity_providers)],
) -> AccountDeletionServices:
    """Todo en la sesión del usuario: marcar la cuenta y cerrar sus sesiones van juntos o no van."""
    return AccountDeletionServices(
        users=SqlUserRepository(session),
        sessions=SqlSessionRepository(session),
        audit=SqlSecurityAudit(session),
        identities=identities,
    )


def get_email_verification_repository(session: PublicSession) -> SqlEmailVerificationRepository:
    """La verificación del correo va antes de que exista el usuario: sesión pública."""
    return SqlEmailVerificationRepository(session)


def get_email_sender() -> LogEmailSender | SmtpEmailSender:
    """El adaptador según `EMAIL_BACKEND` (ver docs/credenciales.md)."""
    settings = get_settings()
    match settings.email_backend:
        case "smtp":
            return SmtpEmailSender(settings)
        case "log":
            return LogEmailSender()
