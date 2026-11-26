"""La bandeja de avisos de la pantalla Avisos: `GET /v1/me/notifications`."""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session

_INSERT = text(
    """
    INSERT INTO notify.notifications (user_id, type_key, title, body, data, created_at)
    VALUES (:user_id, 'recurring.due_soon', :title, 'Abre MoneyMap', '{"link": "/recurring"}',
            now() - make_interval(mins => :minutes))
    """
)


async def _notify(user_id: UUID, *titles: str) -> None:
    async with user_session(user_id) as session:
        for minutes, title in enumerate(titles):
            await session.execute(_INSERT, {"user_id": user_id, "title": title, "minutes": minutes})


async def test_lista_del_mas_nuevo_al_mas_viejo_por_paginas(client: AsyncClient, user_id: UUID) -> None:
    await _notify(user_id, "Nuevo", "Medio", "Viejo")

    first = (await client.get("/v1/me/notifications", params={"limit": 2})).json()
    rest = (await client.get("/v1/me/notifications", params={"before": first["items"][-1]["created_at"]})).json()

    assert [item["title"] for item in first["items"]] == ["Nuevo", "Medio"]
    assert (first["unread"], first["items"][0]["type"], first["items"][0]["data"]) == (
        3,
        "recurring.due_soon",
        {"link": "/recurring"},
    )
    assert [item["title"] for item in rest["items"]] == ["Viejo"]


async def test_marcar_como_leidos(client: AsyncClient, user_id: UUID) -> None:
    await _notify(user_id, "Uno", "Dos")

    assert (await client.post("/v1/me/notifications/read")).status_code == 204

    inbox = (await client.get("/v1/me/notifications")).json()
    assert inbox["unread"] == 0
    assert all(item["read_at"] is not None for item in inbox["items"])
