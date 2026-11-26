"""Las veces de un recurrente desde `next_due_on` hasta una fecha (spec 003, RF-11 y RF-23).

Safe to Spend las suma y la lista de recurrentes las muestra: una sola función
para que Cuentas por pagar y la lista no puedan dar distinto. Cada fecha sale de
`start_date`, con la misma fórmula que `finance.next_occurrence`: un fijo del 31
vuelve al 31 después de febrero. Siempre incluye `p_next_due`, aunque pase de
`p_until`. `first` y `last` acotan las repeticiones.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OCCURRENCES = """
CREATE FUNCTION finance.recurring_occurrences(
  p_start date, p_frequency finance.frequency, p_next_due date, p_until date
)
RETURNS SETOF date
LANGUAGE sql IMMUTABLE AS $$
  SELECT p_next_due
  UNION
  SELECT (p_start + n * steps.step)::date
  FROM (
    SELECT CASE p_frequency
             WHEN 'weekly' THEN interval '1 week'
             WHEN 'biweekly' THEN interval '2 weeks'
             WHEN 'yearly' THEN interval '1 year'
             ELSE interval '1 month'
           END AS step,
           CASE p_frequency
             WHEN 'weekly' THEN (p_next_due - p_start) / 7
             WHEN 'biweekly' THEN (p_next_due - p_start) / 14
             WHEN 'yearly' THEN extract(year FROM age(p_next_due, p_start))::int
             ELSE (extract(year FROM age(p_next_due, p_start)) * 12
                   + extract(month FROM age(p_next_due, p_start)))::int
           END AS first,
           CASE p_frequency
             WHEN 'weekly' THEN (p_until - p_start) / 7
             WHEN 'biweekly' THEN (p_until - p_start) / 14
             WHEN 'yearly' THEN extract(year FROM age(p_until, p_start))::int
             ELSE (extract(year FROM age(p_until, p_start)) * 12
                   + extract(month FROM age(p_until, p_start)))::int
           END + 1 AS last
  ) AS steps
  CROSS JOIN LATERAL generate_series(greatest(steps.first, 0), steps.last) AS n
  WHERE (p_start + n * steps.step)::date > p_next_due
    AND (p_start + n * steps.step)::date <= p_until
$$;
"""

_COMMENT = """
COMMENT ON FUNCTION finance.recurring_occurrences(date, finance.frequency, date, date) IS
  'Las veces de un recurrente desde next_due_on hasta una fecha. Las usan Safe to Spend y la lista de recurrentes.';
"""


def upgrade() -> None:
    op.execute(_OCCURRENCES)
    op.execute(_COMMENT)


def downgrade() -> None:
    op.execute("DROP FUNCTION finance.recurring_occurrences(date, finance.frequency, date, date)")
