"""Caso de uso de escritura: pedir el borrado de la cuenta (spec 001, RF-28)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.core import clock
from app.core.security import verify_password
from app.modules.iam.domain.errors import ReauthenticationFailed
from app.modules.iam.domain.models import DeletionProof, Provider
from app.modules.iam.domain.ports import IdentityProvider, SecurityAudit, SessionRepository, UserRepository

# Cuántos días se guarda la cuenta antes de borrarla: entrar antes lo cancela.
ACCOUNT_DELETION_GRACE_DAYS = 30

REAUTHENTICATION_FAILED_DETAIL = "No pudimos confirmar que sos vos: revisá la contraseña o la cuenta con la que entrás"


@dataclass(frozen=True, slots=True)
class AccountDeletionServices:
    """Las piezas del borrado, todas sobre la misma transacción."""

    users: UserRepository
    sessions: SessionRepository
    audit: SecurityAudit
    identities: Callable[[Provider], IdentityProvider]


async def request_account_deletion(user_id: UUID, proof: DeletionProof, services: AccountDeletionServices) -> datetime:
    """Confirma quién es, deja la cuenta para borrar y cierra todas sus sesiones.

    Devuelve cuándo se borra. Hasta entonces, entrar de nuevo lo cancela (RF-30).
    """
    await _confirm_identity(user_id, proof, services)
    now = clock.utc_now()
    await services.users.schedule_deletion(user_id, now)
    await services.sessions.revoke_all(user_id, now)
    await services.audit.account_deletion_requested(user_id)
    return now + timedelta(days=ACCOUNT_DELETION_GRACE_DAYS)


async def _confirm_identity(user_id: UUID, proof: DeletionProof, services: AccountDeletionServices) -> None:
    """La contraseña de la cuenta, o una identidad del proveedor vinculada a ella."""
    if proof.password is not None:
        password_hash = await services.users.find_password_hash(user_id)
        if password_hash is None or not verify_password(proof.password, password_hash):
            raise ReauthenticationFailed(REAUTHENTICATION_FAILED_DETAIL)
        return
    if proof.provider is None or proof.id_token is None:
        raise ReauthenticationFailed(REAUTHENTICATION_FAILED_DETAIL)
    identity = await services.identities(proof.provider).verify(proof.id_token)
    if not await services.users.has_identity(user_id, identity.provider, identity.subject):
        raise ReauthenticationFailed(REAUTHENTICATION_FAILED_DETAIL)
