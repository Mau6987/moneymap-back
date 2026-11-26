"""El SQL de `iam.user_preferences` (spec 001, RF-15 y RF-16).

La fila la crea `iam.users_create_preferences` al registrarse; aquí solo se lee
y se cambia. Los valores válidos los aplican los CHECK de la tabla.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.domain.models import Preferences, PreferencesChanges

_SELECT_PREFERENCES = text(
    """
    SELECT theme, accent_color, hide_amounts, week_starts_on
    FROM iam.user_preferences
    WHERE user_id = :user_id
    """
)

# accent_color con su bandera: en null vuelve al color de la marca.
_UPDATE_PREFERENCES = text(
    """
    UPDATE iam.user_preferences
    SET theme = coalesce(CAST(:theme AS text), theme),
        accent_color = CASE WHEN :set_accent_color THEN CAST(:accent_color AS text) ELSE accent_color END,
        hide_amounts = coalesce(CAST(:hide_amounts AS boolean), hide_amounts),
        week_starts_on = coalesce(CAST(:week_starts_on AS smallint), week_starts_on)
    WHERE user_id = :user_id
    RETURNING theme, accent_color, hide_amounts, week_starts_on
    """
)


class SqlPreferencesRepository:
    """Implementa `PreferencesRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> Preferences | None:
        row = (await self._session.execute(_SELECT_PREFERENCES, {"user_id": user_id})).mappings().one_or_none()
        return None if row is None else _to_preferences(row)

    async def update(self, user_id: UUID, changes: PreferencesChanges) -> Preferences | None:
        params = {
            "user_id": user_id,
            "theme": changes.theme,
            "accent_color": changes.accent_color,
            "set_accent_color": "accent_color" in changes.sent,
            "hide_amounts": changes.hide_amounts,
            "week_starts_on": changes.week_starts_on,
        }
        row = (await self._session.execute(_UPDATE_PREFERENCES, params)).mappings().one_or_none()
        return None if row is None else _to_preferences(row)


def _to_preferences(row: RowMapping) -> Preferences:
    return Preferences(
        theme=row["theme"],
        accent_color=row["accent_color"],
        hide_amounts=row["hide_amounts"],
        week_starts_on=row["week_starts_on"],
    )
