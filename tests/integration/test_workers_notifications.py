"""Los avisos que encolan los workers (spec 006, RF-13 a RF-15 y RF-17).

Las fechas salen del "hoy" de la base en la zona horaria del usuario, como en
`test_workers_recurring.py`.
"""

from uuid import UUID

from sqlalchemy import text

from app.core.db import user_session
from app.workers import celery
from app.workers.money_story import close_months
from app.workers.notifications import notify_budget_alerts, notify_goal_milestones, remind_recurring

_INSERT_RULE = text(
    """
    INSERT INTO finance.recurring_rules (user_id, account_id, category_id, amount, description, frequency, start_date)
    SELECT :user_id, accounts.id, categories.id, :amount, :description, 'monthly',
           (now() AT TIME ZONE users.timezone)::date + CAST(:in_days AS int)
    FROM iam.users AS users, finance.accounts AS accounts, finance.categories AS categories
    WHERE users.id = :user_id AND accounts.user_id = :user_id AND categories.user_id = :user_id
      AND categories.template_key = :category
    """
)


async def _setup(user_id: UUID, *, device: bool = True) -> None:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)"
                " VALUES (:user_id, 'Efectivo', 'cash', 'BOB', 100000)"
            ),
            {"user_id": user_id},
        )
        if device:
            await session.execute(
                text("INSERT INTO iam.devices (user_id, platform, push_token) VALUES (:user_id, 'ios', :token)"),
                {"user_id": user_id, "token": f"apns-{user_id}"},
            )


async def _rule(user_id: UUID, description: str, amount: int, in_days: int, category: str = "subscriptions") -> None:
    params = {
        "user_id": user_id,
        "description": description,
        "amount": amount,
        "in_days": in_days,
        "category": category,
    }
    async with user_session(user_id) as session:
        await session.execute(_INSERT_RULE, params)


async def _queued(user_id: UUID) -> list[tuple[str, str, str]]:
    async with user_session(user_id) as session:
        rows = await session.execute(
            text("SELECT type_key, title, body FROM notify.notifications WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [tuple(row) for row in rows]


async def test_un_solo_aviso_para_los_gastos_del_mismo_dia_rf15(user_id: UUID) -> None:
    await _setup(user_id)
    await _rule(user_id, "Netflix", 50, in_days=1)
    await _rule(user_id, "Gimnasio", 150, in_days=1)
    await _rule(user_id, "Sueldo", 5000, in_days=1, category="salary")  # un ingreso no avisa
    await _rule(user_id, "Luz", 80, in_days=3)  # todavía no

    await remind_recurring()
    await remind_recurring()  # otra corrida el mismo día no repite

    assert await _queued(user_id) == [
        ("recurring.due_soon", "Tienes 2 pagos recurrentes mañana", "Gimnasio (Bs 150.00), Netflix (Bs 50.00).")
    ]


async def test_avisa_tambien_el_dia_que_vence(user_id: UUID) -> None:
    await _setup(user_id)
    await _rule(user_id, "Alquiler", 50, in_days=0)

    await remind_recurring()
    await remind_recurring()  # otra corrida el mismo día no repite

    assert await _queued(user_id) == [("recurring.due_soon", "Tienes un pago recurrente hoy", "Alquiler (Bs 50.00).")]


async def test_con_el_modo_privado_no_lleva_montos_ni_nombres_rf14(user_id: UUID) -> None:
    await _setup(user_id)
    await _rule(user_id, "Netflix", 50, in_days=1)
    async with user_session(user_id) as session:
        await session.execute(
            text("UPDATE iam.user_preferences SET hide_amounts = true WHERE user_id = :user_id"), {"user_id": user_id}
        )

    await remind_recurring()

    assert await _queued(user_id) == [
        ("recurring.due_soon", "Tienes un pago recurrente mañana", "Abre MoneyMap para verlo.")
    ]


async def test_no_guarda_nada_si_esta_apagado_rf13(user_id: UUID) -> None:
    await _setup(user_id)
    await _rule(user_id, "Netflix", 50, in_days=1)
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO notify.preferences (user_id, type_key, is_enabled)"
                " VALUES (:user_id, 'recurring.due_soon', false)"
            ),
            {"user_id": user_id},
        )

    await remind_recurring()

    assert await _queued(user_id) == []


async def test_sin_dispositivo_queda_en_la_bandeja_sin_push_rf13(user_id: UUID) -> None:
    await _setup(user_id, device=False)
    await _rule(user_id, "Netflix", 50, in_days=1)

    await remind_recurring()

    async with user_session(user_id) as session:
        statuses = (
            await session.execute(
                text("SELECT status FROM notify.notifications WHERE user_id = :user_id"), {"user_id": user_id}
            )
        ).scalars()
        assert list(statuses) == ["skipped"]


