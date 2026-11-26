-- =============================================================================
-- MoneyMap · 040 · finance (núcleo financiero)
-- FTR-003 multicuenta, FTR-004 Quick Add, FTR-005 categorías, FTR-006 historial,
-- FTR-031 ingresos, gastos recurrentes para Safe to Spend (FTR-009),
-- monedas del usuario ("Mis monedas") y periodos financieros.
--
-- Reglas de diseño:
--   * Los datos son personales: cada fila lleva user_id y solo su dueño la ve
--     (RLS). No hay cuentas compartidas.
--   * Las claves foráneas compuestas (user_id, id) impiden usar la cuenta o la
--     categoría de otro usuario aunque la app tenga un error.
--   * Una cuenta es efectivo o una tarjeta (sin distinguir débito de crédito).
--     Las dos tienen saldo. Los datos propios de la tarjeta (banco del catálogo
--     y últimos 4 dígitos) viven en finance.cards. El plan decide cuántas tarjetas y cuántas monedas
--     puede tener el usuario ('finance.cards' y 'finance.currencies').
--   * Cada cuenta tiene UNA moneda y todo lo que pasa en ella queda en esa
--     moneda. MoneyMap no tiene tipos de cambio ni convierte: solo se
--     transfiere entre cuentas de la misma moneda y ningún total suma monedas
--     distintas. Las claves foráneas (user_id, account_id, currency) lo imponen.
--   * Cada usuario tiene UNA cuenta por defecto (is_default): la que la app
--     propone primero en Quick Add, voz y escaneo.
--   * Efectivo o tarjeta sale del tipo de cuenta (catalog.account_types.is_card).
--   * Ingreso o gasto sale de la categoría.
--   * Montos en numeric(19,4), nunca float.
--   * finance.transactions está particionada por HASH(user_id) en 16 partes:
--     las consultas de un usuario tocan una sola partición.
--
-- Errores para la API (HINT → código de problem+json):
--   currency_unavailable, currency_mismatch, transfer_currency_mismatch,
--   invalid_transfer_target, invalid_amount, account_currency_locked,
--   currency_in_use; SQLSTATE MM001 = plan_limit (HINT plan_limit:<funcionalidad>).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS finance;
COMMENT ON SCHEMA finance IS 'Cuentas, tarjetas, categorías, transacciones, recurrentes y periodos de cada usuario.';

-- Periodo financiero del usuario: cómo agrupa su dinero (Safe to Spend,
-- Money Flow, Money Story). Lista fija:
--   weekly        semanal: 7 días desde el día de la semana elegido
--   semi_monthly  quincenal: dos por mes, desde el día d y desde el d + 15
--   monthly       mensual: desde el día del mes elegido (su día de cobro)
CREATE TYPE finance.period_type AS ENUM ('weekly', 'semi_monthly', 'monthly');

-- Frecuencia de un gasto o ingreso recurrente. Lista fija:
--   weekly cada semana · biweekly cada 2 semanas · monthly cada mes · yearly cada año
CREATE TYPE finance.frequency AS ENUM ('weekly', 'biweekly', 'monthly', 'yearly');

-- Cómo se registró un movimiento (mide el uso de Quick Add, voz y escaneo). Lista fija:
--   manual · quick_add · voice (dictado) · scan (factura) · recurring (lo registró un
--   recurrente) · onboarding · adjustment (corrección de saldo)
CREATE TYPE finance.transaction_source AS ENUM ('manual', 'quick_add', 'voice', 'scan', 'recurring', 'onboarding', 'adjustment');

-- -----------------------------------------------------------------------------
-- Configuración financiera del usuario
-- -----------------------------------------------------------------------------
CREATE TABLE finance.user_settings (
  user_id          uuid                PRIMARY KEY REFERENCES iam.users (id) ON DELETE CASCADE,
  main_currency    char(3)             NOT NULL REFERENCES catalog.currencies (code),
  period_type      finance.period_type NOT NULL DEFAULT 'monthly',
  period_start_day smallint            NOT NULL DEFAULT 1,
  planned_savings  numeric(19,4)       NOT NULL DEFAULT 0 CHECK (planned_savings >= 0),   -- por periodo, en la moneda principal
  updated_at       timestamptz         NOT NULL DEFAULT now(),
  CONSTRAINT user_settings_period_start_chk CHECK (CASE period_type
    WHEN 'weekly'       THEN period_start_day BETWEEN 0 AND 6     -- 0 domingo … 6 sábado
    WHEN 'semi_monthly' THEN period_start_day BETWEEN 1 AND 13    -- d y d + 15 caben en cualquier mes
    ELSE                     period_start_day BETWEEN 1 AND 28 END)
);
CREATE TRIGGER user_settings_set_updated_at BEFORE UPDATE ON finance.user_settings
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER user_settings_audit AFTER INSERT OR UPDATE OR DELETE ON finance.user_settings
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();
COMMENT ON TABLE finance.user_settings IS
  'Moneda principal, periodo financiero (semanal, quincenal o mensual) y ahorro planificado por periodo. Una fila por usuario.';
COMMENT ON COLUMN finance.user_settings.main_currency IS
  'Moneda que la app muestra primero. Cambiarla no convierte ni cambia ningún monto.';
COMMENT ON COLUMN finance.user_settings.period_start_day IS
  'weekly: día de la semana (0 domingo … 6 sábado). semi_monthly: día d del mes (1 a 13); la segunda quincena empieza el d + 15. monthly: día del mes (1 a 28), por ejemplo su día de cobro.';
