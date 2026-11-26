"""El job que registra los recurrentes con `auto_post` (spec 003, RF-20).

Se prueba la función que hace el trabajo, contra PostgreSQL real, como en
`test_workers_retention.py`. El "hoy" sale de la base, en la zona horaria del
usuario: así la prueba no depende del reloj de la máquina.
"""

from uuid import UUID

from sqlalchemy import text

from app.core.db import user_session
from app.workers import celery
from app.workers.recurring import post_due_recurring_rules

_INSERT_RULE = text(
    """
    INSERT INTO finance.recurring_rules
        (user_id, account_id, category_id, amount, description, frequency, start_date, auto_post)
    SELECT :user_id, accounts.id, categories.id, 100, :description, 'monthly',
           ((now() AT TIME ZONE 'America/La_Paz')::date - INTERVAL '2 months')::date, :auto_post
    FROM finance.accounts AS accounts, finance.categories AS categories
    WHERE accounts.user_id = :user_id AND categories.user_id = :user_id AND categories.kind = 'expense'
    LIMIT 1
    RETURNING id
    """
)


async def _rule(user_id: UUID, *, auto_post: bool) -> UUID:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)"
                " VALUES (:user_id, :name, 'cash', 'BOB', 1000)"
            ),
            {"user_id": user_id, "name": f"Efectivo {auto_post}"},
        )
        rule_id: UUID = (
            await session.execute(
                _INSERT_RULE, {"user_id": user_id, "auto_post": auto_post, "description": f"Gimnasio {auto_post}"}
            )
        ).scalar_one()
    return rule_id


async def _state(user_id: UUID, rule_id: UUID) -> tuple[int, bool]:
    async with user_session(user_id) as session:
        posted = (
            await session.execute(
                text("SELECT count(*) FROM finance.transactions WHERE recurring_rule_id = :rule_id"),
                {"rule_id": rule_id},
            )
        ).scalar_one()
        upcoming = (
            await session.execute(
                text(
                    "SELECT next_due_on > (now() AT TIME ZONE 'America/La_Paz')::date"
                    " FROM finance.recurring_rules WHERE id = :rule_id"
                ),
                {"rule_id": rule_id},
            )
        ).scalar_one()
    return posted, upcoming


async def test_registra_cada_vencimiento_atrasado_y_solo_los_auto_post(user_id: UUID) -> None:
    automatic = await _rule(user_id, auto_post=True)
    manual = await _rule(user_id, auto_post=False)

    assert await post_due_recurring_rules() >= 3

    # Empezó hace 2 meses: vencía hace 2 meses, hace 1 y hoy.
    assert await _state(user_id, automatic) == (3, True)
    assert await _state(user_id, manual) == (0, False)

    await post_due_recurring_rules()  # otra corrida el mismo día no registra nada de nuevo
    assert await _state(user_id, automatic) == (3, True)


def test_la_tarea_esta_en_el_calendario() -> None:
    schedule = celery.conf.beat_schedule
    assert schedule["post-due-recurring-rules"]["task"] == "finance.post_due_recurring_rules"
    assert "finance.post_due_recurring_rules" in celery.tasks
