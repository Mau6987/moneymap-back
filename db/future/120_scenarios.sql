-- =============================================================================
-- MoneyMap · 120 · escenarios What If? (FTR-011)
-- Guarda los cambios hipotéticos y el resultado calculado para comparar
-- "Mapa actual" contra "Mapa del escenario".
-- =============================================================================

CREATE TABLE planning.scenarios (
  id                uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id           uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  name              text        NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  changes           jsonb       NOT NULL,     -- [{"type": "category_delta", "category_id": "…", "monthly": -100}]
  result            jsonb,                    -- ahorro mensual nuevo, metas adelantadas o atrasadas…
  algorithm_version text,
  is_pinned         boolean     NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  deleted_at        timestamptz
);
CREATE INDEX scenarios_user_idx ON planning.scenarios (user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE TRIGGER scenarios_set_updated_at BEFORE UPDATE ON planning.scenarios
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

ALTER TABLE planning.scenarios ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows   ON planning.scenarios FOR ALL TO moneymap_app
  USING (user_id = (SELECT core.current_user_id())) WITH CHECK (user_id = (SELECT core.current_user_id()));
CREATE POLICY worker_all   ON planning.scenarios FOR ALL TO moneymap_worker USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON planning.scenarios TO moneymap_app, moneymap_worker;
