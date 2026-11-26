"""El SQL de `finance.user_settings` (RF-1; spec 003, RF-7 a RF-9).

`finance.setup_user` crea la fila y siembra las categorías iniciales la primera
vez, y es idempotente. Después el UPDATE solo cambia la moneda principal, que es
lo que la base valida contra el catálogo.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.finance.domain.models import SettingsChanges, UserSettings

# Crea la configuración y las categorías iniciales si todavía no están.
_SETUP_USER = text("SELECT finance.setup_user(:user_id, :main_currency)")

# Cambiar la moneda principal no convierte ningún monto (constitución §2).
# El trigger valida que la moneda exista y esté activa, y la suma a Mis monedas.
_UPDATE_MAIN_CURRENCY = text(
    """
    UPDATE finance.user_settings
    SET main_currency = :main_currency
    WHERE user_id = :user_id AND main_currency <> :main_currency
    """
)

# El periodo y el ahorro: el CHECK del día de inicio, el de ahorro no negativo y
# el trigger de los decimales (migración 0006) los aplica la base.
_UPDATE_PERIOD_AND_SAVINGS = text(
    """
    UPDATE finance.user_settings
    SET period_type = coalesce(CAST(:period_type AS finance.period_type), period_type),
        period_start_day = coalesce(CAST(:period_start_day AS smallint), period_start_day),
        planned_savings = coalesce(CAST(:planned_savings AS numeric), planned_savings)
    WHERE user_id = :user_id
    RETURNING user_id
    """
)

_SELECT_SETTINGS = text(
    """
    SELECT settings.main_currency,
           settings.period_type::text AS period_type,
           settings.period_start_day,
           settings.planned_savings,
           currencies.decimals
    FROM finance.user_settings AS settings
    JOIN catalog.currencies AS currencies ON currencies.code = settings.main_currency
    WHERE settings.user_id = :user_id
    """
)


class SqlSettingsRepository:
    """Implementa `SettingsRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> UserSettings | None:
        row = (await self._session.execute(_SELECT_SETTINGS, {"user_id": user_id})).mappings().one_or_none()
        return None if row is None else _to_user_settings(row)

    async def save_main_currency(self, user_id: UUID, main_currency: str) -> UserSettings:
        parameters = {"user_id": user_id, "main_currency": main_currency}
        await self._session.execute(_SETUP_USER, parameters)
        await self._session.execute(_UPDATE_MAIN_CURRENCY, parameters)
        return await self._read(user_id)

    async def update(self, user_id: UUID, changes: SettingsChanges) -> UserSettings | None:
        params = {
            "user_id": user_id,
            "period_type": changes.period_type,
            "period_start_day": changes.period_start_day,
            "planned_savings": changes.planned_savings,
        }
        if (await self._session.execute(_UPDATE_PERIOD_AND_SAVINGS, params)).scalar_one_or_none() is None:
            return None
        return await self._read(user_id)

    async def _read(self, user_id: UUID) -> UserSettings:
        row = (await self._session.execute(_SELECT_SETTINGS, {"user_id": user_id})).mappings().one()
        return _to_user_settings(row)


def _to_user_settings(row: RowMapping) -> UserSettings:
    currency: str = row["main_currency"]
    return UserSettings(
        main_currency=currency,
        period_type=row["period_type"],
        period_start_day=row["period_start_day"],
        planned_savings=Money(row["planned_savings"], currency, row["decimals"]),
    )
