"""Identidad (spec 001): solo HTTP.

Valida con el esquema, llama al caso de uso y devuelve el esquema. Sin SQL y sin
reglas. Cubre la verificación del correo (RF-22 a RF-26), el registro (RF-1 a
RF-5), el inicio de sesión (RF-20), la rotación del refresh token (RF-17 y RF-18)
y el perfil (RF-9). El OAuth de Google y Apple, las preferencias y el avatar
llegan con sus requisitos.
"""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, Response

from app.core.dependencies import get_current_user_id
from app.core.rate_limit import enforce_rate_limit
from app.modules.iam.account_router import router as account_router
from app.modules.iam.application.commands.complete_social_registration import complete_social_registration
from app.modules.iam.application.commands.confirm_email import confirm_email
from app.modules.iam.application.commands.confirm_password_reset import confirm_password_reset
from app.modules.iam.application.commands.login import login
from app.modules.iam.application.commands.logout import logout
from app.modules.iam.application.commands.refresh_session import refresh_session
from app.modules.iam.application.commands.register import register
from app.modules.iam.application.commands.request_password_reset import request_password_reset
from app.modules.iam.application.commands.resend_email_verification import resend_email_verification
from app.modules.iam.application.commands.sign_in_with_provider import sign_in_with_provider
from app.modules.iam.application.commands.start_email_verification import start_email_verification
from app.modules.iam.application.commands.update_me import update_me
from app.modules.iam.application.queries.get_email_verification import get_email_verification
from app.modules.iam.application.queries.get_me import get_me
from app.modules.iam.application.queries.verify_password_reset_code import verify_password_reset_code
from app.modules.iam.deps import (
    PasswordResetServices,
    get_current_user_repository,
    get_email_sender,
    get_email_verification_repository,
    get_identity_provider,
    get_password_reset_repository,
    get_password_reset_services,
    get_security_audit,
    get_session_repository,
    get_unit_of_work,
    get_user_repository,
)
from app.modules.iam.domain.models import RegistrationRequired, SignedIn
from app.modules.iam.domain.ports import (
    EmailSender,
    EmailVerificationRepository,
    IdentityProvider,
    PasswordResetRepository,
    SecurityAudit,
    SessionRepository,
    UnitOfWork,
    UserRepository,
)
from app.modules.iam.schemas import (
    AuthRead,
    CompleteRegistrationRequest,
    EmailVerificationRead,
    EmailVerificationRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetVerify,
    ProfileUpdate,
    ProviderSignInRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationRequiredRead,
    SignedInRead,
    TokenPairRead,
    UserProfileRead,
)
from app.modules.iam.verify_page import render_verify_page

router = APIRouter(tags=["iam"])
router.include_router(account_router)

CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
Verifications = Annotated[EmailVerificationRepository, Depends(get_email_verification_repository)]
Sender = Annotated[EmailSender, Depends(get_email_sender)]

# Límite de intentos (spec 001, requisitos no funcionales). Por IP solo frena el
# abuso en masa, con margen: los registros de la web salen todos de la IP de su
# servidor y en el celular muchas personas comparten la IP de su operadora.
# ponytail: la web cuenta como una sola IP; si llega a estos límites, que mande la
# IP real en un encabezado firmado y se cuente por persona.
REGISTER_LIMIT = 100
REGISTER_WINDOW_SECONDS = 3600
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 60
# Cada link es un correo que sale: 5 por correo por hora y 100 por IP, contando
# los reenvíos.
EMAIL_VERIFICATION_LIMIT = 100
EMAIL_VERIFICATION_PER_EMAIL_LIMIT = 5
EMAIL_VERIFICATION_WINDOW_SECONDS = 3600
# Verificar tokens de proveedor es barato, pero no gratis: 120 por IP por minuto.
OAUTH_LIMIT = 120
OAUTH_WINDOW_SECONDS = 60
# Cada pedido de restablecimiento manda un correo: 5 por correo por hora.
PASSWORD_RESET_LIMIT = 5
PASSWORD_RESET_WINDOW_SECONDS = 3600
# Los intentos de código: 5 por correo cada 15 minutos (spec 008, RF-9).
PASSWORD_RESET_ATTEMPTS = 5
PASSWORD_RESET_ATTEMPTS_WINDOW_SECONDS = 900


async def enforce_register_limit(request: Request) -> None:
    """100 registros por IP por hora (el registro ya pide un correo verificado)."""
    await enforce_rate_limit(
        scope="register",
        identifier=_client_ip(request),
        limit=REGISTER_LIMIT,
        window_seconds=REGISTER_WINDOW_SECONDS,
    )


async def enforce_email_verification_limit(request: Request) -> None:
    """100 links por IP por hora, entre los nuevos y los reenvíos."""
    await enforce_rate_limit(
        scope="email_verification",
        identifier=_client_ip(request),
        limit=EMAIL_VERIFICATION_LIMIT,
        window_seconds=EMAIL_VERIFICATION_WINDOW_SECONDS,
    )


