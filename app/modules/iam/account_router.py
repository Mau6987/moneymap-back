"""La cuenta propia (spec 001, RF-15, RF-16 y RF-28): solo HTTP, sin SQL ni reglas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user_id
from app.modules.iam.application.commands.request_account_deletion import (
    AccountDeletionServices,
    request_account_deletion,
)
from app.modules.iam.application.commands.update_preferences import update_preferences
from app.modules.iam.application.queries.get_preferences import get_preferences
from app.modules.iam.deps import get_account_deletion_services, get_preferences_repository
from app.modules.iam.domain.ports import PreferencesRepository
from app.modules.iam.schemas import AccountDeletionRead, AccountDeletionRequest, PreferencesRead, PreferencesUpdate

router = APIRouter()


@router.post(
    "/me/deletion",
    response_model=AccountDeletionRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pide borrar la cuenta",
)
async def request_account_deletion_route(
    payload: AccountDeletionRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    services: Annotated[AccountDeletionServices, Depends(get_account_deletion_services)],
) -> AccountDeletionRead:
    """RF-28: con la contraseña o el proveedor; se borra en 30 días y entrar antes lo cancela."""
    scheduled_at = await request_account_deletion(user_id, payload.to_proof(), services)
    return AccountDeletionRead(deletion_scheduled_at=scheduled_at)


@router.get("/me/preferences", response_model=PreferencesRead, summary="Las preferencias propias")
async def get_preferences_route(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    preferences: Annotated[PreferencesRepository, Depends(get_preferences_repository)],
) -> PreferencesRead:
    """RF-15: tema, color de acento, modo privado e inicio de semana."""
    return PreferencesRead.from_record(await get_preferences(user_id, preferences))


@router.patch("/me/preferences", response_model=PreferencesRead, summary="Cambia las preferencias propias")
async def update_preferences_route(
    payload: PreferencesUpdate,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    preferences: Annotated[PreferencesRepository, Depends(get_preferences_repository)],
) -> PreferencesRead:
    """RF-15 y RF-16: solo lo enviado; un tema, color o día que no sirve es 422."""
    return PreferencesRead.from_record(await update_preferences(payload.to_changes(), user_id, preferences))
