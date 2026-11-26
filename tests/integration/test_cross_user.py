"""QA de la RLS desde la API (MM-46): lo de otra persona responde 404 y no cambia.

Se recorren todas las rutas con un `{..._id}`. Una ruta nueva con id que no esté
en `_CASES` hace fallar `test_todas_las_rutas_con_id_estan_cubiertas`.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import user_session
from app.main import app

# Lo de la dueña, creado con SQL en su sesión: una fila de cada recurso.
_SEED = {
    "account_id": "INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)"
    " VALUES (:user_id, 'Efectivo', 'cash', 'BOB', 100000) RETURNING id",
    "category_id": "SELECT id FROM finance.categories WHERE user_id = :user_id AND template_key = 'groceries'",
    "transaction_id": "INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)"
    " SELECT :user_id, 'expense', accounts.id, categories.id, 10, current_date"
    " FROM finance.accounts AS accounts, finance.categories AS categories"
    " WHERE accounts.user_id = :user_id AND categories.user_id = :user_id AND categories.template_key = 'groceries'"
    " RETURNING id",
    "rule_id": "INSERT INTO finance.recurring_rules"
    " (user_id, account_id, category_id, amount, description, frequency, start_date)"
    " SELECT :user_id, accounts.id, categories.id, 50, 'Netflix', 'monthly', current_date"
    " FROM finance.accounts AS accounts, finance.categories AS categories"
    " WHERE accounts.user_id = :user_id AND categories.user_id = :user_id AND categories.template_key = 'groceries'"
    " RETURNING id",
    "goal_id": "INSERT INTO goals.goals (user_id, name, target_amount, currency)"
    " VALUES (:user_id, 'Viaje', 1000, 'BOB') RETURNING id",
    "budget_id": "INSERT INTO planning.budgets (user_id, category_id, currency, amount)"
    " SELECT :user_id, id, 'BOB', 400 FROM finance.categories WHERE user_id = :user_id AND template_key = 'groceries'"
    " RETURNING id",
    "device_id": "INSERT INTO iam.devices (user_id, platform, push_token)"
    " VALUES (:user_id, 'ios', 'apns-' || gen_random_uuid()) RETURNING id",
    "entry_id": "INSERT INTO ai.voice_entries (user_id, input_type, transcript, status)"
    " VALUES (:user_id, 'text', 'gasté 10', 'extracted') RETURNING id",
    "event_id": "INSERT INTO agenda.events (user_id, kind, activity_type, title, starts_at, ends_at)"
    " VALUES (:user_id, 'activity', 'sport', 'Fútbol', '2026-11-10T10:00:00Z', '2026-11-10T11:00:00Z')"
    " RETURNING id",
}

_CASES = [
    ("PATCH", "/v1/accounts/{account_id}", {"name": "Mía"}),
    ("PATCH", "/v1/transactions/{transaction_id}", {"description": "Mía"}),
    ("DELETE", "/v1/transactions/{transaction_id}", None),
    # Spec 014: una foto válida, así el 404 es por ser de otro y no por el formato.
    ("PUT", "/v1/transactions/{transaction_id}/receipt", b"\xff\xd8\xff\xe0foto"),
    ("GET", "/v1/transactions/{transaction_id}/receipt", None),
    ("DELETE", "/v1/transactions/{transaction_id}/receipt", None),
    ("PATCH", "/v1/recurring-rules/{rule_id}", {"description": "Mía"}),
    ("DELETE", "/v1/recurring-rules/{rule_id}", None),
    ("POST", "/v1/recurring-rules/{rule_id}/payments", {}),
    ("POST", "/v1/recurring-rules/{rule_id}/skip", None),
    ("PATCH", "/v1/categories/{category_id}", {"name": "Mía"}),
    ("DELETE", "/v1/categories/{category_id}", None),
    ("PATCH", "/v1/goals/{goal_id}", {"name": "Mía"}),
    ("DELETE", "/v1/goals/{goal_id}", None),
    ("POST", "/v1/goals/{goal_id}/contributions", {"amount": "10.00"}),
    (
        "POST",
        "/v1/goals/{goal_id}/withdrawals",
        {"amount": "10.00", "account_id": "00000000-0000-7000-8000-000000000001"},
    ),
    ("DELETE", "/v1/me/devices/{device_id}", None),
    ("PATCH", "/v1/budgets/{budget_id}", {"amount": "1.00"}),
    ("DELETE", "/v1/budgets/{budget_id}", None),
    ("GET", "/v1/voice-entries/{entry_id}", None),
    ("POST", "/v1/voice-entries/{entry_id}/confirm", {"transaction_id": "01a16a4f-6ba2-7f28-afbf-ebe873c11b16"}),
    ("POST", "/v1/voice-entries/{entry_id}/discard", None),
    ("GET", "/v1/agenda/{event_id}", None),
    ("PATCH", "/v1/agenda/{event_id}", {"title": "Mía"}),
    ("DELETE", "/v1/agenda/{event_id}", None),
]

# Sin id de un recurso: son públicas o el parámetro es un código del catálogo.
_NOT_OWNED = {
    "/v1/auth/email-verifications/{verification_id}",
    "/v1/auth/email-verifications/{verification_id}/resend",
    "/v1/auth/oauth/{provider}",
    "/v1/me/currencies/{code}",
    # MM-189: códigos de plan y de funcionalidad, del catálogo y no de un usuario.
    # Que nadie más que el administrador los toque lo prueba test_billing_admin.py.
    "/v1/admin/plans/{code}",
    "/v1/admin/plans/{code}/features/{key}",
    "/v1/admin/plans/{code}/prices/{period}/{currency}",
}

_SNAPSHOT = text(
    """
    SELECT (SELECT count(*) FROM finance.transactions WHERE user_id = :user_id AND deleted_at IS NULL),
           (SELECT count(*) FROM finance.recurring_rules WHERE user_id = :user_id AND deleted_at IS NULL),
           (SELECT count(*) FROM goals.goal_contributions WHERE user_id = :user_id),
           (SELECT count(*) FROM iam.devices WHERE user_id = :user_id AND revoked_at IS NULL),
           (SELECT string_agg(name, ',' ORDER BY id) FROM finance.accounts WHERE user_id = :user_id),
           (SELECT string_agg(name, ',' ORDER BY id) FROM finance.categories WHERE user_id = :user_id
                                                                              AND deleted_at IS NULL),
           (SELECT string_agg(name, ',' ORDER BY id) FROM goals.goals WHERE user_id = :user_id AND deleted_at IS NULL),
           (SELECT string_agg(amount::text, ',' ORDER BY id) FROM planning.budgets
            WHERE user_id = :user_id AND deleted_at IS NULL),
           (SELECT string_agg(status, ',' ORDER BY id) FROM ai.voice_entries WHERE user_id = :user_id),
           (SELECT string_agg(title, ',' ORDER BY id)
            FROM agenda.events WHERE user_id = :user_id AND deleted_at IS NULL)
    """
)


async def _snapshot(owner: UUID) -> tuple[object, ...]:
    async with user_session(owner) as session:
        return tuple((await session.execute(_SNAPSHOT, {"user_id": owner})).one())


def test_todas_las_rutas_con_id_estan_cubiertas() -> None:
    covered = {(method, path) for method, path, _ in _CASES}
    with_id = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{" in path and path not in _NOT_OWNED
        for method in operations
    }
    assert with_id == covered


@pytest.mark.parametrize(("method", "path", "body"), _CASES, ids=[f"{m} {p}" for m, p, _ in _CASES])
async def test_lo_de_otra_persona_responde_404_y_no_cambia(
    client: AsyncClient,
    new_financial_user: Callable[[str], Awaitable[UUID]],
    method: str,
    path: str,
    body: dict[str, object] | bytes | None,
) -> None:
    owner = await new_financial_user("BOB")
    ids: dict[str, str] = {}
    async with user_session(owner) as session:
        for name, sql in _SEED.items():
            ids[name] = str((await session.execute(text(sql), {"user_id": owner})).scalar_one())
    before = await _snapshot(owner)

    if isinstance(body, bytes):
        response = await client.request(method, path.format(**ids), content=body)
    else:
        response = await client.request(method, path.format(**ids), json=body)

    assert response.status_code == 404, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert await _snapshot(owner) == before
