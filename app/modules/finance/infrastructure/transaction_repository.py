"""El SQL de `finance.transactions` (RF-6 a RF-8, RF-10 a RF-13, RF-27).

Los saldos son de los triggers, y se leen después del INSERT o del UPDATE: los
triggers `AFTER` corren al cerrar la sentencia, así que una consulta dentro de la
misma sentencia (un CTE) todavía vería el saldo viejo.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import NewTransaction, TransactionChanges, TransactionRecord

# La moneda puede venir vacía: el trigger la completa con la de la cuenta y
# valida que no sea otra (RF-7). Los decimales del monto y el destino de la
# transferencia también los valida él (RF-8, RF-11, RF-12).
_INSERT = text(
    """
    INSERT INTO finance.transactions
        (user_id, kind, account_id, category_id, amount, currency, transfer_account_id,
         occurred_on, description, source)
    VALUES
        (:user_id, :kind, :account_id, :category_id, :amount, :currency, :transfer_account_id,
         :occurred_on, :description, :source)
    RETURNING id, kind, account_id, category_id, transfer_account_id, amount, currency,
              occurred_on, description, source, created_at
    """
)

_UPDATE = text(
    """
    UPDATE finance.transactions
    SET account_id = coalesce(:account_id, account_id),
        category_id = coalesce(:category_id, category_id),
        transfer_account_id = coalesce(:transfer_account_id, transfer_account_id),
        amount = coalesce(:amount, amount),
        occurred_on = coalesce(:occurred_on, occurred_on),
        description = coalesce(:description, description)
    WHERE user_id = :user_id AND id = :transaction_id AND deleted_at IS NULL
    RETURNING id, kind, account_id, category_id, transfer_account_id, amount, currency,
              occurred_on, description, source, created_at
    """
)

# Borrado lógico: el trigger de saldos devuelve el monto a las cuentas.
_SOFT_DELETE = text(
    """
    UPDATE finance.transactions
    SET deleted_at = now()
    WHERE user_id = :user_id AND id = :transaction_id AND deleted_at IS NULL
    RETURNING id
    """
)

# El saldo lo lee después, ya con los triggers aplicados.
_SELECT_BALANCES = text(
    """
    SELECT origin.current_balance AS account_balance,
           destination.current_balance AS transfer_account_balance,
           currencies.decimals
    FROM finance.accounts AS origin
    LEFT JOIN finance.accounts AS destination
           ON destination.user_id = origin.user_id AND destination.id = :transfer_account_id
    JOIN catalog.currencies AS currencies ON currencies.code = origin.currency
    WHERE origin.user_id = :user_id AND origin.id = :account_id
    """
)


class SqlTransactionRepository:
    """Implementa `TransactionRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, transaction: NewTransaction, user_id: UUID) -> TransactionRecord:
        row = (
            (
                await self._session.execute(
                    _INSERT,
                    {
                        "user_id": user_id,
                        "kind": transaction.kind,
                        "account_id": transaction.account_id,
                        "category_id": transaction.category_id,
                        "transfer_account_id": transaction.transfer_account_id,
                        "amount": transaction.amount,
                        "currency": transaction.currency,
                        "occurred_on": transaction.occurred_on,
                        "description": transaction.description,
                        "source": transaction.source,
                    },
                )
            )
            .mappings()
            .one()
        )
        return await self._with_balances(row, user_id)

    async def update(
        self,
        transaction_id: UUID,
        user_id: UUID,
        changes: TransactionChanges,
    ) -> TransactionRecord | None:
        row = (
            (
                await self._session.execute(
                    _UPDATE,
                    {
                        "user_id": user_id,
                        "transaction_id": transaction_id,
                        "account_id": changes.account_id,
                        "category_id": changes.category_id,
                        "transfer_account_id": changes.transfer_account_id,
                        "amount": changes.amount,
                        "occurred_on": changes.occurred_on,
                        "description": changes.description,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return await self._with_balances(row, user_id)

    async def soft_delete(self, transaction_id: UUID, user_id: UUID) -> bool:
        params = {"user_id": user_id, "transaction_id": transaction_id}
        return (await self._session.execute(_SOFT_DELETE, params)).scalar_one_or_none() is not None

    async def _with_balances(self, row: RowMapping, user_id: UUID) -> TransactionRecord:
        balances = (
            (
                await self._session.execute(
                    _SELECT_BALANCES,
                    {
                        "user_id": user_id,
                        "account_id": row["account_id"],
                        "transfer_account_id": row["transfer_account_id"],
                    },
                )
            )
            .mappings()
            .one()
        )
        currency: str = row["currency"]
        decimals: int = balances["decimals"]
        destination = balances["transfer_account_balance"]
        return TransactionRecord(
            id=row["id"],
            kind=row["kind"],
            account_id=row["account_id"],
            category_id=row["category_id"],
            transfer_account_id=row["transfer_account_id"],
            amount=Money(row["amount"], currency, decimals),
            occurred_on=row["occurred_on"],
            description=row["description"],
            source=row["source"],
            created_at=row["created_at"],
            account_balance=Money(balances["account_balance"], currency, decimals),
            transfer_account_balance=None if destination is None else Money(destination, currency, decimals),
        )
