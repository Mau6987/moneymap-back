"""Casos de uso de lectura: el catálogo del onboarding (países y bancos)."""

from collections.abc import Sequence

from app.modules.finance.domain.models import CountryOption, Institution
from app.modules.finance.domain.ports import CatalogReader


async def get_countries(catalog: CatalogReader) -> Sequence[CountryOption]:
    """Los países activos con su moneda local: el onboarding sugiere esa moneda."""
    return await catalog.countries()


async def get_institutions(country_code: str, catalog: CatalogReader) -> Sequence[Institution]:
    """Los bancos y billeteras de un país, para elegir el emisor de una tarjeta."""
    return await catalog.institutions(country_code)