COMMENT ON COLUMN finance.user_settings.planned_savings IS
  'Cuánto quiere ahorrar en cada periodo, en la moneda principal. Safe to Spend de esa moneda lo resta.';

-- Inicio y fin (inclusive) del periodo que contiene p_date.
CREATE OR REPLACE FUNCTION finance.period_bounds(p_type finance.period_type, p_start_day smallint, p_date date,
                                                 OUT starts_on date, OUT ends_on date)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_month date := date_trunc('month', p_date)::date;
  v_day   int  := extract(day FROM p_date);
BEGIN
  CASE p_type
    WHEN 'weekly' THEN
      starts_on := p_date - ((extract(dow FROM p_date)::int - p_start_day + 7) % 7);
      ends_on   := starts_on + 6;
    WHEN 'monthly' THEN
      starts_on := CASE WHEN v_day >= p_start_day THEN v_month ELSE (v_month - INTERVAL '1 month')::date END
                   + (p_start_day - 1);
      ends_on   := (starts_on + INTERVAL '1 month')::date - 1;
    WHEN 'semi_monthly' THEN
      IF v_day >= p_start_day + 15 THEN            -- segunda quincena
        starts_on := v_month + (p_start_day + 14);
        ends_on   := (v_month + INTERVAL '1 month')::date + (p_start_day - 2);
      ELSIF v_day >= p_start_day THEN              -- primera quincena
        starts_on := v_month + (p_start_day - 1);
        ends_on   := v_month + (p_start_day + 13);
      ELSE                                         -- segunda quincena del mes anterior
        starts_on := (v_month - INTERVAL '1 month')::date + (p_start_day + 14);
        ends_on   := v_month + (p_start_day - 2);
      END IF;
  END CASE;
END $$;
COMMENT ON FUNCTION finance.period_bounds(finance.period_type, smallint, date) IS
  'Periodo que contiene la fecha: monthly día 25 → del 25 al 24 del mes siguiente; semi_monthly día 1 → 1-15 y 16-fin de mes; weekly día 1 → lunes a domingo.';

-- Periodo actual (o el de p_date) de un usuario, según su configuración.
CREATE OR REPLACE FUNCTION finance.current_period(p_user uuid, p_date date DEFAULT current_date,
                                                  OUT starts_on date, OUT ends_on date)
LANGUAGE sql STABLE AS $$
  SELECT b.starts_on, b.ends_on
  FROM (SELECT coalesce(max(s.period_type), 'monthly') AS t, coalesce(max(s.period_start_day), 1)::smallint AS d
        FROM finance.user_settings s WHERE s.user_id = p_user) cfg
  CROSS JOIN LATERAL finance.period_bounds(cfg.t, cfg.d, p_date) b
$$;
COMMENT ON FUNCTION finance.current_period(uuid, date) IS
  'Inicio y fin del periodo del usuario. Safe to Spend, Money Flow y Money Story usan este rango.';

-- -----------------------------------------------------------------------------
-- Mis monedas: las que el usuario ve primero al elegir moneda
-- Siempre incluye la moneda principal y las de sus cuentas. Se agregan solas al
-- crear una cuenta en una moneda nueva, y el usuario puede agregar o quitar
-- otras en Ajustes.
-- -----------------------------------------------------------------------------
CREATE TABLE finance.user_currencies (
  user_id    uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  currency   char(3)     NOT NULL REFERENCES catalog.currencies (code),
  sort_order smallint    NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, currency)
);
COMMENT ON TABLE finance.user_currencies IS
  'Monedas favoritas del usuario para el selector. La moneda principal y las de cuentas activas no se pueden quitar.';

CREATE OR REPLACE FUNCTION finance.user_currencies_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    PERFORM catalog.assert_currency_active(NEW.currency);
    RETURN NEW;
  END IF;
  -- Al borrar el usuario (cascada) no hay nada que proteger
  IF NOT EXISTS (SELECT 1 FROM iam.users WHERE id = OLD.user_id) THEN
    RETURN OLD;
  END IF;
  IF EXISTS (SELECT 1 FROM finance.user_settings WHERE user_id = OLD.user_id AND main_currency = OLD.currency) THEN
    RAISE EXCEPTION 'No se puede quitar % de Mis monedas: es tu moneda principal', OLD.currency
      USING ERRCODE = 'check_violation', HINT = 'currency_in_use';
  END IF;
  IF EXISTS (SELECT 1 FROM finance.accounts
             WHERE user_id = OLD.user_id AND currency = OLD.currency AND deleted_at IS NULL AND archived_at IS NULL) THEN
    RAISE EXCEPTION 'No se puede quitar % de Mis monedas: tienes cuentas activas en esa moneda', OLD.currency
      USING ERRCODE = 'check_violation', HINT = 'currency_in_use';
  END IF;
  RETURN OLD;
END $$;

CREATE TRIGGER user_currencies_guard BEFORE INSERT OR DELETE ON finance.user_currencies
  FOR EACH ROW EXECUTE FUNCTION finance.user_currencies_guard();

-- Agrega una moneda a Mis monedas si todavía no está
CREATE OR REPLACE FUNCTION finance.remember_currency(p_user uuid, p_currency char(3)) RETURNS void
LANGUAGE sql AS $$
  INSERT INTO finance.user_currencies (user_id, currency) VALUES (p_user, p_currency)
  ON CONFLICT (user_id, currency) DO NOTHING
