from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine: AsyncEngine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def user_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """Sesión de un usuario: una transacción que empieza con app.user_id.

    Sin ese valor la RLS no devuelve filas. Es la única forma de abrir una
    sesión para atender a un usuario (ver AGENTS.md).
    """
    async with SessionLocal() as session, session.begin():
        await session.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
        yield session
