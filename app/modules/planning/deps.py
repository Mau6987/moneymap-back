"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.planning.infrastructure.budget_repository import SqlBudgetRepository
from app.modules.planning.infrastructure.forecast_reader import SqlForecastReader
from app.modules.planning.infrastructure.planning_reader import SqlPlanningReader
from app.modules.planning.infrastructure.what_if_base_reader import SqlWhatIfBaseReader


def get_planning_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlPlanningReader:
    return SqlPlanningReader(session)


def get_budget_repository(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlBudgetRepository:
    return SqlBudgetRepository(session)


def get_forecast_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlForecastReader:
    return SqlForecastReader(session)


def get_what_if_base_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlWhatIfBaseReader:
    return SqlWhatIfBaseReader(session)
