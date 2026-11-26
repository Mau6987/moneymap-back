-- =============================================================================
-- MoneyMap · 070 · reports (lectura)
-- Money Flow (FTR-013), gasto en efectivo y con tarjeta, y Money Story
-- semanal y mensual (FTR-021, FTR-022).
--
-- Los totales se calculan al momento desde finance.transactions, para el rango
-- que pida la API (normalmente finance.current_period del usuario). No hay
-- tablas precalculadas que mantener al día: los índices por (user_id, fecha)
-- responden en milisegundos con cientos de miles de movimientos.
-- Todo va por moneda: nunca se suman bolivianos con dólares.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS reports;
COMMENT ON SCHEMA reports IS 'Totales por categoría, Money Flow, gasto por efectivo y tarjeta, y Money Story. Todo por moneda.';

-- Total por categoría en un rango de fechas (inclusive). Base del Money Flow y
-- del detalle de "¿dónde se fue mi dinero?".
CREATE OR REPLACE FUNCTION reports.category_totals(p_user uuid, p_from date, p_to date)
RETURNS TABLE (currency char(3), category_id uuid, category_name text, kind catalog.money_kind,
               flow_group catalog.flow_group, total numeric, tx_count bigint)
LANGUAGE sql STABLE AS $$
  SELECT t.currency, c.id, c.name, t.kind, c.flow_group, sum(t.amount), count(*)
  FROM finance.transactions t
  JOIN finance.categories c ON c.user_id = t.user_id AND c.id = t.category_id
  WHERE t.user_id = p_user
    AND t.occurred_on BETWEEN p_from AND p_to
    AND t.kind IN ('income', 'expense')
    AND t.deleted_at IS NULL
  GROUP BY t.currency, c.id, c.name, t.kind, c.flow_group
$$;
COMMENT ON FUNCTION reports.category_totals(uuid, date, date) IS
  'Cuánto entró o salió por categoría y moneda entre dos fechas. Sin transferencias ni borrados.';

-- Money Flow: una fila por nodo y moneda.
--   income           ingresos
--   needs, lifestyle cada grupo de gasto (catalog.flow_group)
--   goals            aportes a metas en esa moneda
--   available        ingresos − gastos − aportes
CREATE OR REPLACE FUNCTION reports.money_flow(p_user uuid, p_from date, p_to date)
RETURNS TABLE (currency char(3), node text, amount numeric)
LANGUAGE sql STABLE AS $$
  WITH cat AS (
    SELECT ct.currency, CASE WHEN ct.kind = 'income' THEN 'income' ELSE ct.flow_group::text END AS node, sum(ct.total) AS amount
    FROM reports.category_totals(p_user, p_from, p_to) ct
    GROUP BY 1, 2
  ), goal AS (
    SELECT g.currency, 'goals'::text AS node, sum(gc.amount) AS amount
    FROM goals.goal_contributions gc
    JOIN goals.goals g ON g.user_id = gc.user_id AND g.id = gc.goal_id
    WHERE gc.user_id = p_user AND gc.contributed_on BETWEEN p_from AND p_to
    GROUP BY 1
  ), nodes AS (
    SELECT * FROM cat UNION ALL SELECT * FROM goal
  )
  SELECT n.currency, n.node, n.amount FROM nodes n
  UNION ALL
  SELECT n.currency, 'available',
         sum(CASE WHEN n.node = 'income' THEN n.amount ELSE -n.amount END)
  FROM nodes n
  GROUP BY n.currency
$$;
COMMENT ON FUNCTION reports.money_flow(uuid, date, date) IS
  'Nodos del Money Flow por moneda: income, cada grupo de gasto, goals y available (ingresos − gastos − metas).';

-- ¿Cuánto gasté en efectivo y cuánto con tarjeta? Sale del tipo de cuenta.
CREATE OR REPLACE FUNCTION reports.payment_method_totals(p_user uuid, p_from date, p_to date)
RETURNS TABLE (currency char(3), kind catalog.money_kind, method text, total numeric, tx_count bigint)
LANGUAGE sql STABLE AS $$
  SELECT t.currency, t.kind, CASE WHEN at.is_card THEN 'card' ELSE 'cash' END, sum(t.amount), count(*)
  FROM finance.transactions t
  JOIN finance.accounts a ON a.user_id = t.user_id AND a.id = t.account_id
  JOIN catalog.account_types at ON at.code = a.type
  WHERE t.user_id = p_user
    AND t.occurred_on BETWEEN p_from AND p_to
    AND t.kind IN ('income', 'expense')
    AND t.deleted_at IS NULL
  GROUP BY 1, 2, 3
$$;
COMMENT ON FUNCTION reports.payment_method_totals(uuid, date, date) IS
  'Gastos e ingresos en efectivo (cash) y con tarjeta (card), por moneda, entre dos fechas.';

-- -----------------------------------------------------------------------------
-- Money Story: la "foto" que se genera al cerrar una semana (Weekly Check-in)
-- o un mes (Monthly Money Story), se notifica y queda en el historial.
-- -----------------------------------------------------------------------------
CREATE TABLE reports.money_stories (
  id               uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id          uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  period_type      text          NOT NULL CHECK (period_type IN ('week', 'month')),
  period_start     date          NOT NULL,
  period_end       date          NOT NULL,
  status           text          NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
  currency         char(3)       NOT NULL REFERENCES catalog.currencies (code),
  income_total     numeric(19,4),
  expense_total    numeric(19,4),
  savings_total    numeric(19,4),
  savings_rate     numeric(7,4),
  highlights       jsonb         NOT NULL DEFAULT '[]',   -- [{"key": "income_change", "params": {…}}]
  template_version text          NOT NULL,
  generated_at     timestamptz,
  viewed_at        timestamptz,
  created_at       timestamptz   NOT NULL DEFAULT now(),
  CONSTRAINT money_stories_period_uq  UNIQUE (user_id, period_type, period_start, currency),
  CONSTRAINT money_stories_period_chk CHECK (period_end >= period_start)
);
CREATE INDEX money_stories_user_idx ON reports.money_stories (user_id, period_start DESC);
COMMENT ON TABLE reports.money_stories IS
  'Resumen semanal (week) o mensual (month) por moneda con movimientos. Se guardan claves y parámetros, no texto, para traducir y cambiar plantillas sin regenerar.';
