"""Puertos de los reportes: lo que la aplicación pide y la infraestructura implementa."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.reports.domain.models import FlowCategories, FlowGroup, MoneyFlow, MoneyStory


class ReportsReader(Protocol):
    """Se calcula en cada consulta, no se guarda nada (spec 004, consistencia).

    `month` es el primer día del mes pedido; `on`, un día: el periodo
    financiero del usuario (semanal, quincenal o mensual) que lo contiene. Sin
    ninguno, el periodo vigente. `currency` None es la principal. Los dos devuelven None si el
    usuario todavía no tiene moneda principal.
    """

    async def money_flow(
        self, user_id: UUID, currency: str | None, month: date | None, on: date | None = None
    ) -> MoneyFlow | None: ...

    async def flow_categories(
        self, user_id: UUID, currency: str | None, month: date | None, group: FlowGroup, on: date | None = None
    ) -> FlowCategories | None: ...


class MoneyStoryReader(Protocol):
    """Lo que guardó el cierre de mes (spec 006). `month` None es el último mes con historia."""

    async def month(self, user_id: UUID, month: date | None, currency: str | None) -> Sequence[MoneyStory]: ...
