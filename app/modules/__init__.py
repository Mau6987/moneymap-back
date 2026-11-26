"""Módulos de dominio: los mismos esquemas de la base de datos."""

from fastapi import APIRouter

from app.modules.ai.router import router as ai
from app.modules.billing.admin_router import router as billing_admin
from app.modules.billing.router import router as billing
from app.modules.finance.router import router as finance
from app.modules.goals.router import router as goals
from app.modules.iam.router import router as iam
from app.modules.notify.router import router as notify
from app.modules.ops.router import router as ops
from app.modules.planning.router import budgets_router
from app.modules.planning.router import router as planning
from app.modules.reports.router import money_story_router
from app.modules.reports.router import router as reports

ROUTERS: list[APIRouter] = [
    iam,
    billing,
    billing_admin,
    finance,
    goals,
    planning,
    budgets_router,
    reports,
    money_story_router,
    notify,
    ai,
    ops,
]
