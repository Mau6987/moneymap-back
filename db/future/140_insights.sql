-- =============================================================================
-- MoneyMap · 140 · insights y fugas de dinero (FTR-016, FTR-017, FTR-021)
-- Cada insight se guarda como clave + parámetros (traducible) con su estado,
-- para no repetir lo que el usuario ya descartó.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS insights;
COMMENT ON SCHEMA insights IS 'Observaciones generadas sobre los hábitos del usuario.';
GRANT USAGE ON SCHEMA insights TO moneymap_app, moneymap_worker;

CREATE TABLE insights.insights (
  id           uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id      uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  type         text        NOT NULL CHECK (type IN ('category_increase', 'subscription_total', 'small_recurring',
                                                     'spending_pace', 'saving_trend', 'weekly_checkin')),
  period_start date        NOT NULL,
  period_end   date        NOT NULL,
  severity     text        NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'watch', 'positive')),
  message_key  text        NOT NULL,     -- 'insight.category_increase'
  params       jsonb       NOT NULL,     -- {"category": "Delivery", "pct": 42, "amount": 186}
  status       text        NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen', 'dismissed', 'acted')),
  dedupe_key   text        NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT insights_dedupe_uq UNIQUE (user_id, dedupe_key),
  CHECK (period_end >= period_start)
);
CREATE INDEX insights_user_idx ON insights.insights (user_id, created_at DESC) WHERE status IN ('new', 'seen');

ALTER TABLE insights.insights ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows   ON insights.insights FOR ALL TO moneymap_app
  USING (user_id = (SELECT core.current_user_id())) WITH CHECK (user_id = (SELECT core.current_user_id()));
CREATE POLICY worker_all   ON insights.insights FOR ALL TO moneymap_worker USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON insights.insights TO moneymap_app, moneymap_worker;
