from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_responde_y_dice_si_llega_a_la_base() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert isinstance(response.json()["database"], bool)
