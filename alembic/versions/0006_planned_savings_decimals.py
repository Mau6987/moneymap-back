"""Los decimales de la moneda en el ahorro planificado (spec 003, RF-8).

`planned_savings` es por periodo y en la moneda principal. El CHECK de la tabla
ya rechaza un negativo, pero no un 1000.5 en CLP o PYG. Mismo error y mismo HINT
(`invalid_amount`) que los movimientos, el saldo inicial y los recurrentes
(migración 0003).

Solo se valida al escribir `planned_savings`: si después la persona cambia la
moneda principal a una sin decimales, el monto no se reescribe ni se convierte
(constitución §2). Qué hacer en ese caso es una duda abierta de la spec 003.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.user_settings_check_amount() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.planned_savings, NEW.main_currency);
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_settings_check_amount BEFORE INSERT OR UPDATE OF planned_savings
          ON finance.user_settings
          FOR EACH ROW EXECUTE FUNCTION finance.user_settings_check_amount()
        """
    )
    op.execute(
        "COMMENT ON FUNCTION finance.user_settings_check_amount() IS"
        " 'Rechaza un ahorro planificado con más decimales que los de la moneda principal (invalid_amount).'"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER user_settings_check_amount ON finance.user_settings")
    op.execute("DROP FUNCTION finance.user_settings_check_amount()")
