"""Cableado del módulo: quién construye cada pieza con la sesión de la petición."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import current_session
from app.modules.notify.infrastructure.device_repository import SqlDeviceRepository
from app.modules.notify.infrastructure.inbox_repository import SqlInboxRepository
from app.modules.notify.infrastructure.settings_repository import SqlSettingsRepository

UserSession = Annotated[AsyncSession, Depends(current_session)]


def get_device_repository(session: UserSession) -> SqlDeviceRepository:
    return SqlDeviceRepository(session)


def get_settings_repository(session: UserSession) -> SqlSettingsRepository:
    return SqlSettingsRepository(session)


def get_inbox_repository(session: UserSession) -> SqlInboxRepository:
    return SqlInboxRepository(session)