$$;

-- La moneda principal debe estar activa y queda siempre en Mis monedas
CREATE OR REPLACE FUNCTION finance.user_settings_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.main_currency IS DISTINCT FROM OLD.main_currency THEN
    PERFORM catalog.assert_currency_active(NEW.main_currency);
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION finance.user_settings_after_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM finance.remember_currency(NEW.user_id, NEW.main_currency);
  RETURN NULL;
END $$;

CREATE TRIGGER user_settings_before_write BEFORE INSERT OR UPDATE OF main_currency ON finance.user_settings
  FOR EACH ROW EXECUTE FUNCTION finance.user_settings_before_write();
CREATE TRIGGER user_settings_after_write AFTER INSERT OR UPDATE OF main_currency ON finance.user_settings
  FOR EACH ROW EXECUTE FUNCTION finance.user_settings_after_write();

-- -----------------------------------------------------------------------------
-- Cuentas: dónde está el dinero (efectivo, tarjeta de débito o de crédito)
-- -----------------------------------------------------------------------------
CREATE TABLE finance.accounts (
  id              uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id         uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  name            text          NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  type            text          NOT NULL REFERENCES catalog.account_types (code),   -- cash o card
  currency        char(3)       NOT NULL REFERENCES catalog.currencies (code),
  opening_balance numeric(19,4) NOT NULL DEFAULT 0,
  current_balance numeric(19,4) NOT NULL DEFAULT 0,     -- lo mantiene un trigger
  is_default      boolean       NOT NULL DEFAULT false, -- la que la app propone primero
  sort_order      smallint      NOT NULL DEFAULT 0,
  archived_at     timestamptz,
  created_at      timestamptz   NOT NULL DEFAULT now(),
  updated_at      timestamptz   NOT NULL DEFAULT now(),
  deleted_at      timestamptz,
  CONSTRAINT accounts_user_id_uq          UNIQUE (user_id, id),
  CONSTRAINT accounts_user_id_currency_uq UNIQUE (user_id, id, currency),
  CONSTRAINT accounts_user_id_type_uq     UNIQUE (user_id, id, type),
  CONSTRAINT accounts_default_active_chk  CHECK (NOT is_default OR (archived_at IS NULL AND deleted_at IS NULL)),
  -- Una sola por defecto por usuario. Se valida al final de la transacción para
  -- poder marcar la nueva y desmarcar la anterior en la misma operación.
  CONSTRAINT accounts_one_default         EXCLUDE USING btree (user_id WITH =) WHERE (is_default)
                                          DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX accounts_name_uq ON finance.accounts (user_id, lower(name)) WHERE deleted_at IS NULL;
COMMENT ON TABLE finance.accounts IS
  'Efectivo y tarjetas. Una moneda por cuenta: para tener Bs y USD en efectivo se crean dos cuentas. Los datos de tarjeta van en finance.cards.';
COMMENT ON COLUMN finance.accounts.current_balance IS 'Saldo actual; lo mantienen los triggers. En tarjetas de crédito es negativo: lo que se debe.';
COMMENT ON COLUMN finance.accounts.is_default IS
  'Cuenta por defecto (una por usuario): la que la app propone primero. La primera cuenta lo es sola; si se archiva, pasa a la siguiente.';

CREATE OR REPLACE FUNCTION finance.sync_opening_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    NEW.current_balance := NEW.opening_balance;
  ELSIF NEW.opening_balance IS DISTINCT FROM OLD.opening_balance THEN
    NEW.current_balance := NEW.current_balance + (NEW.opening_balance - OLD.opening_balance);
  END IF;
  RETURN NEW;
END $$;

-- Valida tipo y moneda, aplica los límites del plan (tarjetas y monedas) y
-- mantiene una sola cuenta por defecto. Una tarjeta o una moneda cuenta cuando
-- la cuenta se crea, se desarchiva, se restaura o cambia de tipo o moneda.
-- Tras bajar de plan, lo que ya tiene se conserva; solo se impide agregar más.
CREATE OR REPLACE FUNCTION finance.accounts_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_type_active boolean;
  v_is_card     boolean;
  v_was_card    boolean := false;
  v_active      boolean := NEW.deleted_at IS NULL AND NEW.archived_at IS NULL;
  v_was_active  boolean := false;
  v_limit       record;
  v_used        int;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    v_was_active := OLD.deleted_at IS NULL AND OLD.archived_at IS NULL;
  END IF;

  IF TG_OP = 'INSERT' OR NEW.type IS DISTINCT FROM OLD.type THEN
    SELECT is_active INTO v_type_active FROM catalog.account_types WHERE code = NEW.type;
    IF NOT coalesce(v_type_active, false) THEN
      RAISE EXCEPTION 'El tipo de cuenta % no está disponible', NEW.type USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  -- Con movimientos, el tipo ya no cambia: el signo del saldo y "efectivo o tarjeta" dependen de él
  IF TG_OP = 'UPDATE' AND NEW.type IS DISTINCT FROM OLD.type
     AND EXISTS (SELECT 1 FROM finance.transactions t WHERE t.user_id = OLD.user_id AND t.account_id = OLD.id) THEN
    RAISE EXCEPTION 'La cuenta "%" ya tiene movimientos: crea una cuenta nueva en vez de cambiar su tipo', OLD.name
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'INSERT' OR NEW.currency IS DISTINCT FROM OLD.currency THEN
    PERFORM catalog.assert_currency_active(NEW.currency);
  END IF;
  -- La moneda solo se corrige mientras la cuenta no se haya usado
  IF TG_OP = 'UPDATE' AND NEW.currency IS DISTINCT FROM OLD.currency
     AND (EXISTS (SELECT 1 FROM finance.transactions t
                  WHERE t.user_id = OLD.user_id AND (t.account_id = OLD.id OR t.transfer_account_id = OLD.id))
          OR EXISTS (SELECT 1 FROM finance.recurring_rules r WHERE r.user_id = OLD.user_id AND r.account_id = OLD.id)) THEN
    RAISE EXCEPTION 'La cuenta "%" ya se usó: crea una cuenta nueva en % en vez de cambiar su moneda', OLD.name, NEW.currency
      USING ERRCODE = 'check_violation', HINT = 'account_currency_locked';
  END IF;

  -- Límite de tarjetas del plan
  SELECT is_card INTO v_is_card FROM catalog.account_types WHERE code = NEW.type;
  IF TG_OP = 'UPDATE' THEN
    SELECT t.is_card AND v_was_active INTO v_was_card FROM catalog.account_types t WHERE t.code = OLD.type;
  END IF;
  IF v_is_card AND v_active AND NOT v_was_card THEN
    -- Serializa altas del mismo usuario (varias instancias de la API)
    PERFORM pg_advisory_xact_lock(hashtextextended('finance.accounts:' || NEW.user_id::text, 0));
    IF NOT billing.try_consume(NEW.user_id, 'finance.cards') THEN
      SELECT * INTO v_limit FROM billing.limit_status(NEW.user_id, 'finance.cards');
      RAISE EXCEPTION 'Tu plan permite % tarjeta(s) y ya tienes %', coalesce(v_limit.limit_value, 0), coalesce(v_limit.used, 0)
        USING ERRCODE = 'MM001', HINT = 'plan_limit:finance.cards';
    END IF;
  END IF;

  -- Límite de monedas del plan: solo cuenta una moneda que el usuario aún no usa
  IF v_active AND (NOT v_was_active OR NEW.currency IS DISTINCT FROM OLD.currency)
     AND NOT EXISTS (SELECT 1 FROM finance.accounts a
                     WHERE a.user_id = NEW.user_id AND a.id <> NEW.id AND a.currency = NEW.currency
                       AND a.deleted_at IS NULL AND a.archived_at IS NULL) THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('finance.accounts:' || NEW.user_id::text, 0));
    SELECT * INTO v_limit FROM billing.limit_status(NEW.user_id, 'finance.currencies');
    SELECT count(DISTINCT a.currency) INTO v_used FROM finance.accounts a
    WHERE a.user_id = NEW.user_id AND a.id <> NEW.id AND a.deleted_at IS NULL AND a.archived_at IS NULL;
    IF NOT coalesce(v_limit.is_enabled, false) OR (v_limit.limit_value IS NOT NULL AND v_used + 1 > v_limit.limit_value) THEN
      RAISE EXCEPTION 'Tu plan permite % moneda(s) y ya usas %', coalesce(v_limit.limit_value, 0), v_used
        USING ERRCODE = 'MM001', HINT = 'plan_limit:finance.currencies';
    END IF;
  END IF;

  -- Cuenta por defecto: la primera lo es sola; una archivada o borrada deja de serlo
  IF NOT v_active THEN
    NEW.is_default := false;
  ELSIF TG_OP = 'INSERT' AND NOT EXISTS (SELECT 1 FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.is_default) THEN
    NEW.is_default := true;
  END IF;
  RETURN NEW;