async def test_avisa_una_vez_que_la_money_story_esta_lista_rf17(user_id: UUID) -> None:
    await _setup(user_id)
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on,"
                " description)"
                " SELECT :user_id, 'expense', accounts.id, categories.id, 10,"
                " (date_trunc('month', now() AT TIME ZONE 'America/La_Paz') - INTERVAL '1 month')::date, 'Prueba'"
                " FROM finance.accounts AS accounts, finance.categories AS categories"
                " WHERE accounts.user_id = :user_id AND categories.user_id = :user_id"
                " AND categories.template_key = 'groceries'"
            ),
            {"user_id": user_id},
        )

    await close_months()

    [(type_key, title, body)] = await _queued(user_id)
    assert (type_key, title) == ("money_story.ready", "Tu Money Story está lista")
    assert body.startswith("Mira cómo te fue en ")


async def _contribute(user_id: UUID, goal_id: UUID, amount: int) -> None:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO goals.goal_contributions (user_id, goal_id, amount) VALUES (:user_id, :goal_id, :amount)"
            ),
            {"user_id": user_id, "goal_id": goal_id, "amount": amount},
        )


async def test_avisa_cada_hito_de_una_meta_una_sola_vez_rf16(user_id: UUID) -> None:
    await _setup(user_id)
    async with user_session(user_id) as session:
        goal_id = (
            await session.execute(
                text(
                    "INSERT INTO goals.goals (user_id, name, target_amount, currency)"
                    " VALUES (:user_id, 'Viaje', 1000, 'BOB') RETURNING id"
                ),
                {"user_id": user_id},
            )
        ).scalar_one()

    await notify_goal_milestones()  # 0 %: nada
    await _contribute(user_id, goal_id, 300)
    await notify_goal_milestones()
    await notify_goal_milestones()  # el mismo hito no se repite
    await _contribute(user_id, goal_id, 400)  # del 30 al 70 %: solo el 50
    await notify_goal_milestones()
    await _contribute(user_id, goal_id, 300)
    await notify_goal_milestones()

    assert await _queued(user_id) == [
        ("goal.milestone", "Vas por el 25 % de tu meta", "Viaje: llevas Bs 300.00 de Bs 1000.00."),
        ("goal.milestone", "Vas por el 50 % de tu meta", "Viaje: llevas Bs 700.00 de Bs 1000.00."),
        ("goal.achieved", "Cumpliste tu meta", "Viaje: llegaste a Bs 1000.00."),
    ]


async def _spend(user_id: UUID, amount: int) -> None:
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)"
                " SELECT :user_id, 'expense', accounts.id, categories.id, :amount,"
                " (now() AT TIME ZONE 'America/La_Paz')::date"
                " FROM finance.accounts AS accounts, finance.categories AS categories"
                " WHERE accounts.user_id = :user_id AND categories.user_id = :user_id"
                " AND categories.template_key = 'groceries'"
            ),
            {"user_id": user_id, "amount": amount},
        )


async def test_avisa_el_80_y_el_100_de_un_presupuesto_una_vez_spec009_rf10(user_id: UUID) -> None:
    await _setup(user_id)
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO planning.budgets (user_id, category_id, currency, amount)"
                " SELECT :user_id, id, 'BOB', 400 FROM finance.categories"
                " WHERE user_id = :user_id AND template_key = 'groceries'"
            ),
            {"user_id": user_id},
        )

    await _spend(user_id, 300)  # 75 %: nada
    await notify_budget_alerts()
    await _spend(user_id, 30)  # 82 %
    await notify_budget_alerts()
    await notify_budget_alerts()  # el mismo umbral no se repite
    await _spend(user_id, 100)  # 107 %
    await notify_budget_alerts()

    assert await _queued(user_id) == [
        ("budget.threshold", "Usaste el 80 % de Supermercado", "Llevas Bs 330.00 de Bs 400.00 este mes."),
        ("budget.exceeded", "Superaste tu presupuesto de Supermercado", "Llevas Bs 430.00 de Bs 400.00 este mes."),
    ]


async def test_respeta_los_avisos_apagados_de_cada_presupuesto_spec009_rf18(user_id: UUID) -> None:
    await _setup(user_id)
    async with user_session(user_id) as session:
        await session.execute(
            text(
                "INSERT INTO planning.budgets (user_id, category_id, currency, amount, alert_at_80, alert_at_100)"
                " SELECT :user_id, id, 'BOB', 400, true, false FROM finance.categories"
                " WHERE user_id = :user_id AND template_key = 'groceries'"
            ),
            {"user_id": user_id},
        )

    await _spend(user_id, 500)  # 125 %, pero el del 100 % está apagado
    await notify_budget_alerts()

    assert [type_key for type_key, _, _ in await _queued(user_id)] == ["budget.threshold"]


def test_las_tareas_estan_en_el_calendario() -> None:
    assert celery.conf.beat_schedule["remind-recurring-payments"]["task"] == "notify.remind_recurring"
    assert celery.conf.beat_schedule["notify-goal-milestones"]["task"] == "notify.goal_milestones"
    assert celery.conf.beat_schedule["notify-budget-alerts"]["task"] == "notify.budget_alerts"
    assert {"notify.remind_recurring", "notify.goal_milestones", "notify.budget_alerts"} <= set(celery.tasks)
