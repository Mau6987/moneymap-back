"""El SQL del catálogo que usa el onboarding: países y bancos.

Son datos de referencia que el equipo mantiene sin desplegar código: `catalog`
lo puede leer cualquiera, no tiene RLS.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.domain.models import CountryOption, Institution

_SELECT_COUNTRIES = text(
    """
    SELECT code, name, currency
    FROM catalog.countries
    WHERE is_active
    ORDER BY sort_order, name
    """
)

_SELECT_INSTITUTIONS = text(
    """
    SELECT code, name, short_name, kind
    FROM catalog.financial_institutions
    WHERE is_active AND country_code = :country_code
    ORDER BY sort_order, short_name
    """
)


class SqlCatalogReader:
    """Implementa `CatalogReader`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def countries(self) -> list[CountryOption]:
        rows = (await self._session.execute(_SELECT_COUNTRIES)).mappings().all()
        return [CountryOption(code=row["code"], name=row["name"], currency=row["currency"]) for row in rows]

    async def institutions(self, country_code: str) -> list[Institution]:
        rows = (await self._session.execute(_SELECT_INSTITUTIONS, {"country_code": country_code})).mappings().all()
        return [
            Institution(code=row["code"], name=row["name"], short_name=row["short_name"], kind=row["kind"])
            for row in rows
        ]
