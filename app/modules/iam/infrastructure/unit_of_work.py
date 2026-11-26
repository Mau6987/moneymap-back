"""La unidad de trabajo: la sesión de la petición, que ya existe."""

from sqlalchemy.ext.asyncio import AsyncSession


class SqlUnitOfWork:
    """Implementa `UnitOfWork` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()
