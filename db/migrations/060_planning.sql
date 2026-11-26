-- =============================================================================
-- MoneyMap · 060 · planning (GPS financiero)
-- FTR-010 Can I Afford It? Safe to Spend (FTR-009) no se guarda: se calcula al
-- momento en el motor financiero. Cada consulta de Can I Afford It? sí se
-- registra, porque cuenta para la North Star ("acción financiera informada").
-- Presupuestos (FTR-014) y What If? (FTR-011) llegan en future/.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS planning;
COMMENT ON SCHEMA planning IS 'Herramientas de decisión: Can I Afford It? hoy; presupuestos y escenarios después.';

CREATE TABLE planning.affordability_checks (
  id                    uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id               uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  description           text          CHECK (length(description) <= 120),
  amount                numeric(19,4) NOT NULL CHECK (amount > 0),
  currency              char(3)       NOT NULL REFERENCES catalog.currencies (code),
  verdict               text          NOT NULL CHECK (verdict IN ('affordable', 'affordable_with_impact', 'not_now')),
  safe_to_spend_before  numeric(19,4) NOT NULL,
  safe_to_spend_after   numeric(19,4) NOT NULL,
  earliest_affordable_on date,                                   -- cuando el veredicto es 'not_now'
  impacts               jsonb         NOT NULL DEFAULT '[]',     -- [{"goal_id": "…", "delay_months": 1}]
  assumptions           jsonb         NOT NULL DEFAULT '{}',     -- supuestos mostrados al usuario
  algorithm_version     text          NOT NULL,
  decision              text          CHECK (decision IN ('bought', 'postponed', 'dismissed')),
  created_at            timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX affordability_checks_user_idx ON planning.affordability_checks (user_id, created_at DESC);
COMMENT ON TABLE planning.affordability_checks IS 'Historial de Can I Afford It?: resultado, impacto, supuestos y lo que decidió el usuario.';
