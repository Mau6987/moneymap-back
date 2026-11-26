"""Caso de uso de lectura: el historial de movimientos (RF-26 y RF-32)."""

from dataclasses import replace
from uuid import UUID

from app.modules.finance.domain.errors import InvalidDateRange
from app.modules.finance.domain.models import TransactionCursor, TransactionFilters, TransactionPage
from app.modules.finance.domain.ports import TransactionHistoryReader


async def get_transactions(
    user_id: UUID,
    filters: TransactionFilters,
    after: TransactionCursor | None,
    limit: int,
    history: TransactionHistoryReader,
) -> TransactionPage:
    """Una página, del más reciente al más viejo.

    Pide uno de más: si llega, hay otra página, que empieza después del último
    que se devuelve.
    """
    if filters.from_date and filters.to_date and filters.from_date > filters.to_date:
        raise InvalidDateRange()
    search = " ".join(filters.search.split()) if filters.search else ""
    filters = replace(filters, search=search or None)
    rows = await history.page(user_id, filters, after, limit + 1)
    items = rows[:limit]
    if len(rows) <= limit:
        return TransactionPage(items=items, next_cursor=None)
    last = items[-1]
    return TransactionPage(items=items, next_cursor=TransactionCursor(occurred_on=last.occurred_on, id=last.id))
