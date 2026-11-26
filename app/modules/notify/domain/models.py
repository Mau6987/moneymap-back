"""Read models de los avisos (spec 006): Python puro."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NewDevice:
    """Un dispositivo que pide avisos (RF-8). El token push nunca sale de la API ni va a los logs."""

    platform: str
    push_token: str
    app_version: str | None
    os_version: str | None


@dataclass(frozen=True, slots=True)
class Device:
    id: UUID
    platform: str
    app_version: str | None
    os_version: str | None
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class InboxItem:
    """Un aviso recibido, para la pantalla Avisos."""

    id: UUID
    type_key: str
    title: str
    body: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class Inbox:
    items: list[InboxItem]
    unread: int


@dataclass(frozen=True, slots=True)
class NotificationSetting:
    """Un tipo de aviso y si le llega al usuario (RF-11). Los de seguridad y cobro no se apagan."""

    key: str
    description: str
    enabled: bool
    can_disable: bool
