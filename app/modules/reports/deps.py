"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.reports.infrastructure.money_story_reader import SqlMoneyStoryReader
from app.modules.reports.infrastructure.reports_reader import SqlReportsReader


def get_reports_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlReportsReader:
    return SqlReportsReader(session)


def get_money_story_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlMoneyStoryReader:
    return SqlMoneyStoryReader(session)
