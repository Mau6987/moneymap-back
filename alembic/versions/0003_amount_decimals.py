"""Los decimales de la moneda en el saldo inicial y en los recurrentes (spec 007).

`finance.transactions` ya rechaza 1000.5 en CLP o PYG (`invalid_amount`), pero el
saldo inicial de una cuenta y el monto de un recurrente no: el onboarding los
crea los dos. Mismo error y mismo HINT que los movimientos.

Los triggers se llaman `…_check_amount` para correr después de
`…_before_write` (PostgreSQL los ordena por nombre), que es el que completa la
moneda del recurrente con la de su cuenta.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.assert_amount_decimals(p_amount numeric, p_currency char(3))
        RETURNS void
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
          v_decimals smallint;
        BEGIN
          SELECT c.decimals INTO v_decimals FROM catalog.currencies c WHERE c.code = p_currency;
          IF v_decimals IS NOT NULL AND p_amount <> round(p_amount, v_decimals) THEN
            RAISE EXCEPTION 'El monto % tiene más de % decimales para %', p_amount, v_decimals, p_currency
              USING ERRCODE = 'check_violation', HINT = 'invalid_amount';
          END IF;
        END $$
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION finance.assert_amount_decimals(numeric, char) IS
          'Rechaza un monto con más decimales que los de su moneda (1000.5 en CLP o PYG): HINT invalid_amount.'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.accounts_check_amount() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.opening_balance, NEW.currency);
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER accounts_check_amount BEFORE INSERT OR UPDATE OF opening_balance, currency
          ON finance.accounts FOR EACH ROW EXECUTE FUNCTION finance.accounts_check_amount()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finance.recurring_rules_check_amount() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM finance.assert_amount_decimals(NEW.amount, NEW.currency);
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER recurring_rules_check_amount BEFORE INSERT OR UPDATE OF amount, account_id, currency
          ON finance.recurring_rules FOR EACH ROW EXECUTE FUNCTION finance.recurring_rules_check_amount()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS recurring_rules_check_amount ON finance.recurring_rules")
    op.execute("DROP TRIGGER IF EXISTS accounts_check_amount ON finance.accounts")
    op.execute("DROP FUNCTION IF EXISTS finance.recurring_rules_check_amount()")
    op.execute("DROP FUNCTION IF EXISTS finance.accounts_check_amount()")
    op.execute("DROP FUNCTION IF EXISTS finance.assert_amount_decimals(numeric, char)")
