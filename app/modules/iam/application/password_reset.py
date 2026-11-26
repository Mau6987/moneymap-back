"""La comprobación del código del restablecimiento, compartida por verify y confirm (spec 008).

Vive fuera de `commands/` y de `queries/` para que la query no dependa de un command:
los dos casos de uso comprueban el código exactamente igual.
"""

from uuid import UUID

from app.core import clock
from app.core.security import DUMMY_PASSWORD_HASH, verify_code
from app.modules.iam.domain.errors import InvalidResetCode
from app.modules.iam.domain.ports import PasswordResetRepository, UserRepository

# El mismo error para todo: no sirve para averiguar si el correo existe (RF-12).
INVALID_CODE_DETAIL = "Ese código no sirve o venció: pedí uno nuevo"


async def valid_code_owner(
    email: str,
    code: str,
    users: UserRepository,
    resets: PasswordResetRepository,
) -> UUID:
    """El usuario del código vigente que coincide, o `InvalidResetCode`.

    Lo usan `verify` y `confirm`: los dos responden lo mismo si el correo no existe,
    si no tiene contraseña, si el código venció o si no coincide (RF-12).

    Se hace siempre una comprobación argon2, aunque el correo no exista o no haya
    código pendiente: así el tiempo de respuesta tampoco dice si la cuenta está.
    """
    identity = await users.find_password_identity(email)
    code_hash = None
    if identity is not None:
        code_hash = await resets.latest_code_hash(identity.user_id, clock.utc_now())
    if not verify_code(code, code_hash or DUMMY_PASSWORD_HASH) or identity is None or code_hash is None:
        raise InvalidResetCode(INVALID_CODE_DETAIL)
    return identity.user_id
