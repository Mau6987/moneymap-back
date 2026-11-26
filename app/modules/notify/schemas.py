"""Esquemas de los avisos (spec 006). El token push entra pero nunca sale."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.modules.notify.domain.models import Device, Inbox, NewDevice, NotificationSetting

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
PushToken = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]


class DeviceCreate(BaseModel):
    """RF-8. `push_token` es el que da el sistema: FCM en Android, APNs en iOS."""

    platform: Literal["ios", "android"]
    push_token: PushToken = Field(repr=False)
    app_version: ShortText | None = Field(default=None, examples=["1.0.3"])
    os_version: ShortText | None = Field(default=None, examples=["17.5"])

    def to_new(self) -> NewDevice:
        return NewDevice(self.platform, self.push_token, self.app_version, self.os_version)


class DeviceRead(BaseModel):
    id: UUID
    platform: str
    app_version: str | None
    os_version: str | None
    created_at: datetime
    last_seen_at: datetime

    @classmethod
    def from_record(cls, device: Device) -> "DeviceRead":
        return cls(
            id=device.id,
            platform=device.platform,
            app_version=device.app_version,
            os_version=device.os_version,
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
        )


class NotificationSettingRead(BaseModel):
    """RF-11. `can_disable` en false: avisos de seguridad y de cobro, siempre encendidos."""

    type: str = Field(examples=["goal.milestone"])
    description: str
    enabled: bool
    can_disable: bool


class NotificationSettingsRead(BaseModel):
    items: list[NotificationSettingRead]

    @classmethod
    def from_records(cls, settings: Sequence[NotificationSetting]) -> "NotificationSettingsRead":
        return cls(
            items=[
                NotificationSettingRead(
                    type=setting.key,
                    description=setting.description,
                    enabled=setting.enabled,
                    can_disable=setting.can_disable,
                )
                for setting in settings
            ]
        )


class NotificationSettingChange(BaseModel):
    type: str = Field(max_length=100, examples=["goal.milestone"])
    enabled: bool


class NotificationSettingsUpdate(BaseModel):
    """RF-11 y RF-12: solo cambian los tipos enviados; uno que no existe o no se apaga es 422."""

    items: list[NotificationSettingChange] = Field(min_length=1, max_length=50)

    def to_changes(self) -> dict[str, bool]:
        return {item.type: item.enabled for item in self.items}


class InboxItemRead(BaseModel):
    id: UUID
    type: str = Field(examples=["budget.threshold"])
    title: str
    body: str
    data: dict[str, Any] = Field(description="El deep link y los ids relacionados")
    created_at: datetime
    read_at: datetime | None


class InboxRead(BaseModel):
    items: list[InboxItemRead]
    unread: int = Field(description="Cuántos sin leer en total, no solo en esta página")

    @classmethod
    def from_record(cls, inbox: Inbox) -> "InboxRead":
        return cls(
            items=[
                InboxItemRead(
                    id=item.id,
                    type=item.type_key,
                    title=item.title,
                    body=item.body,
                    data=item.data,
                    created_at=item.created_at,
                    read_at=item.read_at,
                )
                for item in inbox.items
            ],
            unread=inbox.unread,
        )
