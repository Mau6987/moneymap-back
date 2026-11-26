"""Los errores que levanta la identidad.

Los del registro (`email_taken`, `terms_outdated`) no están aquí: los
levanta la base de datos y los traduce `core/errors.py` (constitución §3). Estos
son decisiones de la aplicación.
"""

from app.core.errors import ApiError, Unauthorized


class InvalidCredentials(Unauthorized):
    """Correo o contraseña que no coinciden (RF-20)."""

    code = "invalid_credentials"


class InvalidResetCode(Unauthorized):
    """El código del restablecimiento no sirve: no existe, venció o ya se usó (spec 008, RF-6)."""

    code = "invalid_reset_code"


class ProviderEmailMissing(ApiError):
    """El proveedor no dio el correo y el pedido tampoco (RF-8)."""

    status_code = 422
    code = "email_required"


class InvalidProviderToken(Unauthorized):
    """El token del proveedor no sirve: firma, audiencia, vencimiento o correo sin verificar."""

    code = "invalid_provider_token"


class InvalidRegistrationToken(Unauthorized):
    """El `registration_token` de un registro social no sirve o venció (RF-8)."""

    code = "invalid_registration_token"


class InvalidRefreshToken(Unauthorized):
    """Un refresh token que no existe o que venció (RF-17)."""

    code = "invalid_refresh_token"


class RefreshTokenReused(Unauthorized):
    """Se reusó un refresh token ya rotado: se cerró la sesión de ese dispositivo (RF-18)."""

    code = "refresh_token_reused"


class EmailAlreadyRegistered(ApiError):
    """Pidió verificar un correo que ya tiene cuenta (RF-22): que entre con su contraseña.

    Mismo `code` que el registro repetido, para que la app lo trate igual. No dice
    nada de la cuenta: ni el nombre ni cómo se registró.
    """

    status_code = 409
    code = "email_taken"


class EmailNotVerified(ApiError):
    """El correo no está confirmado: se registró sin abrir el link (RF-25) o
    intenta entrar sin verificarlo (MM-88). Mismo `code` para que la app muestre
    la misma pantalla en los dos casos."""

    status_code = 409
    code = "email_not_verified"


class VerificationExpired(ApiError):
    """El link venció sin abrirse, o el correo verificado no se usó a tiempo (RF-24, RF-25)."""

    status_code = 410
    code = "verification_expired"


class ReauthenticationFailed(ApiError):
    """RF-28: la contraseña o la cuenta del proveedor no son las de quien pide borrar la cuenta.

    403 y no 401: la sesión sigue siendo válida, así que la app no tiene que
    cerrarla; solo no alcanza para algo tan grave como borrar la cuenta.
    """

    status_code = 403
    code = "reauthentication_failed"