async def enforce_email_verification_email_limit(request: Request) -> None:
    """5 links por correo por hora: el que recibe los correos es esa persona."""
    email = await _json_field(request, "email")
    if email:
        await enforce_rate_limit(
            scope="email_verification_email",
            identifier=email,
            limit=EMAIL_VERIFICATION_PER_EMAIL_LIMIT,
            window_seconds=EMAIL_VERIFICATION_WINDOW_SECONDS,
        )


async def enforce_login_limit(request: Request) -> None:
    """10 inicios de sesión por minuto por correo."""
    await enforce_rate_limit(
        scope="login",
        identifier=await _json_field(request, "email") or _client_ip(request),
        limit=LOGIN_LIMIT,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )


def _client_ip(request: Request) -> str:
    """La IP de quien hace la petición, para contar sus intentos.

    Detrás del proxy (Traefik en Dokploy), `request.client.host` es el proxy: la
    misma para todas las personas, así que el límite se contaría en conjunto.
    El proxy agrega la IP real al final de `X-Forwarded-For` y las de más
    arriba las escribe el cliente, así que vale la última. Sin encabezado —local
    y pruebas— queda la del socket.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is not None:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client is not None else "desconocida"


async def _json_field(request: Request, field: str) -> str:
    """Lee un campo del cuerpo antes de que lo valide el esquema, sin romper nada.

    FastAPI guarda el cuerpo leído, así que el esquema lo sigue parseando igual.
    """
    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(body, dict):
        return ""
    value = body.get(field)
    return value.strip().lower() if isinstance(value, str) else ""


@router.post(
    "/auth/email-verifications",
    response_model=EmailVerificationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_email_verification_limit), Depends(enforce_email_verification_email_limit)],
    summary="Envía el link para verificar el correo",
)
async def start_email_verification_route(
    payload: EmailVerificationRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    verifications: Verifications,
    sender: Sender,
) -> EmailVerificationRead:
    """RF-22: el primer paso del registro. 409 `email_taken` si el correo ya tiene cuenta."""
    state = await start_email_verification(payload.email, users, verifications, sender)
    return EmailVerificationRead.from_state(state)


@router.get(
    "/auth/email-verifications/{verification_id}",
    response_model=EmailVerificationRead,
    summary="Cómo va la verificación del correo",
)
async def get_email_verification_route(
    verification_id: UUID,
    verifications: Verifications,
) -> EmailVerificationRead:
    """RF-23: `pending`, `verified` o `expired`. La app lo pide al tocar «Ya verifiqué»."""
    state = await get_email_verification(verification_id, verifications)
    return EmailVerificationRead.from_state(state)


@router.post(
    "/auth/email-verifications/{verification_id}/resend",
    response_model=EmailVerificationRead,
    dependencies=[Depends(enforce_email_verification_limit)],
    summary="Reenvía el link",
)
async def resend_email_verification_route(
    verification_id: UUID,
    verifications: Verifications,
    sender: Sender,
) -> EmailVerificationRead:
    """RF-25: un link nuevo que reemplaza al anterior; 429 si no pasó un minuto."""
    state = await resend_email_verification(verification_id, verifications, sender)
    return EmailVerificationRead.from_state(state)


@router.get(
    "/auth/verify-email",
    response_class=HTMLResponse,
    summary="El link del correo",
    description="Lo abre el navegador desde el correo, no la app: responde una página HTML.",
)
async def verify_email_route(
    verifications: Verifications,
    token: Annotated[str, Query(max_length=128)] = "",
) -> HTMLResponse:
    """RF-24: marca el correo como verificado y le dice a la persona que vuelva a la app."""
    outcome = await confirm_email(token, verifications)
    status_code, html = render_verify_page(outcome.status, outcome.email)
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.post(
    "/auth/register",
    response_model=AuthRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_register_limit)],
    summary="Registra a una persona nueva",
)
async def register_route(
    payload: RegisterRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
    verifications: Verifications,
) -> AuthRead:
    """RF-1, RF-3 a RF-5 y RF-26: el correo es el que se verificó; los términos y el
    correo repetido los aplica la base."""
    result = await register(payload.to_registration(), payload.password, users, sessions, verifications)
    return AuthRead.from_result(result)


@router.post(
    "/auth/login",
    response_model=TokenPairRead,
    dependencies=[Depends(enforce_login_limit)],
    summary="Inicia sesión",
)
async def login_route(
    payload: LoginRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
) -> TokenPairRead:
    """RF-20: correo y contraseña a cambio de un par de tokens."""
    tokens = await login(payload.email, payload.password, users, sessions)
    return TokenPairRead.from_record(tokens)


@router.post(
    "/auth/refresh",
    response_model=TokenPairRead,
    summary="Rota el refresh token",
)
async def refresh_route(
    payload: RefreshRequest,
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
    audit: Annotated[SecurityAudit, Depends(get_security_audit)],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> TokenPairRead:
    """RF-17 y RF-18: el token anterior queda revocado; si se reusa, se corta la cadena."""
    tokens = await refresh_session(payload.refresh_token, sessions, audit, unit_of_work)
    return TokenPairRead.from_record(tokens)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cierra la sesión de este dispositivo",
)
async def logout_route(
    payload: RefreshRequest,
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
) -> Response:
    """RF-32: el refresh token de este dispositivo deja de servir; los demás siguen."""
    await logout(payload.refresh_token, sessions)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserProfileRead, summary="El perfil propio")
async def get_me_route(
    user_id: CurrentUser,
    users: Annotated[UserRepository, Depends(get_current_user_repository)],
) -> UserProfileRead:
    """RF-9: el perfil de quien manda el token."""
    profile = await get_me(user_id, users)
    return UserProfileRead.from_record(profile)


@router.patch("/me", response_model=UserProfileRead, summary="Corrige el perfil propio")
async def update_me_route(
    payload: ProfileUpdate,
    user_id: CurrentUser,
    users: Annotated[UserRepository, Depends(get_current_user_repository)],
) -> UserProfileRead:
    """RF-10 a RF-12: solo lo enviado; devuelve el perfil como quedó guardado."""
    return UserProfileRead.from_record(await update_me(payload.to_changes(), user_id, users))


async def enforce_oauth_limit(request: Request) -> None:
    """120 ingresos con proveedor por IP por minuto."""
    await enforce_rate_limit(
        scope="oauth",
        identifier=_client_ip(request),
        limit=OAUTH_LIMIT,
        window_seconds=OAUTH_WINDOW_SECONDS,
    )


# Va antes que /auth/oauth/{provider}: si no, "complete" entraría como proveedor.
@router.post(
    "/auth/oauth/complete",
    response_model=AuthRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_oauth_limit)],
    summary="Completa el registro con el proveedor",
)
async def complete_social_registration_route(
    payload: CompleteRegistrationRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
) -> AuthRead:
    """RF-8: crea la cuenta con la identidad que verificó el proveedor."""
    result = await complete_social_registration(payload.to_registration(), payload.registration_token, users, sessions)
    return AuthRead.from_result(result)


@router.post(
    "/auth/oauth/{provider}",
    response_model=SignedInRead | RegistrationRequiredRead,
    dependencies=[Depends(enforce_oauth_limit)],
    summary="Ingresa con un proveedor (Google o Apple)",
)
async def sign_in_with_provider_route(
    payload: ProviderSignInRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    sessions: Annotated[SessionRepository, Depends(get_session_repository)],
    identities: Annotated[IdentityProvider, Depends(get_identity_provider)],
) -> SignedInRead | RegistrationRequiredRead:
    """RF-6 y RF-7: si el correo ya tiene cuenta se vincula y entra; si no, se completa el registro."""
    identity = await identities.verify(payload.id_token)
    outcome = await sign_in_with_provider(identity, users, sessions)
    match outcome:
        case SignedIn(tokens=tokens):
            return SignedInRead.from_record(tokens)
        case RegistrationRequired():
            return RegistrationRequiredRead.from_record(outcome)


async def enforce_password_reset_limit(request: Request) -> None:
    """5 pedidos de código por correo por hora: cada uno manda un correo."""
    await enforce_rate_limit(
        scope="password_reset",
        identifier=await _json_field(request, "email") or _client_ip(request),
        limit=PASSWORD_RESET_LIMIT,
        window_seconds=PASSWORD_RESET_WINDOW_SECONDS,
    )


async def enforce_password_reset_attempts(request: Request) -> None:
    """5 intentos de código por correo cada 15 minutos (RF-9)."""
    await enforce_rate_limit(
        scope="password_reset_attempts",
        identifier=await _json_field(request, "email") or _client_ip(request),
        limit=PASSWORD_RESET_ATTEMPTS,
        window_seconds=PASSWORD_RESET_ATTEMPTS_WINDOW_SECONDS,
    )


@router.post(
    "/auth/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_password_reset_limit)],
    summary="Pide el código para restablecer la contraseña",
)
async def request_password_reset_route(
    payload: PasswordResetRequest,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    resets: Annotated[PasswordResetRepository, Depends(get_password_reset_repository)],
    sender: Sender,
) -> Response:
    """RF-1 a RF-4 y RF-10: responde 202 siempre, exista o no la cuenta."""
    await request_password_reset(payload.email, users, resets, sender)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/auth/password-reset/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_password_reset_attempts)],
    summary="Comprueba el código sin cambiar la contraseña",
)
async def verify_password_reset_route(
    payload: PasswordResetVerify,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    resets: Annotated[PasswordResetRepository, Depends(get_password_reset_repository)],
) -> Response:
    """RF-15: 204 si el código sirve, 401 `invalid_reset_code` si no. No lo gasta y
    cuenta en los mismos 5 intentos que confirm (RF-9)."""
    await verify_password_reset_code(payload.email, payload.code, users, resets)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_password_reset_attempts)],
    summary="Cambia la contraseña con el código",
)
async def confirm_password_reset_route(
    payload: PasswordResetConfirm,
    services: Annotated[PasswordResetServices, Depends(get_password_reset_services)],
) -> Response:
    """RF-5 a RF-8: la contraseña nueva, el código quemado y todas las sesiones cerradas."""
    await confirm_password_reset(
        payload.to_new_password(),
        services.users,
        services.resets,
        services.sessions,
        services.audit,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
