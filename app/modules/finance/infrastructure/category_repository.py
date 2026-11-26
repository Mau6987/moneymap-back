"""El SQL de `finance.categories` (spec 007, RF-6 a RF-13).

Las categorías iniciales las copia `finance.setup_user` en el paso 1; aquí se
leen, se crean, se corrigen y se borran las del usuario, que la RLS ya filtra.
El nombre repetido y el grupo del Money Flow los valida la base.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.domain.models import CategoryChanges, CategoryRecord, NewCategory

# CAST en :type: sin filtro llega NULL y asyncpg necesita saber su tipo.
_SELECT_CATEGORIES = text(
    """
    SELECT id, name, kind::text AS type, flow_group::text AS flow_group, icon, color, template_key
    FROM finance.categories
    WHERE user_id = :user_id
      AND deleted_at IS NULL
      AND (CAST(:type AS text) IS NULL OR kind::text = CAST(:type AS text))
    ORDER BY kind, flow_group, sort_order, name
    """
)

_INSERT_CATEGORY = text(
    """
    INSERT INTO finance.categories (user_id, kind, flow_group, name, icon, color)
    VALUES (:user_id, CAST(:type AS catalog.money_kind), CAST(:flow_group AS catalog.flow_group),
            :name, :icon, :color)
    RETURNING id, name, kind::text AS type, flow_group::text AS flow_group, icon, color, template_key
    """
)

# RF-11: la FK de finance.transactions ya impide el cambio si hay movimientos
# (aun borrados); los recurrentes no la tienen y toman su tipo de la categoría.
_TYPE_IN_USE = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM finance.categories AS categories
        WHERE categories.user_id = :user_id
          AND categories.id = :category_id
          AND categories.deleted_at IS NULL
          AND categories.kind::text <> CAST(:type AS text)
          AND (
              EXISTS (
                  SELECT 1 FROM finance.transactions AS transactions
                  WHERE transactions.user_id = :user_id AND transactions.category_id = :category_id
              )
              OR EXISTS (
                  SELECT 1 FROM finance.recurring_rules AS rules
                  WHERE rules.user_id = :user_id AND rules.category_id = :category_id
                    AND rules.deleted_at IS NULL
              )
          )
    )
    """
)

# COALESCE para corregir solo lo que se envía. Al pasar a ingreso se quita el
# grupo; al pasar a gasto sin grupo, la base responde categories_flow_chk.
_UPDATE_CATEGORY = text(
    """
    UPDATE finance.categories
    SET name = coalesce(:name, name),
        kind = coalesce(CAST(CAST(:type AS text) AS catalog.money_kind), kind),
        flow_group = CASE
            WHEN CAST(:type AS text) = 'income' THEN NULL
            ELSE coalesce(CAST(:flow_group AS catalog.flow_group), flow_group)
        END,
        icon = coalesce(:icon, icon),
        color = coalesce(:color, color)
    WHERE user_id = :user_id AND id = :category_id AND deleted_at IS NULL
    RETURNING id, name, kind::text AS type, flow_group::text AS flow_group, icon, color, template_key
    """
)

# RF-12: borrado lógico. Los movimientos la siguen apuntando y los reportes la
# muestran como `sin_categoria`.
_SOFT_DELETE_CATEGORY = text(
    """
    UPDATE finance.categories
    SET deleted_at = now()
    WHERE user_id = :user_id AND id = :category_id AND deleted_at IS NULL
    RETURNING id
    """
)

# RF-13: sin mayúsculas ni tildes, y salteando las categorías borradas. `translate` y no `unaccent`, que no está
# instalada. ponytail: recorre los movimientos del usuario; con historiales
# grandes, un índice por esa expresión.
_PLAIN_FROM = "áàâäãéèêëíìîïóòôöõúùûüñç"
_PLAIN_TO = "aaaaaeeeeiiiiooooouuuunc"
_LAST_USED_FOR = text(
    """
    SELECT categories.id, categories.name, categories.kind::text AS type,
           categories.flow_group::text AS flow_group, categories.icon, categories.color, categories.template_key
    FROM finance.transactions AS transactions
    JOIN finance.categories AS categories
      ON categories.user_id = transactions.user_id AND categories.id = transactions.category_id
     AND categories.deleted_at IS NULL
    WHERE transactions.user_id = :user_id
      AND transactions.deleted_at IS NULL
      AND transactions.kind::text = :type
      AND translate(lower(transactions.description), :plain_from, :plain_to)
          = translate(lower(:description), :plain_from, :plain_to)
    ORDER BY transactions.occurred_on DESC, transactions.created_at DESC
    LIMIT 1
    """
)


class SqlCategoryRepository:
    """Implementa `CategoryRepository` sobre la sesión del usuario (con RLS)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UUID, category_type: str | None) -> list[CategoryRecord]:
        rows = (
            (await self._session.execute(_SELECT_CATEGORIES, {"user_id": user_id, "type": category_type}))
            .mappings()
            .all()
        )
        return [_to_category(row) for row in rows]

    async def insert(self, user_id: UUID, category: NewCategory) -> CategoryRecord:
        row = (
            (
                await self._session.execute(
                    _INSERT_CATEGORY,
                    {
                        "user_id": user_id,
                        "type": category.type,
                        "flow_group": category.flow_group,
                        "name": category.name,
                        "icon": category.icon,
                        "color": category.color,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_category(row)

    async def type_in_use(self, user_id: UUID, category_id: UUID, category_type: str) -> bool:
        params = {"user_id": user_id, "category_id": category_id, "type": category_type}
        return bool((await self._session.execute(_TYPE_IN_USE, params)).scalar_one())

    async def update(self, user_id: UUID, category_id: UUID, changes: CategoryChanges) -> CategoryRecord | None:
        row = (
            (
                await self._session.execute(
                    _UPDATE_CATEGORY,
                    {
                        "user_id": user_id,
                        "category_id": category_id,
                        "name": changes.name,
                        "type": changes.type,
                        "flow_group": changes.flow_group,
                        "icon": changes.icon,
                        "color": changes.color,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_category(row)

    async def soft_delete(self, user_id: UUID, category_id: UUID) -> bool:
        params = {"user_id": user_id, "category_id": category_id}
        return (await self._session.execute(_SOFT_DELETE_CATEGORY, params)).first() is not None

    async def last_used_for(self, user_id: UUID, description: str, category_type: str) -> CategoryRecord | None:
        params = {
            "user_id": user_id,
            "description": description,
            "type": category_type,
            "plain_from": _PLAIN_FROM,
            "plain_to": _PLAIN_TO,
        }
        row = (await self._session.execute(_LAST_USED_FOR, params)).mappings().first()
        return None if row is None else _to_category(row)


def _to_category(row: RowMapping) -> CategoryRecord:
    return CategoryRecord(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        flow_group=row["flow_group"],
        icon=row["icon"],
        color=row["color"],
        template_key=row["template_key"],
    )