END $$;

-- Mis monedas y cuenta por defecto: marcar una desmarca la anterior; si el
-- usuario se quedó sin ninguna, pasa a la siguiente cuenta activa.
CREATE OR REPLACE FUNCTION finance.accounts_after_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.currency IS DISTINCT FROM OLD.currency THEN
    PERFORM finance.remember_currency(NEW.user_id, NEW.currency);
  END IF;
  IF NEW.is_default AND (TG_OP = 'INSERT' OR NOT OLD.is_default) THEN
    UPDATE finance.accounts SET is_default = false WHERE user_id = NEW.user_id AND is_default AND id <> NEW.id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.is_default) THEN
    UPDATE finance.accounts SET is_default = true
     WHERE id = (SELECT a.id FROM finance.accounts a
                 WHERE a.user_id = NEW.user_id AND a.deleted_at IS NULL AND a.archived_at IS NULL
                 ORDER BY a.sort_order, a.id LIMIT 1);
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER accounts_before_write BEFORE INSERT OR UPDATE OF type, currency, archived_at, deleted_at, is_default ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION finance.accounts_before_write();
CREATE TRIGGER accounts_after_write AFTER INSERT OR UPDATE OF currency, archived_at, deleted_at, is_default ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION finance.accounts_after_write();
CREATE TRIGGER accounts_sync_opening_balance BEFORE INSERT OR UPDATE ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION finance.sync_opening_balance();
CREATE TRIGGER accounts_set_updated_at BEFORE UPDATE ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER accounts_audit AFTER INSERT OR UPDATE OR DELETE ON finance.accounts
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();

