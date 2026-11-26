"""Quita el teléfono del perfil: no se usa para nada (2026-10-22).

Se van la columna `phone_e164`, su CHECK (cae con la columna) y la línea que lo
limpiaba en `iam.users_before_write()`, que se vuelve a crear sin ella.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITHOUT_PHONE = r"""CREATE OR REPLACE FUNCTION iam.users_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.email        := btrim(NEW.email);
  NEW.first_name   := nullif(regexp_replace(btrim(NEW.first_name), '\s+', ' ', 'g'), '');
  NEW.last_name    := nullif(regexp_replace(btrim(NEW.last_name), '\s+', ' ', 'g'), '');
  NEW.display_name := coalesce(nullif(regexp_replace(btrim(NEW.display_name), '\s+', ' ', 'g'), ''), NEW.first_name);
  NEW.country_code := upper(nullif(btrim(NEW.country_code), ''));
  NEW.city         := nullif(btrim(NEW.city), '');
  IF TG_OP = 'INSERT' AND NOT EXISTS (
    SELECT 1 FROM iam.terms_versions WHERE version = NEW.terms_version AND is_current
  ) THEN
    RAISE EXCEPTION 'Debes aceptar la versión vigente de los términos (%)',
      (SELECT version FROM iam.terms_versions WHERE is_current)
      USING ERRCODE = 'check_violation', HINT = 'terms_outdated';
  END IF;
  RETURN NEW;
END $$"""

_WITH_PHONE = r"""CREATE OR REPLACE FUNCTION iam.users_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.email        := btrim(NEW.email);
  NEW.first_name   := nullif(regexp_replace(btrim(NEW.first_name), '\s+', ' ', 'g'), '');
  NEW.last_name    := nullif(regexp_replace(btrim(NEW.last_name), '\s+', ' ', 'g'), '');
  NEW.display_name := coalesce(nullif(regexp_replace(btrim(NEW.display_name), '\s+', ' ', 'g'), ''), NEW.first_name);
  NEW.phone_e164   := nullif(regexp_replace(NEW.phone_e164, '[\s().-]', '', 'g'), '');
  NEW.country_code := upper(nullif(btrim(NEW.country_code), ''));
  NEW.city         := nullif(btrim(NEW.city), '');
  IF TG_OP = 'INSERT' AND NOT EXISTS (
    SELECT 1 FROM iam.terms_versions WHERE version = NEW.terms_version AND is_current
  ) THEN
    RAISE EXCEPTION 'Debes aceptar la versión vigente de los términos (%)',
      (SELECT version FROM iam.terms_versions WHERE is_current)
      USING ERRCODE = 'check_violation', HINT = 'terms_outdated';
  END IF;
  RETURN NEW;
END $$"""


def upgrade() -> None:
    op.execute(_WITHOUT_PHONE)
    op.execute("ALTER TABLE iam.users DROP COLUMN phone_e164")


def downgrade() -> None:
    # Vuelve la columna vacía: los teléfonos se perdieron al quitarla.
    op.execute(r"ALTER TABLE iam.users ADD COLUMN phone_e164 text CHECK (phone_e164 ~ '^\+[1-9][0-9]{6,14}$')")
    op.execute(
        "COMMENT ON COLUMN iam.users.phone_e164 IS"
        " 'Teléfono en formato E.164. La migración 0013 lo quita y este downgrade lo repone vacío.'"
    )
    op.execute(_WITH_PHONE)
