"""El SQL de `finance.accounts` y `finance.cards` (RF-3, RF-14, RF-23).

Los saldos, la cuenta por defecto, Mis monedas y los límites del plan los
mantienen triggers: aquí solo se inserta y se lee lo que quedó.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import AccountChanges, AccountRecord, NewAccount

# Los decimales de la moneda vienen del catálogo: el saldo se devuelve con los
# decimales que esa moneda acepta, no con los cuatro del numeric(19,4).
_INSERT_ACCOUNT = text(
    """
    WITH created AS (
        INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)
        VALUES (:user_id, :name, :type, :currency, :opening_balance)
        RETURNING id, name, type, currency, current_balance, is_default, created_at, archived_at
    )
    SELECT created.*, currencies.decimals
    FROM created
    JOIN catalog.currencies AS currencies ON currencies.code = created.currency
    """
)

_INSERT_CARD = text(
    """
    INSERT INTO finance.cards (user_id, account_id, institution_code, last4)
    VALUES (:user_id, :account_id, :institution_code, :last4)
    """
)

# COALESCE para corregir solo lo que se envía. La moneda en el SET hace que el
# trigger corra y valide: moneda activa, cuenta sin usar y límites del plan. Un
# saldo inicial nuevo mueve el saldo actual por la diferencia
# (finance.sync_opening_balance) y se valida con los decimales de la moneda.
_UPDATE_ACCOUNT = text(
    """
    WITH updated AS (
        UPDATE finance.accounts
        SET name = coalesce(:name, name),
            currency = coalesce(:currency, currency),
            opening_balance = coalesce(CAST(:opening_balance AS numeric), opening_balance),
            archived_at = CASE CAST(:archived AS boolean)
                WHEN true THEN coalesce(archived_at, now())
                WHEN false THEN NULL
                ELSE archived_at
            END
        WHERE user_id = :user_id AND id = :account_id AND deleted_at IS NULL
        RETURNING id, name, type, currency, current_balance, is_default, created_at, archived_at
    )
    SELECT updated.*, currencies.decimals
    FROM updated
    JOIN catalog.currencies AS currencies ON currencies.code = updated.currency
    """
)

# Las activas o, con :archived, solo las archivadas.
_SELECT_ACCOUNTS = text(
    """
    SELECT accounts.id, accounts.name, accounts.type, accounts.currency, accounts.current_balance,
           accounts.is_default, accounts.created_at, accounts.archived_at, currencies.decimals,
           cards.institution_code, cards.last4
    FROM finance.accounts AS accounts
    JOIN catalog.currencies AS currencies ON currencies.code = accounts.currency
    LEFT JOIN finance.cards AS cards ON cards.user_id = accounts.user_id AND cards.account_id = accounts.id
    WHERE accounts.user_id = :user_id AND accounts.deleted_at IS NULL
      AND (accounts.archived_at IS NOT NULL) = :archived
    ORDER BY accounts.is_default DESC, accounts.sort_order, accounts.created_at, accounts.id
    """
)


class SqlAccountRepository:
    """Implementa `AccountRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UUID, archived: bool) -> list[AccountRecord]:
        params = {"user_id": user_id, "archived": archived}
        rows = (await self._session.execute(_SELECT_ACCOUNTS, params)).mappings().all()
        return [_to_account_record(row) for row in rows]

    async def insert(self, user_id: UUID, account: NewAccount) -> AccountRecord:
        row = (
            (
                await self._session.execute(
                    _INSERT_ACCOUNT,
                    {
                        "user_id": user_id,
                        "name": account.name,
                        "type": account.type,
                        "currency": account.currency,
                        "opening_balance": account.opening_balance,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_account_record(row)

    async def append_card(
        self,
        user_id: UUID,
        account_id: UUID,
        institution_code: str | None,
        last4: str | None,
    ) -> None:
        await self._session.execute(
            _INSERT_CARD,
            {
                "user_id": user_id,
                "account_id": account_id,
                "institution_code": institution_code,
                "last4": last4,
            },
        )

    async def update(self, user_id: UUID, account_id: UUID, changes: AccountChanges) -> AccountRecord | None:
        row = (
            (
                await self._session.execute(
                    _UPDATE_ACCOUNT,
                    {
                        "user_id": user_id,
                        "account_id": account_id,
                        "name": changes.name,
                        "currency": changes.currency,
                        "archived": changes.archived,
                        "opening_balance": changes.opening_balance,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _to_account_record(row)


def _to_account_record(row: RowMapping) -> AccountRecord:
    currency: str = row["currency"]
    return AccountRecord(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        currency=currency,
        current_balance=Money(row["current_balance"], currency, row["decimals"]),
        is_default=row["is_default"],
        created_at=row["created_at"],
        archived_at=row["archived_at"],
        institution_code=row.get("institution_code"),
        last4=row.get("last4"),
    )
