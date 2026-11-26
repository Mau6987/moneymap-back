"""Endpoints de las metas (spec 005): HTTP, sin SQL ni reglas."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_current_user_id
from app.core.idempotency import IdempotentRequest, get_idempotent_request
from app.core.validation import CurrencyCode
from app.modules.goals.application.commands.add_contribution import add_contribution
from app.modules.goals.application.commands.create_goal import create_goal
from app.modules.goals.application.commands.delete_goal import delete_goal
from app.modules.goals.application.commands.update_goal import update_goal
from app.modules.goals.application.commands.withdraw import withdraw
from app.modules.goals.application.queries.get_goal_movements import get_goal_movements
from app.modules.goals.application.queries.get_goals import get_goals
from app.modules.goals.deps import get_goal_movement_reader, get_goal_repository
from app.modules.goals.domain.models import GoalMovementFilters
from app.modules.goals.domain.ports import GoalMovementReader, GoalRepository
from app.modules.goals.schemas import (
    GOAL_MOVEMENT_PAGE_DEFAULT_SIZE,
    GOAL_MOVEMENT_PAGE_MAX_SIZE,
    ContributionCreate,
    ContributionCreatedRead,
    GoalCreate,
    GoalMovementPageRead,
    GoalRead,
    GoalUpdate,
    WithdrawalCreate,
    decode_goal_movement_cursor,
)

router = APIRouter(prefix="/goals", tags=["goals"])

User = Annotated[UUID, Depends(get_current_user_id)]
Goals = Annotated[GoalRepository, Depends(get_goal_repository)]


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED, summary="Crea una meta")
async def create_goal_route(payload: GoalCreate, user_id: User, goals: Goals) -> GoalRead:
    """RF-1 a RF-3. Si el plan tuviera un límite de metas: 409 `plan_limit`."""
    return GoalRead.from_record(await create_goal(payload.to_new_goal(), user_id, goals))


@router.get("", response_model=list[GoalRead], summary="Las metas con su avance")
async def get_goals_route(user_id: User, goals: Goals) -> list[GoalRead]:
    """RF-9: la de prioridad más alta primero; cada una en su moneda."""
    return [GoalRead.from_record(goal) for goal in await get_goals(user_id, goals)]


@router.get(
    "/movements",
    response_model=GoalMovementPageRead,
    summary="Los aportes y retiros de las metas, para Movimientos",
)
async def get_goal_movements_route(
    user_id: User,
    reader: Annotated[GoalMovementReader, Depends(get_goal_movement_reader)],
    currency: Annotated[CurrencyCode | None, Query(examples=["BOB"])] = None,
    account_id: Annotated[UUID | None, Query(description="La cuenta de donde salió o a donde volvió")] = None,
    from_date: Annotated[date | None, Query(alias="from", description="Desde ese día, incluido")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Hasta ese día, incluido")] = None,
    cursor: Annotated[str | None, Query(description="El `next_cursor` de la página anterior")] = None,
    limit: Annotated[int, Query(ge=1, le=GOAL_MOVEMENT_PAGE_MAX_SIZE)] = GOAL_MOVEMENT_PAGE_DEFAULT_SIZE,
) -> GoalMovementPageRead:
    """REQ-056: el filtro "Metas" de Movimientos, del más reciente al más viejo.

    Un aporte o un retiro mueve dinero de una cuenta pero no es un movimiento
    del historial: esta lista los muestra. El `next_cursor` sirve con los mismos
    filtros.
    """
    filters = GoalMovementFilters(currency=currency, account_id=account_id, from_date=from_date, to_date=to_date)
    after = None if cursor is None else decode_goal_movement_cursor(cursor)
    return GoalMovementPageRead.from_record(await get_goal_movements(user_id, filters, after, limit, reader))


@router.patch("/{goal_id}", response_model=GoalRead, summary="Corrige una meta")
async def update_goal_route(goal_id: UUID, payload: GoalUpdate, user_id: User, goals: Goals) -> GoalRead:
    """RF-4: solo lo enviado."""
    return GoalRead.from_record(await update_goal(payload.to_changes(), goal_id, user_id, goals))


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borra una meta")
async def delete_goal_route(goal_id: UUID, user_id: User, goals: Goals) -> Response:
    """RF-5: la meta y sus aportes; ninguna cuenta cambia."""
    await delete_goal(goal_id, user_id, goals)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{goal_id}/contributions",
    response_model=ContributionCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Aporta a una meta",
)
async def add_contribution_route(
    goal_id: UUID,
    payload: ContributionCreate,
    user_id: User,
    goals: Goals,
    idempotency: Annotated[IdempotentRequest, Depends(get_idempotent_request)],
) -> ContributionCreatedRead:
    """RF-6 a RF-8. Con `Idempotency-Key`, un reintento no aporta dos veces."""
    stored = await idempotency.replay()
    if stored is not None:
        return ContributionCreatedRead.model_validate_json(stored)
    record = await add_contribution(payload.to_contribution(), goal_id, user_id, goals)
    response = ContributionCreatedRead.from_record(record)
    await idempotency.remember(response.model_dump_json())
    return response


@router.post(
    "/{goal_id}/withdrawals",
    response_model=ContributionCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Saca dinero de una meta a una cuenta",
)
async def withdraw_route(
    goal_id: UUID,
    payload: WithdrawalCreate,
    user_id: User,
    goals: Goals,
    idempotency: Annotated[IdempotentRequest, Depends(get_idempotent_request)],
) -> ContributionCreatedRead:
    """RF-20. El retiro sale como aporte negativo; más de lo acumulado es 422 `goal_insufficient`."""
    stored = await idempotency.replay()
    if stored is not None:
        return ContributionCreatedRead.model_validate_json(stored)
    record = await withdraw(payload.to_withdrawal(), goal_id, user_id, goals)
    response = ContributionCreatedRead.from_record(record)
    await idempotency.remember(response.model_dump_json())
    return response
