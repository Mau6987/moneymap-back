"""El SQL de elegir plan (MM-186): todo lo hace `billing.change_plan` en la base."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# El usuario sale de app.user_id dentro de la función: nunca va como parámetro.
_CHANGE_PLAN = text("SELECT billing.change_plan(:code)")


class SqlPlanWriter:
    """Implementa `PlanWriter` sobre la sesión del usuario."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def change(self, code: str) -> bool:
        return bool((await self._session.execute(_CHANGE_PLAN, {"code": code})).scalar_one())
