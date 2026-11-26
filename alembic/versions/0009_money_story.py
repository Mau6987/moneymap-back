"""La comparación y las plantillas de la Money Story (spec 006, RF-2 a RF-4).

- `reports.money_stories.comparison`: lo del mes anterior en la misma moneda
  (ingresos, gastos, ahorro, mayor categoría de gasto y aportes a metas). En
  null si ese mes no tuvo movimientos en la moneda (RF-3).
- `catalog.story_templates`: el texto de cada frase destacada, por versión. La
  historia guarda claves y parámetros; la API arma el texto con esta tabla, así
  que cambiar una frase es un UPDATE y no regenera nada (RF-4).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Los montos llegan con su símbolo y los meses con su nombre (app/modules/reports/domain/money_story.py).
_TEMPLATES = [
    ("summary", "En {month} entraron {income} y salieron {expense}."),
    ("saved", "Ahorraste {savings}: el {rate} % de lo que entró."),
    ("overspent", "Saliste {deficit} por encima de lo que entró."),
    ("balanced", "Lo que entró y lo que salió quedaron iguales."),
    ("top_expense_category", "Tu mayor gasto fue {category}: {amount}."),
    ("goals_contributed", "Aportaste {amount} a tus metas."),
    ("income_up", "Entró {difference} más que en {previous_month}."),
    ("income_down", "Entró {difference} menos que en {previous_month}."),
    ("income_same", "Entró lo mismo que en {previous_month}."),
    ("savings_up", "Ahorraste {difference} más que en {previous_month}."),
    ("savings_down", "Ahorraste {difference} menos que en {previous_month}."),
    ("savings_same", "Ahorraste lo mismo que en {previous_month}."),
    ("first_month", "Es tu primer mes con movimientos en esta moneda: desde el próximo verás cómo cambió."),
]


def upgrade() -> None:
    op.execute("ALTER TABLE reports.money_stories ADD COLUMN comparison jsonb")
    op.execute(
        "COMMENT ON COLUMN reports.money_stories.comparison IS"
        " 'El mes anterior en la misma moneda: ingresos, gastos, ahorro, mayor categoría de gasto"
        " y aportes a metas. Null si ese mes no tuvo movimientos en la moneda'"
    )
    op.execute(
        """
        CREATE TABLE catalog.story_templates (
          template_version text NOT NULL,
          key              text NOT NULL,
          body             text NOT NULL,
          PRIMARY KEY (template_version, key)
        )
        """
    )
    op.execute("GRANT SELECT ON catalog.story_templates TO moneymap_app, moneymap_worker")
    op.execute(
        "COMMENT ON TABLE catalog.story_templates IS"
        " 'Texto de cada frase de la Money Story por versión; {nombre} es un parámetro de la frase'"
    )
    templates = sa.table(
        "story_templates", sa.column("template_version"), sa.column("key"), sa.column("body"), schema="catalog"
    )
    op.bulk_insert(templates, [{"template_version": "1", "key": key, "body": body} for key, body in _TEMPLATES])


def downgrade() -> None:
    op.execute("DROP TABLE catalog.story_templates")
    op.execute("ALTER TABLE reports.money_stories DROP COLUMN comparison")
