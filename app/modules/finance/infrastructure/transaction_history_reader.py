"""El SQL del historial de movimientos (RF-26 y RF-32).

Pagina por cursor sobre `(occurred_on, id)`, el mismo orden de
`transactions_feed_idx`: cada página cuesta lo mismo aunque el historial sea
largo, cosa que un OFFSET no logra.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import TransactionCursor, TransactionFilters, TransactionItem

# Con cuenta, entran también las transferencias que llegan a ella. La búsqueda
# usa transactions_search_idx (trigramas sobre lower(description)); los comodines
# del texto se escapan con \ (el escape por defecto de LIKE): "50%" busca "50%".
_SELECT_PAGE = text(
    """
    SELECT transactions.id, transactions.kind, transactions.account_id, transactions.category_id,
           transactions.transfer_account_id, transactions.amount, transactions.currency,
           transactions.occurred_on, transactions.description, transactions.source,
           transactions.created_at, currencies.decimals,
           EXISTS (SELECT 1 FROM finance.transaction_receipts AS receipts
                   WHERE receipts.user_id = transactions.user_id AND receipts.transaction_id = transactions.id)
             AS has_receipt
    FROM finance.transactions AS transactions
    JOIN catalog.currencies AS currencies ON currencies.code = transactions.currency
    WHERE transactions.user_id = :user_id
      AND transactions.deleted_at IS NULL
      AND (CAST(:account_id AS uuid) IS NULL
           OR transactions.account_id = CAST(:account_id AS uuid)
           OR transactions.transfer_account_id = CAST(:account_id AS uuid))
      AND (CAST(:category_id AS uuid) IS NULL OR transactions.category_id = CAST(:category_id AS uuid))
      AND (CAST(:currency AS text) IS NULL OR transactions.currency = CAST(:currency AS text))
      AND (CAST(:from_date AS date) IS NULL OR transactions.occurred_on >= CAST(:from_date AS date))
      AND (CAST(:to_date AS date) IS NULL OR transactions.occurred_on <= CAST(:to_date AS date))
      AND (CAST(:pattern AS text) IS NULL OR lower(transactions.description) LIKE CAST(:pattern AS text))
      AND (CAST(:after_date AS date) IS NULL
           OR (transactions.occurred_on, transactions.id) < (CAST(:after_date AS date), CAST(:after_id AS uuid)))
    ORDER BY transactions.occurred_on DESC, transactions.id DESC
    LIMIT :limit
    """
)


class SqlTransactionHistoryReader:
    """Implementa `TransactionHistoryReader` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(
        self,
        user_id: UUID,
        filters: TransactionFilters,
        after: TransactionCursor | None,
        limit: int,
    ) -> Sequence[TransactionItem]:
        params = {
            "user_id": user_id,
            "account_id": filters.account_id,
            "category_id": filters.category_id,
            "currency": filters.currency,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "pattern": None if filters.search is None else f"%{_escape_like(filters.search.lower())}%",
            "after_date": None if after is None else after.occurred_on,
            "after_id": None if after is None else after.id,
            "limit": limit,
        }
        rows = (await self._session.execute(_SELECT_PAGE, params)).mappings().all()
        return [to_transaction_item(row) for row in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_transaction_item(row: Mapping[Any, Any]) -> TransactionItem:
    return TransactionItem(
        id=row["id"],
        kind=row["kind"],
        account_id=row["account_id"],
        category_id=row["category_id"],
        transfer_account_id=row["transfer_account_id"],
        amount=Money(row["amount"], row["currency"], row["decimals"]),
        occurred_on=row["occurred_on"],
        description=row["description"],
        source=row["source"],
        created_at=row["created_at"],
        has_receipt=bool(row.get("has_receipt")),
    )