-- -----------------------------------------------------------------------------
-- Tarjetas: datos que solo tienen las tarjetas. Una fila por cuenta de tipo
-- tarjeta (1 a 1). El saldo, la moneda y el nombre siguen en finance.accounts.
-- -----------------------------------------------------------------------------
CREATE TABLE finance.cards (
  account_id       uuid        PRIMARY KEY,
  user_id          uuid        NOT NULL,
  account_type     text        NOT NULL DEFAULT 'card' CHECK (account_type = 'card'),
  institution_code text        REFERENCES catalog.financial_institutions (code),   -- banco emisor del catálogo
  last4            char(4)     CHECK (last4 ~ '^[0-9]{4}$'),   -- solo para reconocerla; nunca el número completo
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT cards_account_fk FOREIGN KEY (user_id, account_id, account_type)
                              REFERENCES finance.accounts (user_id, id, type) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE TRIGGER cards_set_updated_at BEFORE UPDATE ON finance.cards
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE finance.cards IS
  'Banco emisor y últimos 4 dígitos de cada tarjeta. La clave (user_id, account_id, account_type) exige que la cuenta sea una tarjeta del mismo usuario.';

-- -----------------------------------------------------------------------------
-- Categorías (copiadas de catalog.category_templates al registrarse)
-- -----------------------------------------------------------------------------
CREATE TABLE finance.categories (
  id           uuid               PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id      uuid               NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  template_key text               REFERENCES catalog.category_templates (key) ON DELETE SET NULL,
  kind         catalog.money_kind NOT NULL CHECK (kind IN ('income', 'expense')),
  flow_group   catalog.flow_group,                                          -- solo en gastos
  name         text               NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  icon         text               NOT NULL DEFAULT 'label',
  color        text               NOT NULL DEFAULT '#6B7280' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  sort_order   smallint           NOT NULL DEFAULT 0,
  created_at   timestamptz        NOT NULL DEFAULT now(),
  updated_at   timestamptz        NOT NULL DEFAULT now(),
  deleted_at   timestamptz,
  CONSTRAINT categories_user_id_uq      UNIQUE (user_id, id),
  CONSTRAINT categories_user_id_kind_uq UNIQUE (user_id, id, kind),
  CONSTRAINT categories_flow_chk        CHECK ((kind = 'expense') = (flow_group IS NOT NULL))
);
CREATE UNIQUE INDEX categories_name_uq ON finance.categories (user_id, kind, lower(name)) WHERE deleted_at IS NULL;
CREATE TRIGGER categories_set_updated_at BEFORE UPDATE ON finance.categories
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE finance.categories IS
  'Categorías de cada usuario: copia editable de las iniciales más las que cree. kind dice si es ingreso o gasto; flow_group, a qué nodo del Money Flow va un gasto.';

-- -----------------------------------------------------------------------------
-- Gastos e ingresos recurrentes (onboarding, Safe to Spend, recordatorios)
-- Ingreso o gasto sale de su categoría.
-- -----------------------------------------------------------------------------
CREATE TABLE finance.recurring_rules (
  id                 uuid              PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id            uuid              NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  account_id         uuid              NOT NULL,
  category_id        uuid              NOT NULL,
  amount             numeric(19,4)     NOT NULL CHECK (amount > 0),
  currency           char(3)           NOT NULL,      -- la de la cuenta; la completa un trigger
  description        text              NOT NULL CHECK (length(description) BETWEEN 1 AND 120),
  frequency          finance.frequency NOT NULL,
  start_date         date              NOT NULL,
  end_date           date,
  next_due_on        date              NOT NULL,      -- si no se envía, start_date
  is_committed       boolean           NOT NULL DEFAULT true,   -- se resta en Safe to Spend
  auto_post          boolean           NOT NULL DEFAULT false,  -- registrar sola la transacción al vencer
  remind_days_before smallint          NOT NULL DEFAULT 1 CHECK (remind_days_before BETWEEN 0 AND 14),
  is_active          boolean           NOT NULL DEFAULT true,
  created_at         timestamptz       NOT NULL DEFAULT now(),
  updated_at         timestamptz       NOT NULL DEFAULT now(),
  deleted_at         timestamptz,
  CONSTRAINT recurring_rules_user_id_uq  UNIQUE (user_id, id),
  CONSTRAINT recurring_rules_account_fk  FOREIGN KEY (user_id, account_id, currency)
                                         REFERENCES finance.accounts (user_id, id, currency),
  CONSTRAINT recurring_rules_category_fk FOREIGN KEY (user_id, category_id)
                                         REFERENCES finance.categories (user_id, id),
  CONSTRAINT recurring_rules_dates_chk   CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX recurring_rules_due_idx  ON finance.recurring_rules (next_due_on) WHERE is_active AND deleted_at IS NULL;
CREATE INDEX recurring_rules_user_idx ON finance.recurring_rules (user_id) WHERE deleted_at IS NULL;
CREATE TRIGGER recurring_rules_set_updated_at BEFORE UPDATE ON finance.recurring_rules
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE finance.recurring_rules IS
  'Alquiler, sueldo, Netflix: lo que se repite. Sirve para recordatorios, para registrarse solo (auto_post) y para restarse en Safe to Spend (is_committed).';

-- Moneda de la cuenta y primera fecha de vencimiento
CREATE OR REPLACE FUNCTION finance.recurring_rules_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_currency char(3);
  v_name     text;
BEGIN
  SELECT a.currency, a.name INTO v_currency, v_name
  FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id;
  IF FOUND THEN                                   -- si no existe, la clave foránea lo rechaza
    IF NEW.currency IS NULL THEN
      NEW.currency := v_currency;
    ELSIF NEW.currency <> v_currency THEN
      RAISE EXCEPTION 'La cuenta "%" es en %: no se puede usar con %', v_name, v_currency, NEW.currency
        USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
    END IF;
  END IF;
  NEW.next_due_on := coalesce(NEW.next_due_on, NEW.start_date);
  RETURN NEW;
END $$;
CREATE TRIGGER recurring_rules_before_write BEFORE INSERT OR UPDATE OF account_id, currency, next_due_on ON finance.recurring_rules
  FOR EACH ROW EXECUTE FUNCTION finance.recurring_rules_before_write();

-- Próxima fecha después de p_after, contando siempre desde start_date: así un
-- pago del 31 cae el 28 o 29 en febrero y vuelve al 31 en marzo.
-- ponytail: recorre hasta 2.000 repeticiones (38 años si es semanal); basta para la vida de una regla.
CREATE OR REPLACE FUNCTION finance.next_occurrence(p_start date, p_frequency finance.frequency, p_after date)
RETURNS date
LANGUAGE sql IMMUTABLE AS $$
  SELECT (p_start + n * s.step)::date
  FROM (SELECT CASE p_frequency WHEN 'weekly'   THEN INTERVAL '1 week'
                                WHEN 'biweekly' THEN INTERVAL '2 weeks'
                                WHEN 'monthly'  THEN INTERVAL '1 month'
                                ELSE                 INTERVAL '1 year' END AS step) s
  CROSS JOIN generate_series(0, 2000) n
  WHERE (p_start + n * s.step)::date > p_after
  ORDER BY n
  LIMIT 1
$$;
COMMENT ON FUNCTION finance.next_occurrence(date, finance.frequency, date) IS
  'Próximo vencimiento de un recurrente después de una fecha. El worker lo usa para avanzar next_due_on.';

-- -----------------------------------------------------------------------------
-- Transacciones (tabla de mayor volumen)
-- Cada movimiento está en la moneda de su cuenta. Una transferencia mueve el
-- mismo monto entre dos cuentas de la misma moneda. Efectivo o tarjeta sale
-- del tipo de la cuenta.
-- Diseño para leer rápido: currency se guarda aquí (copia de la de la cuenta)
-- para sumar por moneda sin unir con accounts; la lista solo une con
-- categories y accounts por su clave primaria.
-- -----------------------------------------------------------------------------
CREATE TABLE finance.transactions (
  id                  uuid               NOT NULL DEFAULT core.uuid_v7(),
  user_id             uuid               NOT NULL,
  kind                catalog.money_kind NOT NULL,
  account_id          uuid               NOT NULL,
  category_id         uuid,                          -- NULL solo en transferencias
  amount              numeric(19,4)      NOT NULL CHECK (amount > 0),
  currency            char(3)            NOT NULL,   -- la de la cuenta; la completa el trigger
  transfer_account_id uuid,                          -- cuenta destino, en la misma moneda
  occurred_on         date               NOT NULL,
  description         text               NOT NULL DEFAULT '' CHECK (length(description) <= 200),   -- 'Netflix', 'Almuerzo'
  source              finance.transaction_source NOT NULL DEFAULT 'manual',
  recurring_rule_id   uuid,
  created_at          timestamptz        NOT NULL DEFAULT now(),
  updated_at          timestamptz        NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  CONSTRAINT transactions_pk           PRIMARY KEY (user_id, id),
  CONSTRAINT transactions_user_fk      FOREIGN KEY (user_id) REFERENCES iam.users (id) ON DELETE CASCADE,
  CONSTRAINT transactions_account_fk   FOREIGN KEY (user_id, account_id, currency)
                                       REFERENCES finance.accounts (user_id, id, currency),
  CONSTRAINT transactions_transfer_fk  FOREIGN KEY (user_id, transfer_account_id, currency)
                                       REFERENCES finance.accounts (user_id, id, currency),
  CONSTRAINT transactions_category_fk  FOREIGN KEY (user_id, category_id, kind)
                                       REFERENCES finance.categories (user_id, id, kind),
  CONSTRAINT transactions_recurring_fk FOREIGN KEY (user_id, recurring_rule_id)
                                       REFERENCES finance.recurring_rules (user_id, id) ON DELETE SET NULL (recurring_rule_id),
  CONSTRAINT transactions_category_chk CHECK ((kind = 'transfer') = (category_id IS NULL)),
  CONSTRAINT transactions_transfer_chk CHECK (
    (kind = 'transfer') = (transfer_account_id IS NOT NULL)
    AND (transfer_account_id IS NULL OR transfer_account_id <> account_id))
) PARTITION BY HASH (user_id);

DO $$
BEGIN
  FOR r IN 0 .. 15 LOOP
    EXECUTE format('CREATE TABLE finance.transactions_p%s PARTITION OF finance.transactions
                    FOR VALUES WITH (MODULUS 16, REMAINDER %s)', lpad(r::text, 2, '0'), r);
  END LOOP;
END $$;

-- Historial con paginación por cursor (occurred_on, id) y filtros
CREATE INDEX transactions_feed_idx      ON finance.transactions (user_id, occurred_on DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX transactions_account_idx   ON finance.transactions (user_id, account_id, occurred_on DESC) WHERE deleted_at IS NULL;
CREATE INDEX transactions_transfer_idx  ON finance.transactions (user_id, transfer_account_id) WHERE transfer_account_id IS NOT NULL;
CREATE INDEX transactions_category_idx  ON finance.transactions (user_id, category_id, occurred_on DESC) WHERE deleted_at IS NULL;
CREATE INDEX transactions_recurring_idx ON finance.transactions (user_id, recurring_rule_id) WHERE recurring_rule_id IS NOT NULL;
-- Búsqueda por texto en la descripción: "Amazon", "Hipermaxi" (FTR-006),
-- y sugerencia de categoría y cuenta en Quick Add (finance.suggest_from_history)
CREATE INDEX transactions_search_idx    ON finance.transactions USING gin (lower(description) gin_trgm_ops);

COMMENT ON TABLE finance.transactions IS
  'Ingresos, gastos y transferencias, en la moneda de su cuenta. Particionada por HASH(user_id). Borrado lógico con deleted_at.';

-- Completa y valida cada movimiento antes de guardarlo: moneda de la cuenta,
-- decimales de la moneda y destino de transferencias. La API puede enviar solo
-- monto, cuenta y categoría; el resto se completa.
CREATE OR REPLACE FUNCTION finance.transactions_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_account_name text;
  v_currency     char(3);
  v_decimals     smallint;
  v_dest         record;
BEGIN
  SELECT a.name, a.currency INTO v_account_name, v_currency
  FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.account_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'La cuenta % no existe para este usuario', NEW.account_id USING ERRCODE = 'foreign_key_violation';
  END IF;

  -- Moneda: la de la cuenta. Nunca se convierte.
  IF NEW.currency IS NULL THEN
    NEW.currency := v_currency;
  ELSIF NEW.currency <> v_currency THEN
    RAISE EXCEPTION 'La cuenta "%" es en %: no se registran movimientos en % en ella', v_account_name, v_currency, NEW.currency
      USING ERRCODE = 'check_violation', HINT = 'currency_mismatch';
  END IF;

  -- Decimales de la moneda: 1000.5 no vale en CLP ni PYG
  SELECT c.decimals INTO v_decimals FROM catalog.currencies c WHERE c.code = NEW.currency;
  IF NEW.amount <> round(NEW.amount, v_decimals) THEN
    RAISE EXCEPTION 'El monto % tiene más de % decimales para %', NEW.amount, v_decimals, NEW.currency
      USING ERRCODE = 'check_violation', HINT = 'invalid_amount';
  END IF;

  -- Transferencias: a otra cuenta activa del usuario, en la misma moneda
  IF NEW.kind = 'transfer' AND (TG_OP = 'INSERT' OR NEW.transfer_account_id IS DISTINCT FROM OLD.transfer_account_id
                                OR NEW.account_id IS DISTINCT FROM OLD.account_id) THEN
    SELECT a.name, a.currency, a.archived_at, a.deleted_at INTO v_dest
    FROM finance.accounts a WHERE a.user_id = NEW.user_id AND a.id = NEW.transfer_account_id;
    IF NOT FOUND OR v_dest.archived_at IS NOT NULL OR v_dest.deleted_at IS NOT NULL
       OR NEW.transfer_account_id = NEW.account_id THEN
      RAISE EXCEPTION 'La cuenta destino no es válida: debe ser otra cuenta activa tuya'
        USING ERRCODE = 'check_violation', HINT = 'invalid_transfer_target';
    END IF;
    IF v_dest.currency <> NEW.currency THEN
      RAISE EXCEPTION 'No se puede transferir de % a "%" (%): solo entre cuentas de la misma moneda',
        NEW.currency, v_dest.name, v_dest.currency
        USING ERRCODE = 'check_violation', HINT = 'transfer_currency_mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER transactions_before_write BEFORE INSERT OR UPDATE ON finance.transactions
  FOR EACH ROW EXECUTE FUNCTION finance.transactions_before_write();
CREATE TRIGGER transactions_set_updated_at BEFORE UPDATE ON finance.transactions
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Saldos: se ajustan en la misma transacción SQL que el movimiento, venga de la
-- API, de la voz, del escaneo o de un recurrente.
CREATE OR REPLACE FUNCTION finance.adjust_account_balance(p_user uuid, p_account uuid, p_delta numeric)
RETURNS void
LANGUAGE sql AS $$
  UPDATE finance.accounts
     SET current_balance = current_balance + p_delta
   WHERE user_id = p_user AND id = p_account
$$;

CREATE OR REPLACE FUNCTION finance.apply_transaction_to_balances() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.deleted_at IS NULL THEN
    PERFORM finance.adjust_account_balance(OLD.user_id, OLD.account_id,
            CASE OLD.kind WHEN 'income' THEN -OLD.amount ELSE OLD.amount END);
    IF OLD.kind = 'transfer' THEN
      PERFORM finance.adjust_account_balance(OLD.user_id, OLD.transfer_account_id, -OLD.amount);
    END IF;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') AND NEW.deleted_at IS NULL THEN
    PERFORM finance.adjust_account_balance(NEW.user_id, NEW.account_id,
            CASE NEW.kind WHEN 'income' THEN NEW.amount ELSE -NEW.amount END);
    IF NEW.kind = 'transfer' THEN
      PERFORM finance.adjust_account_balance(NEW.user_id, NEW.transfer_account_id, NEW.amount);
    END IF;
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER transactions_apply_balances AFTER INSERT OR UPDATE OR DELETE ON finance.transactions
  FOR EACH ROW EXECUTE FUNCTION finance.apply_transaction_to_balances();

-- Conciliación: recalcula un saldo desde cero (job nocturno o soporte).
CREATE OR REPLACE FUNCTION finance.recalculate_account_balance(p_user uuid, p_account uuid)
RETURNS numeric
LANGUAGE sql AS $$
  UPDATE finance.accounts a
     SET current_balance = a.opening_balance + coalesce((
           SELECT sum(CASE WHEN t.account_id = p_account
                           THEN CASE t.kind WHEN 'income' THEN t.amount ELSE -t.amount END
                           ELSE t.amount END)          -- llegó por transferencia
           FROM finance.transactions t
           WHERE t.user_id = p_user
             AND (t.account_id = p_account OR t.transfer_account_id = p_account)
             AND t.deleted_at IS NULL), 0)
   WHERE a.user_id = p_user AND a.id = p_account
  RETURNING a.current_balance
$$;

-- Sugerencia de Quick Add: "netflix" → la categoría y la cuenta de la última
-- transacción con ese texto (FTR-006). Sale del historial, sin tabla aparte.
CREATE OR REPLACE FUNCTION finance.suggest_from_history(p_user uuid, p_text text)
RETURNS TABLE (category_id uuid, account_id uuid, kind catalog.money_kind)
LANGUAGE sql STABLE AS $$
  SELECT t.category_id, t.account_id, t.kind
  FROM finance.transactions t
  WHERE t.user_id = p_user AND t.deleted_at IS NULL AND t.kind <> 'transfer'
    AND lower(t.description)
        LIKE '%' || replace(replace(replace(lower(btrim(p_text)), '\', '\\'), '%', '\%'), '_', '\_') || '%'
  ORDER BY t.occurred_on DESC, t.id DESC
  LIMIT 1
$$;
COMMENT ON FUNCTION finance.suggest_from_history(uuid, text) IS
  'Categoría y cuenta que el usuario usó la última vez con esa descripción. Reemplaza a la antigua tabla categorization_memory.';

-- -----------------------------------------------------------------------------
-- Saldos (Financial Position, FTR-012): por cuenta y por moneda, sin convertir
-- -----------------------------------------------------------------------------
CREATE VIEW finance.account_balances AS
SELECT a.user_id,
       a.id                                          AS account_id,
       a.name,
       a.type,
       t.is_card,
       a.currency,
       a.currency = s.main_currency                  AS is_main_currency,
       a.is_default,
       a.current_balance,
       c.last4,
       fi.short_name                                 AS institution
FROM finance.accounts a
JOIN catalog.account_types t ON t.code = a.type
JOIN finance.user_settings s ON s.user_id = a.user_id
LEFT JOIN finance.cards c ON c.user_id = a.user_id AND c.account_id = a.id
LEFT JOIN catalog.financial_institutions fi ON fi.code = c.institution_code
WHERE a.deleted_at IS NULL AND a.archived_at IS NULL;
COMMENT ON VIEW finance.account_balances IS
  'Saldo de cada cuenta activa en su moneda, con el banco y los últimos 4 dígitos si es tarjeta.';

-- Una fila por moneda: total, cuánto en efectivo y cuánto en tarjetas.
-- La API ordena con is_main_currency DESC para mostrar la principal primero.
CREATE VIEW finance.balance_totals AS
SELECT b.user_id,
       b.currency,
       b.is_main_currency,
       sum(b.current_balance)                                          AS total,
       coalesce(sum(b.current_balance) FILTER (WHERE NOT b.is_card), 0) AS cash_total,
       coalesce(sum(b.current_balance) FILTER (WHERE b.is_card), 0)     AS card_total,
       count(*)                                                        AS accounts
FROM finance.account_balances b
GROUP BY b.user_id, b.currency, b.is_main_currency;
COMMENT ON VIEW finance.balance_totals IS 'Totales por moneda para el Map: total, en efectivo y en tarjetas. Nunca suma monedas distintas.';

-- -----------------------------------------------------------------------------
-- Alta financiera de un usuario: configuración, Mis monedas y categorías iniciales
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION finance.setup_user(p_user uuid, p_main_currency char(3), p_lang text DEFAULT 'es')
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
  v_count int;
BEGIN
  INSERT INTO finance.user_settings (user_id, main_currency)
  VALUES (p_user, p_main_currency)
  ON CONFLICT (user_id) DO NOTHING;

  INSERT INTO finance.categories (user_id, template_key, kind, flow_group, name, icon, color, sort_order)
  SELECT p_user, t.key, t.kind, t.flow_group, coalesce(t.names ->> p_lang, t.names ->> 'es'), t.icon, t.color, t.sort_order
  FROM catalog.category_templates t
  WHERE t.is_active
    AND NOT EXISTS (SELECT 1 FROM finance.categories c WHERE c.user_id = p_user AND c.template_key = t.key);

  SELECT count(*) INTO v_count FROM finance.categories WHERE user_id = p_user;
  RETURN v_count;
END $$;
COMMENT ON FUNCTION finance.setup_user(uuid, char, text) IS
  'Crea la configuración financiera (la moneda principal entra a Mis monedas) y copia las categorías iniciales. Idempotente.';
