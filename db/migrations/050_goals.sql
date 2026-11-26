-- =============================================================================
-- MoneyMap · 050 · goals (metas de ahorro)
-- FTR-018 metas y FTR-019 Goal Forecast. La fecha estimada se calcula en el
-- motor financiero de la API a partir de los aportes; aquí se guardan los datos.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS goals;
COMMENT ON SCHEMA goals IS 'Metas de ahorro y sus aportes.';

CREATE TABLE goals.goals (
  id                           uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id                      uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  name                         text          NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  target_amount                numeric(19,4) NOT NULL CHECK (target_amount > 0),
  currency                     char(3)       NOT NULL REFERENCES catalog.currencies (code),   -- los aportes van en esta moneda
  current_amount               numeric(19,4) NOT NULL DEFAULT 0,      -- lo mantiene un trigger
  target_date                  date,
  priority                     smallint      NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),  -- 1 = más alta
  planned_contribution         numeric(19,4) CHECK (planned_contribution >= 0),   -- aporte planeado por periodo
  status                       text          NOT NULL DEFAULT 'active'
                                             CHECK (status IN ('active', 'paused', 'achieved', 'archived')),
  achieved_at                  timestamptz,
  icon                         text,
  color                        text          CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  created_at                   timestamptz   NOT NULL DEFAULT now(),
  updated_at                   timestamptz   NOT NULL DEFAULT now(),
  deleted_at                   timestamptz,
  CONSTRAINT goals_user_id_uq   UNIQUE (user_id, id),
  CONSTRAINT goals_achieved_chk CHECK ((status = 'achieved') = (achieved_at IS NOT NULL))
);
CREATE INDEX goals_user_idx ON goals.goals (user_id, priority) WHERE deleted_at IS NULL AND status = 'active';

-- Una meta nueva (o que cambia de moneda) usa una moneda activa del catálogo
CREATE OR REPLACE FUNCTION goals.goals_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.currency IS DISTINCT FROM OLD.currency THEN
    PERFORM catalog.assert_currency_active(NEW.currency);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER goals_before_write BEFORE INSERT OR UPDATE OF currency ON goals.goals
  FOR EACH ROW EXECUTE FUNCTION goals.goals_before_write();
CREATE TRIGGER goals_set_updated_at BEFORE UPDATE ON goals.goals
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER goals_audit AFTER INSERT OR UPDATE OR DELETE ON goals.goals
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();
COMMENT ON TABLE goals.goals IS 'Destinos del mapa financiero: fondo de emergencia, laptop, viaje… Cada meta tiene su moneda; no se vincula a una cuenta.';
COMMENT ON COLUMN goals.goals.planned_contribution IS 'Cuánto piensa aportar en cada periodo (semana, quincena o mes). Safe to Spend lo resta.';

CREATE TABLE goals.goal_contributions (
  id             uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id        uuid          NOT NULL,
  goal_id        uuid          NOT NULL,
  amount         numeric(19,4) NOT NULL CHECK (amount <> 0),          -- negativo = retiro
  contributed_on date          NOT NULL DEFAULT current_date,
  source         text          NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'transaction', 'adjustment')),
  transaction_id uuid,                                                -- transferencia que originó el aporte
  note           text          CHECK (length(note) <= 500),
  created_at     timestamptz   NOT NULL DEFAULT now(),
  CONSTRAINT goal_contributions_goal_fk        FOREIGN KEY (user_id, goal_id)
                                               REFERENCES goals.goals (user_id, id) ON DELETE CASCADE,
  CONSTRAINT goal_contributions_transaction_fk FOREIGN KEY (user_id, transaction_id)
                                               REFERENCES finance.transactions (user_id, id) ON DELETE SET NULL (transaction_id)
);
CREATE INDEX goal_contributions_goal_idx  ON goals.goal_contributions (goal_id, contributed_on);
CREATE INDEX goal_contributions_user_idx ON goals.goal_contributions (user_id, contributed_on);
COMMENT ON TABLE goals.goal_contributions IS 'Aportes y retiros, en la moneda de la meta. Su ritmo alimenta el Goal Forecast.';

CREATE OR REPLACE FUNCTION goals.apply_contribution() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    UPDATE goals.goals SET current_amount = current_amount - OLD.amount
     WHERE user_id = OLD.user_id AND id = OLD.goal_id;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    UPDATE goals.goals SET current_amount = current_amount + NEW.amount
     WHERE user_id = NEW.user_id AND id = NEW.goal_id;
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER goal_contributions_apply AFTER INSERT OR UPDATE OR DELETE ON goals.goal_contributions
  FOR EACH ROW EXECUTE FUNCTION goals.apply_contribution();
