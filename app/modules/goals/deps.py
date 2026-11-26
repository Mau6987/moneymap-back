"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.goals.infrastructure.goal_movement_reader import SqlGoalMovementReader
from app.modules.goals.infrastructure.goal_repository import SqlGoalRepository


def get_goal_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlGoalRepository:
    return SqlGoalRepository(session)


def get_goal_movement_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlGoalMovementReader:
    return SqlGoalMovementReader(session)
