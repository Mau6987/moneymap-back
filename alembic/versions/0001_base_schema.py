"""Esquema base de la V1: aplica db/migrations/*.sql en orden.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def upgrade() -> None:
    # Se usa la conexión de psycopg directamente, en la misma transacción: sin
    # parámetros acepta varias sentencias y no interpreta los %I ni los :nombre
    # de las funciones PL/pgSQL (SQLAlchemy sí lo haría).
    psycopg_conn = op.get_bind().connection.dbapi_connection
    assert psycopg_conn is not None
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        psycopg_conn.execute(sql_file.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("El esquema base no se revierte: se recrea la base de datos.")
