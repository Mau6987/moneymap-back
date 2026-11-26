"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.billing.infrastructure.admin_plans import SqlAdminPlans
from app.modules.billing.infrastructure.plan_reader import SqlPlanReader
from app.modules.billing.infrastructure.plan_writer import SqlPlanWriter


def get_plan_reader(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlPlanReader:
    return SqlPlanReader(session)


def get_plan_writer(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlPlanWriter:
    return SqlPlanWriter(session)


def get_admin_plans(session: Annotated[AsyncSession, Depends(current_session)]) -> SqlAdminPlans:
    return SqlAdminPlans(session)
