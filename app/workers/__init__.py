"""La app de Celery y el calendario de los trabajos del worker.

Hasta ahora el worker no existía: `celery -A app.workers worker --beat` fallaba
porque no había app de Celery. Acá está, con el calendario de los trabajos
programados.

El broker es el mismo Redis de la API (`REDIS_URL`).
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

# El nombre es `celery` a propósito: así `celery -A app.workers` lo encuentra, que
# es el comando que documenta AGENTS.md.
celery = Celery(
    "moneymap",
    broker=get_settings().redis_url,
    include=[
        "app.workers.retention",
        "app.workers.account_deletion",
        "app.workers.recurring",
        "app.workers.money_story",
        "app.workers.notifications",
        "app.workers.voice",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # Todos los días a las 04:00 UTC, cuando nadie está registrándose.
        "purge-old-identity-tokens": {
            "task": "identity.purge_old_tokens",
            "schedule": crontab(hour=4, minute=0),
        },
        # Las cuentas que pidieron borrarse hace más de 30 días (spec 001, RF-29).
        "purge-deleted-accounts": {
            "task": "identity.purge_deleted_accounts",
            "schedule": crontab(hour=4, minute=30),
        },
        # Los recurrentes con auto_post que ya vencieron (spec 003, RF-20). A las
        # 05:00 UTC ya es el día siguiente en Bolivia (UTC-4).
        "post-due-recurring-rules": {
            "task": "finance.post_due_recurring_rules",
            "schedule": crontab(hour=5, minute=0),
        },
        # La Money Story del mes que cerró (spec 006, RF-1). Todos los días: cada
        # persona cierra el mes en su zona horaria y una corrida perdida se recupera.
        "close-money-story-months": {
            "task": "reports.close_months",
            "schedule": crontab(hour=5, minute=30),
        },
        # Los pagos recurrentes que se acercan (spec 006, RF-15). A las 13:00 UTC
        # son las 09:00 en Bolivia: el aviso no llega de madrugada.
        "remind-recurring-payments": {
            "task": "notify.remind_recurring",
            "schedule": crontab(hour=13, minute=0),
        },
        # Los hitos de las metas (spec 006, RF-16): cada hora, para que el aviso
        # llegue poco después del aporte.
        "notify-goal-milestones": {
            "task": "notify.goal_milestones",
            "schedule": crontab(minute=10),
        },
        # Los presupuestos al 80 y al 100 % (spec 009, RF-10): cada hora.
        "notify-budget-alerts": {
            "task": "notify.budget_alerts",
            "schedule": crontab(minute=20),
        },
        # Un dictado que un worker muerto dejó pendiente no queda para siempre
        # (spec 012, QA BUG-047).
        "fail-stale-voice-entries": {
            "task": "ai.fail_stale_voice_entries",
            "schedule": crontab(minute="*/5"),
        },
    },
)
