"""Filtros y búsqueda del historial contra PostgreSQL 16 (spec 002, RF-32)."""

from httpx import AsyncClient

CASH_BOB = {"name": "Efectivo", "type": "cash", "currency": "BOB", "opening_balance": "1000.00"}


async def _categories(client: AsyncClient) -> dict[str, str]:
    return {item["template_key"]: item["id"] for item in (await client.get("/v1/categories")).json()}


async def _history(client: AsyncClient, **params: str) -> list[str]:
    response = await client.get("/v1/transactions", params=params)
    assert response.status_code == 200, response.text
    return [item["description"] for item in response.json()["items"]]


async def _seed(client: AsyncClient) -> dict[str, str]:
    account = (await client.post("/v1/accounts", json=CASH_BOB)).json()["id"]
    categories = await _categories(client)
    moves = [
        ("groceries", "Supermercado Ketal", "2026-09-30"),
        ("restaurants", "Almuerzo", "2026-10-01"),
        ("groceries", "Descuento 50% en el mercado", "2026-10-15"),
        ("groceries", "Descuento 500 en el mercado", "2026-10-31"),
    ]
    for key, description, occurred_on in moves:
        response = await client.post(
            "/v1/transactions",
            json={
                "kind": "expense",
                "account_id": account,
                "category_id": categories[key],
                "amount": "10.00",
                "occurred_on": occurred_on,
                "description": description,
            },
        )
        assert response.status_code == 201, response.text
    return categories


async def test_filtra_por_fechas_incluidos_los_extremos_rf32(client: AsyncClient) -> None:
    await _seed(client)

    october = await _history(client, **{"from": "2026-10-01", "to": "2026-10-31"})

    assert october == ["Descuento 500 en el mercado", "Descuento 50% en el mercado", "Almuerzo"]


async def test_filtra_por_categoria_rf32(client: AsyncClient) -> None:
    categories = await _seed(client)

    restaurants = await _history(client, category_id=categories["restaurants"])

    assert restaurants == ["Almuerzo"]


async def test_filtra_por_moneda(client: AsyncClient, allow_more_currencies: None) -> None:
    categories = await _seed(client)
    dollars = {**CASH_BOB, "name": "Dólares", "currency": "USD", "opening_balance": "300.00"}
    account = (await client.post("/v1/accounts", json=dollars)).json()["id"]
    expense = {"kind": "expense", "account_id": account, "amount": "5.00", "occurred_on": "2026-10-02"}
    expense["category_id"] = categories["groceries"]
    created = await client.post("/v1/transactions", json={**expense, "description": "Libro"})
    assert created.status_code == 201, created.text

    assert await _history(client, currency="USD") == ["Libro"]
    assert len(await _history(client, currency="BOB")) == 4


async def test_busca_en_la_descripcion_sin_mayusculas_y_sin_comodines_rf32(client: AsyncClient) -> None:
    await _seed(client)

    assert await _history(client, q="  KETAL ") == ["Supermercado Ketal"]
    assert await _history(client, q="50%") == ["Descuento 50% en el mercado"]
    assert await _history(client, q="mercado", to="2026-10-20") == ["Descuento 50% en el mercado", "Supermercado Ketal"]
    assert len(await _history(client, q="   ")) == 4


async def test_el_cursor_sigue_con_los_mismos_filtros_rf32(client: AsyncClient) -> None:
    await _seed(client)

    first = (await client.get("/v1/transactions", params={"q": "mercado", "limit": 2})).json()
    second = (
        await client.get("/v1/transactions", params={"q": "mercado", "limit": 2, "cursor": first["next_cursor"]})
    ).json()

    assert [item["description"] for item in first["items"] + second["items"]] == [
        "Descuento 500 en el mercado",
        "Descuento 50% en el mercado",
        "Supermercado Ketal",
    ]
    assert second["next_cursor"] is None


async def test_rechaza_un_rango_al_reves_rf32(client: AsyncClient) -> None:
    response = await client.get("/v1/transactions", params={"from": "2026-10-31", "to": "2026-10-01"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
