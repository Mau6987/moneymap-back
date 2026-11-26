-- =============================================================================
-- MoneyMap · 000 · core
-- Funciones compartidas, eventos de dominio (outbox) y auditoría.
-- Requiere PostgreSQL 16 o superior.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS citext;    -- emails sin distinguir mayúsculas
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- búsqueda por texto en transacciones

CREATE SCHEMA IF NOT EXISTS core;
COMMENT ON SCHEMA core IS 'Infraestructura compartida: UUID v7, updated_at, contexto de usuario, particiones, outbox y auditoría.';

-- -----------------------------------------------------------------------------
-- UUID v7: ordenado por tiempo. Mantiene los índices compactos en tablas grandes
-- y permite paginar por id. Se puede generar también desde Python (uuid.uuid7).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.uuid_v7() RETURNS uuid
LANGUAGE sql VOLATILE PARALLEL SAFE AS $$
  SELECT encode(
           set_bit(
             set_bit(
               overlay(uuid_send(gen_random_uuid())
                       PLACING substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                       FROM 1 FOR 6),
               52, 1),
             53, 1),
           'hex')::uuid
$$;
COMMENT ON FUNCTION core.uuid_v7() IS 'Genera un UUID versión 7 (48 bits de timestamp en ms + aleatorio).';

-- -----------------------------------------------------------------------------
-- updated_at automático
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- Contexto de la petición. La API ejecuta al inicio de cada transacción:
--   SELECT set_config('app.user_id', '<uuid>', true);
-- Las políticas RLS y la auditoría leen este valor.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

-- -----------------------------------------------------------------------------
-- Particiones mensuales para tablas de series de tiempo (auditoría,
-- notificaciones, registros por voz). Un job de Celery Beat la ejecuta cada mes.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.ensure_monthly_partitions(p_parent regclass, p_from date, p_months int)
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
  v_schema  text;
  v_table   text;
  v_start   date := date_trunc('month', p_from)::date;
  v_lo      date;
  v_hi      date;
  v_name    text;
  v_created int := 0;
BEGIN
  SELECT n.nspname, c.relname INTO v_schema, v_table
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.oid = p_parent;

  FOR i IN 0 .. p_months - 1 LOOP
    v_lo   := (v_start + make_interval(months => i))::date;
    v_hi   := (v_start + make_interval(months => i + 1))::date;
    v_name := format('%s_%s', v_table, to_char(v_lo, '"y"YYYY"m"MM'));
    IF to_regclass(format('%I.%I', v_schema, v_name)) IS NULL THEN
      EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                     v_schema, v_name, p_parent, v_lo, v_hi);
      v_created := v_created + 1;
    END IF;
  END LOOP;
  RETURN v_created;
END $$;
COMMENT ON FUNCTION core.ensure_monthly_partitions(regclass, date, int) IS
  'Crea las particiones mensuales que falten desde p_from durante p_months meses. Idempotente.';

CREATE OR REPLACE FUNCTION core.drop_partitions_older_than(p_parent regclass, p_before date)
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
  r record;
  v_dropped int := 0;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS part, pg_get_expr(c.relpartbound, c.oid) AS bound
    FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = p_parent
  LOOP
    -- Solo particiones con rango cuyo límite superior sea <= p_before
    IF r.bound LIKE 'FOR VALUES FROM%' AND
       substring(r.bound FROM 'TO \(''([^'']+)''\)')::date <= p_before THEN
      EXECUTE format('DROP TABLE %s', r.part);
      v_dropped := v_dropped + 1;
    END IF;
  END LOOP;
  RETURN v_dropped;
END $$;
COMMENT ON FUNCTION core.drop_partitions_older_than(regclass, date) IS
  'Retención: elimina particiones mensuales completas anteriores a p_before.';

-- -----------------------------------------------------------------------------
-- Outbox de eventos de dominio. Cada módulo escribe aquí en la misma
-- transacción; un worker los publica a Celery (recalcular reportes,
-- notificaciones, analítica). Desacopla los módulos del monolito.
-- -----------------------------------------------------------------------------
CREATE TABLE core.outbox_events (
  id             uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  aggregate_type text        NOT NULL,              -- 'transaction', 'goal', 'subscription'…
  aggregate_id   uuid        NOT NULL,
  user_id        uuid,                              -- dueño del dato, si aplica
  event_type     text        NOT NULL,              -- 'transaction.created'…
  payload        jsonb       NOT NULL DEFAULT '{}',
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  published_at   timestamptz,
  attempts       int         NOT NULL DEFAULT 0
);
CREATE INDEX outbox_events_pending_idx ON core.outbox_events (occurred_at) WHERE published_at IS NULL;
COMMENT ON TABLE core.outbox_events IS 'Eventos de dominio pendientes de publicar (patrón transactional outbox).';

-- -----------------------------------------------------------------------------
-- Auditoría: quién cambió qué. Particionada por mes con retención.
-- -----------------------------------------------------------------------------
CREATE TABLE core.audit_log (
  id            uuid        NOT NULL DEFAULT core.uuid_v7(),
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid,                               -- quién hizo el cambio
  owner_user_id uuid,                               -- de quién es el dato cambiado
  entity        text        NOT NULL,               -- 'finance.accounts'
  entity_id     uuid,
  action        text        NOT NULL CHECK (action IN ('insert', 'update', 'delete', 'login', 'export', 'plan_change')),
  changes       jsonb,                              -- {"columna": [antes, después]}
  ip            inet,
  PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
CREATE TABLE core.audit_log_default PARTITION OF core.audit_log DEFAULT;
CREATE INDEX audit_log_entity_idx ON core.audit_log (entity, entity_id, occurred_at DESC);
CREATE INDEX audit_log_owner_idx  ON core.audit_log (owner_user_id, occurred_at DESC);
COMMENT ON TABLE core.audit_log IS 'Historial de cambios de entidades sensibles. Particionada por mes.';

-- Trigger genérico de auditoría: guarda solo las columnas que cambiaron.
CREATE OR REPLACE FUNCTION core.audit_row_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_old     jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
  v_new     jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
  v_row     jsonb := coalesce(v_new, v_old);
  v_changes jsonb;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    SELECT jsonb_object_agg(k, jsonb_build_array(v_old -> k, v_new -> k)) INTO v_changes
    FROM jsonb_object_keys(v_new) AS k
    WHERE v_old -> k IS DISTINCT FROM v_new -> k
      AND k NOT IN ('updated_at', 'current_balance', 'current_amount');
    IF v_changes IS NULL THEN
      RETURN NULL;   -- solo cambiaron campos derivados
    END IF;
  ELSE
    v_changes := v_row;
  END IF;

  INSERT INTO core.audit_log (actor_user_id, owner_user_id, entity, entity_id, action, changes)
  VALUES (core.current_user_id(),
          nullif(v_row ->> 'user_id', '')::uuid,
          TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
          nullif(v_row ->> 'id', '')::uuid,
          lower(TG_OP),
          v_changes);
  RETURN NULL;
END $$;
-- =============================================================================
-- MoneyMap · 010 · catalog
-- Datos de referencia compartidos por todos los usuarios: monedas, países,
-- instituciones financieras, tipos de cuenta, grupos del Money Flow y
-- plantillas de categorías iniciales.
-- MoneyMap no convierte monedas.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS catalog;
COMMENT ON SCHEMA catalog IS 'Datos de referencia globales (no pertenecen a ningún usuario).';

-- Tipo de movimiento. Es una lista fija (ENUM) porque no cambia nunca:
--   income   ingreso: suma al saldo
--   expense  gasto: resta del saldo
--   transfer transferencia entre dos cuentas del usuario (solo en transacciones)
CREATE TYPE catalog.money_kind AS ENUM ('income', 'expense', 'transfer');
COMMENT ON TYPE catalog.money_kind IS 'income suma al saldo, expense resta, transfer mueve entre dos cuentas propias.';

-- -----------------------------------------------------------------------------
-- Monedas
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.currencies (
  code       char(3)  PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),   -- ISO 4217
  name       text     NOT NULL,
  symbol     text     NOT NULL,
  decimals   smallint NOT NULL DEFAULT 2 CHECK (decimals BETWEEN 0 AND 4),   -- BOB 2, CLP 0
  is_active  boolean  NOT NULL DEFAULT true,     -- false = no se ofrece para cuentas nuevas
  sort_order smallint NOT NULL DEFAULT 100        -- orden en el selector, después de "Mis monedas"
);
COMMENT ON TABLE catalog.currencies IS
  'Monedas ISO 4217 que ofrece la app. Agregar una es un INSERT; desactivarla la oculta para datos nuevos y conserva los existentes.';
COMMENT ON COLUMN catalog.currencies.decimals IS
  'Cuántos decimales acepta un monto en esta moneda: BOB y USD 2, CLP y PYG 0. 1000,5 pesos chilenos se rechaza.';

-- Valida que una moneda esté activa antes de usarla en una cuenta, una meta,
-- la moneda principal o "Mis monedas". Los datos guardados con una moneda que
-- luego se desactiva siguen siendo válidos.
CREATE OR REPLACE FUNCTION catalog.assert_currency_active(p_code char(3)) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM catalog.currencies WHERE code = p_code AND is_active) THEN
    RAISE EXCEPTION 'La moneda % no está disponible', p_code
      USING ERRCODE = 'check_violation', HINT = 'currency_unavailable';
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- Países (ISO 3166-1) e instituciones financieras de cada país
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.countries (
  code       char(2)  PRIMARY KEY CHECK (code ~ '^[A-Z]{2}$'),   -- ISO 3166-1: BO, AR…
  name       text     NOT NULL,
  currency   char(3)  REFERENCES catalog.currencies (code),     -- moneda local
  is_active  boolean  NOT NULL DEFAULT true,
  sort_order smallint NOT NULL DEFAULT 100
);

-- Bancos, cooperativas y billeteras que emiten tarjetas. La app muestra la
-- lista del país del usuario en vez de pedir el nombre del banco como texto.
CREATE TABLE catalog.financial_institutions (
  code         text     PRIMARY KEY CHECK (code ~ '^[a-z]{2}\.[a-z0-9_]+$'),   -- 'bo.bnb'
  country_code char(2)  NOT NULL REFERENCES catalog.countries (code),
  name         text     NOT NULL,                       -- Banco Nacional de Bolivia
  short_name   text     NOT NULL,                       -- BNB
  kind         text     NOT NULL DEFAULT 'bank' CHECK (kind IN ('bank', 'cooperative', 'microfinance', 'fintech')),
  is_active    boolean  NOT NULL DEFAULT true,
  sort_order   smallint NOT NULL DEFAULT 100,
  CONSTRAINT financial_institutions_name_uq UNIQUE (country_code, short_name)
);
CREATE INDEX financial_institutions_country_idx ON catalog.financial_institutions (country_code, sort_order) WHERE is_active;

-- -----------------------------------------------------------------------------
-- Tipos de cuenta: efectivo y tarjeta. "¿Pagué en efectivo o con tarjeta?" se
-- responde con is_card. No se distingue débito de crédito.
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.account_types (
  code       text     PRIMARY KEY CHECK (code ~ '^[a-z_]+$'),
  names      jsonb    NOT NULL CHECK (names ? 'es'),    -- {"es": "Efectivo", "en": "Cash"}
  icon       text     NOT NULL,
  is_card    boolean  NOT NULL DEFAULT false,   -- tarjeta: cuenta para el límite 'finance.cards' del plan
  sort_order smallint NOT NULL DEFAULT 0,
  is_active  boolean  NOT NULL DEFAULT true
);

-- Grupo del Money Flow al que va cada categoría de gasto. Lista fija:
--   needs      Necesidades (alquiler, supermercado, transporte…)
--   lifestyle  Estilo de vida (restaurantes, suscripciones, compras…)
-- Los ingresos no llevan grupo. El nombre y el color que se muestran viven en la app.
CREATE TYPE catalog.flow_group AS ENUM ('needs', 'lifestyle');
COMMENT ON TYPE catalog.flow_group IS 'Grupo de gasto del Money Flow: needs (Necesidades) o lifestyle (Estilo de vida).';

-- -----------------------------------------------------------------------------
-- Plantillas de categorías: se copian a cada usuario nuevo, que puede
-- editarlas sin afectar a otros. Solo categorías, sin subcategorías.
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.category_templates (
  key        text               PRIMARY KEY CHECK (key ~ '^[a-z0-9_]+$'),
  kind       catalog.money_kind NOT NULL CHECK (kind IN ('income', 'expense')),
  flow_group catalog.flow_group,                                          -- solo en gastos
  names      jsonb              NOT NULL CHECK (names ? 'es'),           -- {"es": "Comida", "en": "Food"}
  icon       text               NOT NULL,
  color      text               NOT NULL CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  sort_order smallint           NOT NULL DEFAULT 0,
  is_active  boolean            NOT NULL DEFAULT true,
  CONSTRAINT category_templates_flow_chk CHECK ((kind = 'expense') = (flow_group IS NOT NULL))
);
COMMENT ON TABLE catalog.category_templates IS 'Categorías iniciales (FTR-005, FTR-031). Cada gasto lleva su grupo del Money Flow.';
-- =============================================================================
-- MoneyMap · 020 · iam (identidad y acceso)
-- FTR-001, FTR-024, FTR-025. Solo mayores de 18 años.
-- Los datos financieros son personales: cuelgan directamente del usuario
-- (user_id) y nadie más puede verlos. No hay cuentas compartidas ni roles.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS iam;
COMMENT ON SCHEMA iam IS 'Usuarios, métodos de acceso, sesiones y dispositivos.';

-- Versiones de los términos y la política de privacidad. La vigente es la que
-- se acepta al registrarse; publicar una nueva es un INSERT y un UPDATE.
CREATE TABLE iam.terms_versions (
  version      text        PRIMARY KEY CHECK (length(version) BETWEEN 1 AND 20),   -- '2026-10'
  terms_url    text        NOT NULL,
  privacy_url  text        NOT NULL,
  is_current   boolean     NOT NULL DEFAULT false,
  published_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX terms_versions_current_uq ON iam.terms_versions (is_current) WHERE is_current;
COMMENT ON TABLE iam.terms_versions IS 'Términos y política de privacidad publicados. Solo una versión es la vigente.';

CREATE TABLE iam.users (
  id                      uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  email                   citext      NOT NULL CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  email_verified_at       timestamptz,
  first_name              text        NOT NULL CHECK (length(first_name) BETWEEN 1 AND 60),
  last_name               text        NOT NULL CHECK (length(last_name) BETWEEN 1 AND 60),
  display_name            text        NOT NULL CHECK (length(display_name) BETWEEN 1 AND 120),   -- vacío = first_name
  avatar_object_key       text,                                   -- foto en Cloud Storage
  birth_date              date        NOT NULL,
  phone_e164              text        CHECK (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),          -- +59171234567
  country_code            char(2)     REFERENCES catalog.countries (code),                  -- ISO 3166-1: BO
  city                    text        CHECK (length(city) BETWEEN 1 AND 80),
  occupation              text        CHECK (occupation IN ('student', 'employee', 'self_employed', 'entrepreneur',
                                                          'unemployed', 'retired', 'other')),
  terms_version           text        NOT NULL REFERENCES iam.terms_versions (version),
  terms_accepted_at       timestamptz NOT NULL DEFAULT now(),
  locale                  text        NOT NULL DEFAULT 'es-BO',
  timezone                text        NOT NULL DEFAULT 'America/La_Paz',
  status                  text        NOT NULL DEFAULT 'active'
                                      CHECK (status IN ('active', 'suspended', 'pending_deletion', 'deleted')),
  onboarding_completed_at timestamptz,                            -- el onboarding se muestra una sola vez
  last_login_at           timestamptz,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  deleted_at              timestamptz,
  CONSTRAINT users_adult_chk CHECK (birth_date <= ((created_at AT TIME ZONE 'UTC')::date - INTERVAL '18 years'))
);
CREATE UNIQUE INDEX users_email_uq ON iam.users (email) WHERE deleted_at IS NULL;
CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON iam.users
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE iam.users IS 'Personas usuarias. users_adult_chk exige 18 años cumplidos al registrarse.';
COMMENT ON COLUMN iam.users.occupation IS
  'student (estudiante), employee (empleado), self_employed (independiente), entrepreneur (emprendedor), unemployed (sin empleo), retired (jubilado) u other.';

-- Normaliza el perfil (lo que se devuelve es lo que quedó guardado) y exige los
-- términos vigentes al registrarse.
CREATE OR REPLACE FUNCTION iam.users_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.email        := btrim(NEW.email);
  NEW.first_name   := nullif(regexp_replace(btrim(NEW.first_name), '\s+', ' ', 'g'), '');
  NEW.last_name    := nullif(regexp_replace(btrim(NEW.last_name), '\s+', ' ', 'g'), '');
  NEW.display_name := coalesce(nullif(regexp_replace(btrim(NEW.display_name), '\s+', ' ', 'g'), ''), NEW.first_name);
  NEW.phone_e164   := nullif(regexp_replace(NEW.phone_e164, '[\s().-]', '', 'g'), '');
  NEW.country_code := upper(nullif(btrim(NEW.country_code), ''));
  NEW.city         := nullif(btrim(NEW.city), '');
  IF TG_OP = 'INSERT' AND NOT EXISTS (SELECT 1 FROM iam.terms_versions WHERE version = NEW.terms_version AND is_current) THEN
    RAISE EXCEPTION 'Debes aceptar la versión vigente de los términos (%)',
      (SELECT version FROM iam.terms_versions WHERE is_current)
      USING ERRCODE = 'check_violation', HINT = 'terms_outdated';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER users_before_write BEFORE INSERT OR UPDATE ON iam.users
  FOR EACH ROW EXECUTE FUNCTION iam.users_before_write();

-- Personalización: se guarda en el servidor para que sea igual en todos los
-- dispositivos. Cada usuario nuevo recibe una fila con los valores por defecto.
CREATE TABLE iam.user_preferences (
  user_id        uuid        PRIMARY KEY REFERENCES iam.users (id) ON DELETE CASCADE,
  theme          text        NOT NULL DEFAULT 'system' CHECK (theme IN ('system', 'light', 'dark')),
  accent_color   text        CHECK (accent_color ~ '^#[0-9A-Fa-f]{6}$'),   -- NULL = color de la marca
  hide_amounts   boolean     NOT NULL DEFAULT false,                      -- modo privado
  week_starts_on smallint    NOT NULL DEFAULT 1 CHECK (week_starts_on BETWEEN 0 AND 6),   -- 0 domingo, 1 lunes
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER user_preferences_set_updated_at BEFORE UPDATE ON iam.user_preferences
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE iam.user_preferences IS 'Tema, color de acento, modo privado e inicio de semana de cada usuario.';

-- SECURITY DEFINER: al registrarse todavía no hay app.user_id y la tabla tiene RLS
CREATE OR REPLACE FUNCTION iam.users_create_preferences() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  INSERT INTO iam.user_preferences (user_id) VALUES (NEW.id) ON CONFLICT DO NOTHING;
  RETURN NULL;
END $$;
CREATE TRIGGER users_create_preferences AFTER INSERT ON iam.users
  FOR EACH ROW EXECUTE FUNCTION iam.users_create_preferences();

-- Métodos de acceso: correo y contraseña, Google, Meta y Apple.
CREATE TABLE iam.auth_identities (
  id               uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id          uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  provider         text        NOT NULL CHECK (provider IN ('password', 'google', 'meta', 'apple')),
  provider_subject text        NOT NULL,        -- email para 'password'; 'sub' del proveedor en los demás
  password_hash    text,                        -- argon2id; solo para 'password'
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_used_at     timestamptz,
  CONSTRAINT auth_identities_subject_uq   UNIQUE (provider, provider_subject),
  CONSTRAINT auth_identities_provider_uq  UNIQUE (user_id, provider),
  CONSTRAINT auth_identities_password_chk CHECK ((provider = 'password') = (password_hash IS NOT NULL))
);
COMMENT ON TABLE iam.auth_identities IS 'Un usuario puede entrar con varios métodos; cada uno identifica a un solo usuario.';

CREATE TABLE iam.devices (
  id                uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id           uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  platform          text        NOT NULL CHECK (platform IN ('ios', 'android', 'web')),
  push_token        text,                       -- token de Firebase Cloud Messaging
  app_version       text,
  os_version        text,
  biometric_enabled boolean     NOT NULL DEFAULT false,   -- la biometría la valida el sistema operativo
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  created_at        timestamptz NOT NULL DEFAULT now(),
  revoked_at        timestamptz
);
CREATE UNIQUE INDEX devices_push_token_uq ON iam.devices (push_token) WHERE push_token IS NOT NULL AND revoked_at IS NULL;
CREATE INDEX devices_user_idx ON iam.devices (user_id) WHERE revoked_at IS NULL;
COMMENT ON TABLE iam.devices IS 'Dispositivos del usuario: token push (FTR-023) y si activó biometría (FTR-025).';

-- Refresh tokens con rotación: cada uso crea una sesión nueva y revoca la anterior.
CREATE TABLE iam.sessions (
  id                 uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id            uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  device_id          uuid        REFERENCES iam.devices (id) ON DELETE SET NULL,
  refresh_token_hash text        NOT NULL UNIQUE,
  replaced_by        uuid        REFERENCES iam.sessions (id) ON DELETE SET NULL,
  ip                 inet,
  user_agent         text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL,
  revoked_at         timestamptz,
  CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_active_idx ON iam.sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX sessions_expires_idx ON iam.sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE iam.verification_tokens (
  id         uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id    uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  purpose    text        NOT NULL CHECK (purpose IN ('email_verification', 'password_reset', 'email_change')),
  token_hash text        NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verification_tokens_user_idx ON iam.verification_tokens (user_id, purpose) WHERE used_at IS NULL;
-- =============================================================================
-- MoneyMap · 030 · billing (planes SaaS y suscripciones)
--
-- Un plan gratuito y tres de pago, cada uno con precio mensual y anual.
--   * Sin suscripción con acceso, el usuario está en el plan gratuito. Si deja
--     de pagar o cancela, vuelve a gratuito al terminar el periodo pagado: no
--     se borra ningún dato y puede volver a suscribirse cuando quiera.
--   * Precios y límites son datos (plan_prices, plan_features), no código.
--   * Cada cambio de una suscripción queda en subscription_changes (historial
--     automático) y cada cobro o reembolso de las tiendas en payments.
--
-- Estados de una suscripción
--   trialing      prueba gratis              con acceso al plan de pago
--   active        pagada y vigente           con acceso
--   grace_period  falló el cobro, reintento  con acceso (periodo de gracia)
--   on_hold       cobro fallido sin gracia   sin acceso (vuelve a gratuito)
--   paused        pausada por el usuario     sin acceso (vuelve a gratuito)
--   expired       terminó sin renovar        sin acceso: plan gratuito
--   revoked       reembolsada o revocada     sin acceso: plan gratuito
-- auto_renew = false significa "canceló": conserva el acceso hasta
-- current_period_end y después pasa a expired.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS billing;
COMMENT ON SCHEMA billing IS 'Planes, precios mensuales y anuales, suscripciones, historial, pagos y cuotas de uso.';

-- -----------------------------------------------------------------------------
-- Catálogo de planes y precios
-- -----------------------------------------------------------------------------
CREATE TABLE billing.plans (
  id          uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  code        text        NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_]+$'),
  name        text        NOT NULL,
  description text,
  tier        smallint    NOT NULL UNIQUE CHECK (tier >= 0),   -- 0 = gratuito; mayor = plan superior
  is_public   boolean     NOT NULL DEFAULT true,
  is_active   boolean     NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER plans_set_updated_at BEFORE UPDATE ON billing.plans
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE billing.plans IS 'Planes SaaS. El de tier 0 es el gratuito y no tiene precios.';

-- Un precio por plan, periodo y moneda. Un cambio de precio es una fila nueva:
-- quien ya está suscrito conserva el precio con el que compró.
CREATE TABLE billing.plan_prices (
  id                    uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  plan_id               uuid          NOT NULL REFERENCES billing.plans (id),
  billing_period        text          NOT NULL CHECK (billing_period IN ('month', 'year')),
  currency              char(3)       NOT NULL REFERENCES catalog.currencies (code),
  amount                numeric(12,2) NOT NULL CHECK (amount > 0),
  trial_days            smallint      NOT NULL DEFAULT 0 CHECK (trial_days BETWEEN 0 AND 90),
  app_store_product_id  text,                       -- producto de App Store
  play_store_product_id text,                       -- producto y plan base de Google Play
  web_price_id          text,                       -- pasarela web, si algún día se cobra fuera de las tiendas
  is_active             boolean       NOT NULL DEFAULT true,
  valid_from            timestamptz   NOT NULL DEFAULT now(),
  valid_until           timestamptz,
  created_at            timestamptz   NOT NULL DEFAULT now(),
  CONSTRAINT plan_prices_id_plan_period_uq UNIQUE (id, plan_id, billing_period),
  CONSTRAINT plan_prices_validity_chk      CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE UNIQUE INDEX plan_prices_active_uq     ON billing.plan_prices (plan_id, billing_period, currency) WHERE is_active;
CREATE UNIQUE INDEX plan_prices_app_store_uq  ON billing.plan_prices (app_store_product_id)  WHERE app_store_product_id IS NOT NULL AND is_active;
CREATE UNIQUE INDEX plan_prices_play_store_uq ON billing.plan_prices (play_store_product_id) WHERE play_store_product_id IS NOT NULL AND is_active;
COMMENT ON TABLE billing.plan_prices IS 'Precio mensual y anual de cada plan de pago, con los productos de cada tienda.';

CREATE TABLE billing.features (
  key          text PRIMARY KEY CHECK (key ~ '^[a-z0-9_.]+$'),   -- 'ai.voice_entries'
  description  text NOT NULL,
  value_type   text NOT NULL CHECK (value_type IN ('boolean', 'limit')),
  limit_period text CHECK (limit_period IN ('total', 'month')),
  CHECK ((value_type = 'limit') = (limit_period IS NOT NULL))
);
COMMENT ON TABLE billing.features IS
  'Funcionalidades que un plan habilita o limita. total = recursos vivos (tarjetas, metas); month = usos en el mes.';

CREATE TABLE billing.plan_features (
  plan_id     uuid    NOT NULL REFERENCES billing.plans (id) ON DELETE CASCADE,
  feature_key text    NOT NULL REFERENCES billing.features (key),
  is_enabled  boolean NOT NULL DEFAULT true,
  limit_value integer CHECK (limit_value >= 0),    -- NULL = ilimitado
  PRIMARY KEY (plan_id, feature_key)
);

-- -----------------------------------------------------------------------------
-- Suscripciones
-- -----------------------------------------------------------------------------
CREATE TABLE billing.subscriptions (
  id                       uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id                  uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  plan_id                  uuid        NOT NULL,
  plan_price_id            uuid        NOT NULL,
  billing_period           text        NOT NULL CHECK (billing_period IN ('month', 'year')),
  status                   text        NOT NULL CHECK (status IN ('trialing', 'active', 'grace_period', 'on_hold',
                                                                  'paused', 'expired', 'revoked')),
  provider                 text        NOT NULL CHECK (provider IN ('app_store', 'play_store', 'web', 'internal')),
  provider_subscription_id text,       -- original_transaction_id (App Store) o purchase token (Play)
  auto_renew               boolean     NOT NULL DEFAULT true,          -- false = el usuario canceló
  started_at               timestamptz NOT NULL DEFAULT now(),
  trial_ends_at            timestamptz,
  current_period_start     timestamptz NOT NULL DEFAULT now(),
  current_period_end       timestamptz NOT NULL,                        -- acceso pagado hasta aquí
  grace_period_ends_at     timestamptz,
  pending_plan_price_id    uuid        REFERENCES billing.plan_prices (id),   -- cambio programado
  pending_change_at        timestamptz,
  canceled_at              timestamptz,                                 -- cuándo apagó la renovación
  cancel_reason            text        CHECK (cancel_reason IN ('user', 'billing_error', 'refund',
                                                               'price_increase_declined', 'replaced', 'other')),
  ended_at                 timestamptz,                                 -- cuándo perdió el acceso
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT subscriptions_plan_fk     FOREIGN KEY (plan_id) REFERENCES billing.plans (id),
  -- el precio debe ser de ese plan y de ese periodo
  CONSTRAINT subscriptions_price_fk    FOREIGN KEY (plan_price_id, plan_id, billing_period)
                                       REFERENCES billing.plan_prices (id, plan_id, billing_period),
  CONSTRAINT subscriptions_provider_uq UNIQUE (provider, provider_subscription_id),
  CONSTRAINT subscriptions_period_chk  CHECK (current_period_end > current_period_start),
  CONSTRAINT subscriptions_pending_chk CHECK ((pending_plan_price_id IS NULL) = (pending_change_at IS NULL)),
  CONSTRAINT subscriptions_ended_chk   CHECK ((status IN ('expired', 'revoked')) = (ended_at IS NOT NULL))
);
-- Una sola suscripción viva por usuario. Al expirar, puede crear otra o reactivar la misma.
CREATE UNIQUE INDEX subscriptions_one_live_uq ON billing.subscriptions (user_id)
  WHERE status IN ('trialing', 'active', 'grace_period', 'on_hold', 'paused');
CREATE INDEX subscriptions_period_end_idx ON billing.subscriptions (current_period_end)
  WHERE status IN ('trialing', 'active', 'grace_period');
CREATE INDEX subscriptions_user_idx ON billing.subscriptions (user_id, created_at DESC);
COMMENT ON TABLE billing.subscriptions IS 'Suscripción de un usuario a un plan de pago, mensual o anual.';

-- Mantiene canceled_at, ended_at y el cierre de suscripciones terminadas.
CREATE OR REPLACE FUNCTION billing.subscriptions_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.auto_renew IS DISTINCT FROM OLD.auto_renew THEN
    IF NEW.auto_renew THEN
      NEW.canceled_at   := NULL;
      NEW.cancel_reason := NULL;
    ELSE
      NEW.canceled_at   := coalesce(NEW.canceled_at, now());
      NEW.cancel_reason := coalesce(NEW.cancel_reason, 'user');
    END IF;
  END IF;

  IF NEW.status IN ('expired', 'revoked') THEN
    NEW.ended_at              := coalesce(NEW.ended_at, least(now(), NEW.current_period_end));
    NEW.pending_plan_price_id := NULL;
    NEW.pending_change_at     := NULL;
  ELSE
    NEW.ended_at := NULL;            -- reactivación de la misma suscripción (App Store)
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER subscriptions_before_write BEFORE INSERT OR UPDATE ON billing.subscriptions
  FOR EACH ROW EXECUTE FUNCTION billing.subscriptions_before_write();
CREATE TRIGGER subscriptions_set_updated_at BEFORE UPDATE ON billing.subscriptions
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER subscriptions_audit AFTER INSERT OR UPDATE OR DELETE ON billing.subscriptions
  FOR EACH ROW EXECUTE FUNCTION core.audit_row_change();

-- -----------------------------------------------------------------------------
-- Historial de suscripciones: lo escribe un trigger, nadie lo edita
-- -----------------------------------------------------------------------------
CREATE TABLE billing.subscription_changes (
  seq             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  subscription_id uuid        REFERENCES billing.subscriptions (id) ON DELETE SET NULL,
  change_type     text        NOT NULL CHECK (change_type IN (
                    'started', 'trial_started', 'trial_converted', 'renewed',
                    'upgraded', 'downgraded', 'period_changed',
                    'change_scheduled', 'change_canceled',
                    'auto_renew_disabled', 'auto_renew_enabled',
                    'grace_period_started', 'on_hold', 'paused', 'resumed', 'recovered',
                    'expired', 'revoked', 'resubscribed', 'reverted_to_free', 'status_changed')),
  from_plan_id    uuid        REFERENCES billing.plans (id),
  to_plan_id      uuid        REFERENCES billing.plans (id),
  from_price_id   uuid        REFERENCES billing.plan_prices (id),
  to_price_id     uuid        REFERENCES billing.plan_prices (id),
  from_period     text,
  to_period       text,
  from_status     text,
  to_status       text,
  source          text        NOT NULL DEFAULT 'system'
                              CHECK (source IN ('store_webhook', 'user', 'admin', 'job', 'system')),
  effective_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX subscription_changes_user_idx ON billing.subscription_changes (user_id, seq DESC);
CREATE INDEX subscription_changes_type_idx ON billing.subscription_changes (change_type, effective_at DESC);
COMMENT ON TABLE billing.subscription_changes IS
  'Historial del plan de cada usuario: altas, cambios de plan o de mensual a anual, cancelaciones y vuelta a gratuito.';

CREATE OR REPLACE FUNCTION billing.log_subscription_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_source       text := coalesce(nullif(current_setting('app.change_source', true), ''), 'system');
  v_types        text[] := '{}';
  v_from_tier    smallint;
  v_to_tier      smallint;
  v_pending_plan uuid;
BEGIN
  IF TG_OP = 'INSERT' THEN
    v_types := ARRAY[CASE WHEN NEW.status = 'trialing' THEN 'trial_started' ELSE 'started' END];
  ELSE
    -- Plan o periodo
    IF NEW.plan_id IS DISTINCT FROM OLD.plan_id THEN
      SELECT tier INTO v_from_tier FROM billing.plans WHERE id = OLD.plan_id;
      SELECT tier INTO v_to_tier   FROM billing.plans WHERE id = NEW.plan_id;
      v_types := v_types || CASE WHEN v_to_tier > v_from_tier THEN 'upgraded' ELSE 'downgraded' END;
    ELSIF NEW.billing_period IS DISTINCT FROM OLD.billing_period THEN
      v_types := v_types || 'period_changed'::text;
    ELSIF NEW.current_period_end > OLD.current_period_end AND OLD.status = 'active' AND NEW.status = 'active' THEN
      v_types := v_types || 'renewed'::text;
    END IF;

    -- Estado
    IF NEW.status IS DISTINCT FROM OLD.status THEN
      v_types := v_types || CASE
        WHEN OLD.status IN ('expired', 'revoked')      THEN 'resubscribed'
        WHEN OLD.status = 'trialing' AND NEW.status = 'active' THEN 'trial_converted'
        WHEN OLD.status = 'paused' AND NEW.status = 'active'   THEN 'resumed'
        WHEN OLD.status IN ('grace_period', 'on_hold') AND NEW.status = 'active' THEN 'recovered'
        WHEN NEW.status = 'grace_period' THEN 'grace_period_started'
        WHEN NEW.status = 'on_hold'      THEN 'on_hold'
        WHEN NEW.status = 'paused'       THEN 'paused'
        WHEN NEW.status = 'expired'      THEN 'expired'
        WHEN NEW.status = 'revoked'      THEN 'revoked'
        ELSE 'status_changed' END;

      IF NEW.status IN ('expired', 'revoked') AND NOT EXISTS (
           SELECT 1 FROM billing.subscriptions s
           WHERE s.user_id = NEW.user_id AND s.id <> NEW.id
             AND s.status IN ('trialing', 'active', 'grace_period', 'on_hold', 'paused')) THEN
        v_types := v_types || 'reverted_to_free'::text;
      END IF;
    END IF;

    -- Renovación automática (cancelar o reactivar)
    IF NEW.auto_renew IS DISTINCT FROM OLD.auto_renew THEN
      v_types := v_types || CASE WHEN NEW.auto_renew THEN 'auto_renew_enabled' ELSE 'auto_renew_disabled' END;
    END IF;

    -- Cambio programado para el fin del periodo
    IF NEW.pending_plan_price_id IS DISTINCT FROM OLD.pending_plan_price_id THEN
      IF NEW.pending_plan_price_id IS NOT NULL THEN
        v_types := v_types || 'change_scheduled'::text;
        SELECT plan_id INTO v_pending_plan FROM billing.plan_prices WHERE id = NEW.pending_plan_price_id;
      ELSIF NEW.plan_price_id IS NOT DISTINCT FROM OLD.plan_price_id AND NEW.status NOT IN ('expired', 'revoked') THEN
        v_types := v_types || 'change_canceled'::text;
      END IF;
    END IF;
  END IF;

  INSERT INTO billing.subscription_changes
         (user_id, subscription_id, change_type, from_plan_id, to_plan_id, from_price_id, to_price_id,
          from_period, to_period, from_status, to_status, source)
  SELECT NEW.user_id, NEW.id, t.change_type,
         CASE WHEN TG_OP = 'UPDATE' THEN OLD.plan_id END,
         CASE WHEN t.change_type = 'change_scheduled' THEN v_pending_plan ELSE NEW.plan_id END,
         CASE WHEN TG_OP = 'UPDATE' THEN OLD.plan_price_id END,
         CASE WHEN t.change_type = 'change_scheduled' THEN NEW.pending_plan_price_id ELSE NEW.plan_price_id END,
         CASE WHEN TG_OP = 'UPDATE' THEN OLD.billing_period END,
         NEW.billing_period,
         CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END,
         NEW.status,
         v_source
  FROM unnest(v_types) WITH ORDINALITY AS t (change_type, ord)
  ORDER BY t.ord;
  RETURN NULL;
END $$;

CREATE TRIGGER subscriptions_log_change AFTER INSERT OR UPDATE ON billing.subscriptions
  FOR EACH ROW EXECUTE FUNCTION billing.log_subscription_change();

-- -----------------------------------------------------------------------------
-- Pagos y reembolsos informados por las tiendas
-- -----------------------------------------------------------------------------
CREATE TABLE billing.payments (
  id                      uuid          PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id                 uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  subscription_id         uuid          REFERENCES billing.subscriptions (id) ON DELETE SET NULL,
  plan_price_id           uuid          REFERENCES billing.plan_prices (id),
  provider                text          NOT NULL CHECK (provider IN ('app_store', 'play_store', 'web', 'internal')),
  provider_transaction_id text          NOT NULL,
  kind                    text          NOT NULL CHECK (kind IN ('initial', 'renewal', 'upgrade', 'refund', 'chargeback')),
  status                  text          NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
  amount                  numeric(12,2) NOT NULL,                           -- negativo en reembolsos
  currency                char(3)       NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),   -- moneda local cobrada por la tienda
  billing_period          text          CHECK (billing_period IN ('month', 'year')),
  period_start            timestamptz,
  period_end              timestamptz,
  store_fee               numeric(12,2),                                    -- comisión de la tienda, si se conoce
  occurred_at             timestamptz   NOT NULL DEFAULT now(),
  created_at              timestamptz   NOT NULL DEFAULT now(),
  CONSTRAINT payments_provider_uq UNIQUE (provider, provider_transaction_id)
);
CREATE INDEX payments_user_idx         ON billing.payments (user_id, occurred_at DESC);
CREATE INDEX payments_subscription_idx ON billing.payments (subscription_id, occurred_at DESC);
COMMENT ON TABLE billing.payments IS 'Cada cobro, renovación o reembolso. La clave única evita registrar dos veces el mismo cobro.';

-- Notificaciones crudas de App Store / Play Store. La clave única hace idempotente el procesamiento.
CREATE TABLE billing.subscription_events (
  id                uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  subscription_id   uuid        REFERENCES billing.subscriptions (id) ON DELETE SET NULL,
  provider          text        NOT NULL,
  provider_event_id text        NOT NULL,
  event_type        text        NOT NULL,
  payload           jsonb       NOT NULL,
  received_at       timestamptz NOT NULL DEFAULT now(),
  processed_at      timestamptz,
  error             text,
  CONSTRAINT subscription_events_uq UNIQUE (provider, provider_event_id)
);
CREATE INDEX subscription_events_pending_idx ON billing.subscription_events (received_at) WHERE processed_at IS NULL;

-- Usos mensuales (registros por voz, Can I Afford It?)
CREATE TABLE billing.usage_counters (
  user_id      uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  feature_key  text        NOT NULL REFERENCES billing.features (key),
  period_start date        NOT NULL,     -- 1.er día del mes
  used         integer     NOT NULL DEFAULT 0 CHECK (used >= 0),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, feature_key, period_start)
);

-- -----------------------------------------------------------------------------
-- Plan vigente, límites y uso
-- -----------------------------------------------------------------------------

-- Recursos vivos que cuentan contra un límite 'total'. Se cuentan, no se
-- acumulan: al borrar o archivar una tarjeta, el usuario recupera el cupo.
--   finance.cards       tarjetas activas
--   finance.currencies  monedas distintas entre sus cuentas activas
--   goals.active        metas activas
CREATE OR REPLACE FUNCTION billing.resource_usage(p_user uuid, p_feature text) RETURNS integer
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  CASE p_feature
    WHEN 'finance.cards' THEN
      RETURN (SELECT count(*) FROM finance.accounts a
              JOIN catalog.account_types t ON t.code = a.type AND t.is_card
              WHERE a.user_id = p_user AND a.deleted_at IS NULL AND a.archived_at IS NULL);
    WHEN 'finance.currencies' THEN
      RETURN (SELECT count(DISTINCT a.currency) FROM finance.accounts a
              WHERE a.user_id = p_user AND a.deleted_at IS NULL AND a.archived_at IS NULL);
    WHEN 'goals.active' THEN
      RETURN (SELECT count(*) FROM goals.goals g
              WHERE g.user_id = p_user AND g.deleted_at IS NULL AND g.status = 'active');
    ELSE
      RETURN 0;
  END CASE;
END $$;

-- Plan efectivo de cada usuario. Sin suscripción con acceso = plan gratuito.
CREATE VIEW billing.user_plans AS
SELECT u.id                                                   AS user_id,
       p.id                                                   AS plan_id,
       p.code                                                 AS plan_code,
       p.tier,
       coalesce(s.status, 'free')                             AS status,
       coalesce(s.status IN ('trialing', 'active', 'grace_period'), false) AS has_paid_access,
       s.id                                                   AS subscription_id,
       s.billing_period,
       s.current_period_end,
       s.auto_renew,
       s.pending_plan_price_id
FROM iam.users u
LEFT JOIN billing.subscriptions s
       ON s.user_id = u.id AND s.status IN ('trialing', 'active', 'grace_period', 'on_hold', 'paused')
LEFT JOIN LATERAL (
  SELECT f.id FROM billing.plans f WHERE f.tier = 0 AND f.is_active ORDER BY f.created_at LIMIT 1
) free ON true
JOIN billing.plans p
  ON p.id = CASE WHEN s.status IN ('trialing', 'active', 'grace_period') THEN s.plan_id ELSE free.id END;
COMMENT ON VIEW billing.user_plans IS
  'Plan efectivo. on_hold y paused muestran su estado pero dan el plan gratuito hasta que se recupere el pago.';

CREATE VIEW billing.user_entitlements AS
SELECT up.user_id,
       f.key                              AS feature_key,
       f.value_type,
       f.limit_period,
       coalesce(pf.is_enabled, false)     AS is_enabled,
       pf.limit_value,
       CASE f.limit_period
         WHEN 'total' THEN billing.resource_usage(up.user_id, f.key)
         WHEN 'month' THEN coalesce(uc.used, 0)
       END                                AS used_in_period
FROM billing.user_plans up
CROSS JOIN billing.features f
LEFT JOIN billing.plan_features pf
       ON pf.plan_id = up.plan_id AND pf.feature_key = f.key
LEFT JOIN billing.usage_counters uc
       ON uc.user_id = up.user_id AND uc.feature_key = f.key
      AND uc.period_start = date_trunc('month', now())::date;
COMMENT ON VIEW billing.user_entitlements IS 'Qué puede hacer cada usuario según su plan y cuánto lleva usado.';

-- Para la pantalla de planes: precio mensual, anual y ahorro de pagar el año
CREATE VIEW billing.price_catalog AS
SELECT p.code                                           AS plan_code,
       p.name,
       p.tier,
       m.currency,
       m.amount                                         AS monthly_amount,
       y.amount                                         AS yearly_amount,
       round(y.amount / 12, 2)                          AS yearly_per_month,
       round(100 * (1 - y.amount / (m.amount * 12)), 1) AS yearly_saving_pct,
       m.id                                             AS monthly_price_id,
       y.id                                             AS yearly_price_id
FROM billing.plans p
JOIN billing.plan_prices m
  ON m.plan_id = p.id AND m.billing_period = 'month' AND m.is_active
LEFT JOIN billing.plan_prices y
  ON y.plan_id = p.id AND y.billing_period = 'year' AND y.is_active AND y.currency = m.currency
WHERE p.is_active AND p.is_public;

-- Estado de un límite: para la API ("2 de 2 tarjetas") y para decidir si se permite crear
CREATE OR REPLACE FUNCTION billing.limit_status(p_user uuid, p_feature text)
RETURNS TABLE (is_enabled boolean, limit_value integer, used integer, remaining integer, allowed boolean)
LANGUAGE sql STABLE AS $$
  SELECT e.is_enabled,
         e.limit_value,
         e.used_in_period,
         CASE WHEN e.limit_value IS NOT NULL THEN greatest(e.limit_value - coalesce(e.used_in_period, 0), 0) END,
         e.is_enabled AND (e.limit_value IS NULL OR coalesce(e.used_in_period, 0) < e.limit_value)
  FROM billing.user_entitlements e
  WHERE e.user_id = p_user AND e.feature_key = p_feature
$$;

-- Antes de crear un recurso o usar una cuota: true si el plan lo permite.
--   'month' descuenta un uso de forma atómica (varias instancias de la API).
--   'total' compara con los recursos vivos; crear el recurso es lo que lo cuenta.
CREATE OR REPLACE FUNCTION billing.try_consume(p_user uuid, p_feature text, p_amount int DEFAULT 1)
RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
  v_enabled boolean;
  v_limit   int;
  v_period  text;
  v_used    int;
  v_start   date := date_trunc('month', now())::date;
BEGIN
  SELECT e.is_enabled, e.limit_value, e.limit_period, e.used_in_period
    INTO v_enabled, v_limit, v_period, v_used
  FROM billing.user_entitlements e
  WHERE e.user_id = p_user AND e.feature_key = p_feature;

  IF NOT FOUND OR NOT v_enabled THEN
    RETURN false;
  END IF;
  IF v_period IS NULL THEN
    RETURN true;                                    -- funcionalidad booleana
  END IF;
  IF v_period = 'total' THEN
    RETURN v_limit IS NULL OR v_used + p_amount <= v_limit;
  END IF;

  INSERT INTO billing.usage_counters (user_id, feature_key, period_start, used)
  VALUES (p_user, p_feature, v_start, 0)
  ON CONFLICT DO NOTHING;

  UPDATE billing.usage_counters
     SET used = used + p_amount, updated_at = now()
   WHERE user_id = p_user AND feature_key = p_feature AND period_start = v_start
     AND (v_limit IS NULL OR used + p_amount <= v_limit);
  RETURN FOUND;
END $$;
COMMENT ON FUNCTION billing.try_consume(uuid, text, int) IS
  'true si el plan permite la acción. Tras bajar a gratuito, los datos existentes se conservan pero no se pueden crear más por encima del límite.';

-- Devuelve usos del mes cuando la acción no se completó por un fallo nuestro
-- (por ejemplo, un dictado en el que fallaron todos los proveedores de IA).
CREATE OR REPLACE FUNCTION billing.release(p_user uuid, p_feature text, p_amount int DEFAULT 1)
RETURNS void
LANGUAGE sql AS $$
  UPDATE billing.usage_counters
     SET used = greatest(used - p_amount, 0), updated_at = now()
   WHERE user_id = p_user
     AND feature_key = p_feature
     AND period_start = date_trunc('month', now())::date;
$$;
COMMENT ON FUNCTION billing.release(uuid, text, int) IS
  'Revierte try_consume en el mes actual. No baja de 0.';

-- -----------------------------------------------------------------------------
-- Job periódico (Celery Beat, cada hora): cierra periodos vencidos
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION billing.process_due_subscriptions(p_now timestamptz DEFAULT now())
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  v_prev  text := current_setting('app.change_source', true);
  v_count int  := 0;
  v_rows  int;
BEGIN
  PERFORM set_config('app.change_source', 'job', true);

  -- 1) Cambios programados en proveedores propios (en las tiendas los aplica su webhook)
  UPDATE billing.subscriptions s
     SET plan_price_id         = pp.id,
         plan_id               = pp.plan_id,
         billing_period        = pp.billing_period,
         pending_plan_price_id = NULL,
         pending_change_at     = NULL
    FROM billing.plan_prices pp
   WHERE pp.id = s.pending_plan_price_id
     AND s.pending_change_at <= p_now
     AND s.provider IN ('web', 'internal')
     AND s.status IN ('trialing', 'active', 'grace_period');
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;

  -- 2) Canceladas cuyo periodo pagado terminó: pasan a expired y el usuario vuelve a gratuito
  UPDATE billing.subscriptions
     SET status = 'expired', ended_at = current_period_end
   WHERE status IN ('trialing', 'active') AND NOT auto_renew AND current_period_end <= p_now;
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;

  -- 3) Periodo de gracia vencido sin pago: on_hold (sin acceso hasta que pague)
  UPDATE billing.subscriptions
     SET status = 'on_hold'
   WHERE status = 'grace_period' AND grace_period_ends_at <= p_now;
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;

  PERFORM set_config('app.change_source', coalesce(v_prev, ''), true);
  RETURN v_count;
END $$;
COMMENT ON FUNCTION billing.process_due_subscriptions(timestamptz) IS
  'Aplica cambios programados, expira suscripciones canceladas al terminar su periodo y pasa a on_hold las de gracia vencida.';
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
-- =============================================================================
-- MoneyMap · 080 · notify (notificaciones push)
-- FTR-023. El usuario elige qué avisos recibe; los avisos de seguridad y de
-- suscripción no se pueden desactivar.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS notify;
COMMENT ON SCHEMA notify IS 'Tipos de aviso, preferencias del usuario y bandeja de notificaciones.';

CREATE TABLE notify.notification_types (
  key              text    PRIMARY KEY CHECK (key ~ '^[a-z0-9_.]+$'),   -- 'recurring.due_soon'
  description      text    NOT NULL,
  default_enabled  boolean NOT NULL DEFAULT true,
  is_transactional boolean NOT NULL DEFAULT false      -- true = no se puede desactivar
);

CREATE TABLE notify.preferences (
  user_id    uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  type_key   text        NOT NULL REFERENCES notify.notification_types (key),
  channel    text        NOT NULL DEFAULT 'push' CHECK (channel IN ('push', 'email', 'in_app')),
  is_enabled boolean     NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, type_key, channel)
);
COMMENT ON TABLE notify.preferences IS 'Solo guarda lo que el usuario cambió; sin fila se usa default_enabled.';

-- Preferencia efectiva (lo que eligió el usuario o el valor por defecto)
CREATE OR REPLACE FUNCTION notify.is_enabled(p_user uuid, p_type text, p_channel text DEFAULT 'push')
RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN t.is_transactional THEN true
              ELSE coalesce(p.is_enabled, t.default_enabled) END
  FROM notify.notification_types t
  LEFT JOIN notify.preferences p
         ON p.user_id = p_user AND p.type_key = t.key AND p.channel = p_channel
  WHERE t.key = p_type
$$;

-- Bandeja y registro de envíos. Alto volumen: particionada por mes con retención.
CREATE TABLE notify.notifications (
  id            uuid        NOT NULL DEFAULT core.uuid_v7(),
  created_at    timestamptz NOT NULL DEFAULT now(),
  user_id       uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  type_key      text        NOT NULL REFERENCES notify.notification_types (key),
  channel       text        NOT NULL DEFAULT 'push' CHECK (channel IN ('push', 'email', 'in_app')),
  title         text        NOT NULL CHECK (length(title) <= 120),
  body          text        NOT NULL CHECK (length(body) <= 500),
  data          jsonb       NOT NULL DEFAULT '{}',      -- deep link e ids relacionados
  dedupe_key    text,                                   -- p. ej. 'recurring:<id>:2026-10'
  status        text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'skipped', 'read')),
  scheduled_for timestamptz NOT NULL DEFAULT now(),
  sent_at       timestamptz,
  read_at       timestamptz,
  error         text,
  PRIMARY KEY (created_at, id)
) PARTITION BY RANGE (created_at);
CREATE TABLE notify.notifications_default PARTITION OF notify.notifications DEFAULT;
CREATE INDEX notifications_user_idx    ON notify.notifications (user_id, created_at DESC);
CREATE INDEX notifications_pending_idx ON notify.notifications (scheduled_for) WHERE status = 'queued';
CREATE INDEX notifications_dedupe_idx  ON notify.notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
-- =============================================================================
-- MoneyMap · 090 · ai (registro por voz con LLM)
-- FTR-007. El usuario dice "gasté 50 en comida": un modelo de voz a texto
-- transcribe y un LLM extrae tipo, monto, moneda, categoría, cuenta, descripción y fecha.
--
-- Varios proveedores por tarea: uno principal y los demás de respaldo.
--   ai.tasks         qué hace la IA (transcribir, extraer) y qué tipo de modelo pide
--   ai.models        catálogo de modelos con sus precios (OpenAI, DeepSeek, Anthropic…)
--   ai.routes        orden por tarea: posición 1 = principal, 2+ = respaldos
--   ai.route_changes quién cambió el orden, cuándo y por qué
--   ai.calls         cada llamada a un proveedor, exitosa o fallida (por mes)
--   ai.voice_entries cada dictado y su resultado (por mes)
-- Cambiar el principal es ai.set_route_order(...): no hay que desplegar código.
-- El audio no se guarda por defecto (privacidad).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ai;
COMMENT ON SCHEMA ai IS 'Registro por voz con IA: proveedores con respaldo, cada llamada, costo y resultado.';

-- -----------------------------------------------------------------------------
-- Tareas
-- -----------------------------------------------------------------------------
CREATE TABLE ai.tasks (
  key          text        PRIMARY KEY CHECK (key ~ '^[a-z0-9_]+\.[a-z0-9_]+$'),   -- 'voice.transcribe'
  model_kind   text        NOT NULL CHECK (model_kind IN ('stt', 'llm', 'audio_llm', 'vision_llm')),
  description  text        NOT NULL
);
COMMENT ON TABLE ai.tasks IS 'Cada paso que hace la IA. FTR-030 (facturas) sería una tarea nueva, sin cambiar tablas.';

-- -----------------------------------------------------------------------------
-- Modelos y precios (USD). Se actualizan con un UPDATE cuando el proveedor cambia precios.
-- -----------------------------------------------------------------------------
CREATE TABLE ai.models (
  code                      text          PRIMARY KEY CHECK (code ~ '^[a-z0-9_]+\.[a-z0-9._-]+$'),  -- 'openai.gpt-transcribe'
  provider                  text          NOT NULL CHECK (provider ~ '^[a-z0-9_]+$'),                -- 'openai', 'deepseek'…
  model                     text          NOT NULL,                                                  -- id que espera la API
  kind                      text          NOT NULL CHECK (kind IN ('stt', 'llm', 'audio_llm', 'vision_llm')),
  price_per_minute_usd      numeric(12,6) CHECK (price_per_minute_usd >= 0),        -- voz a texto
  min_billed_seconds        numeric(6,2)  NOT NULL DEFAULT 0 CHECK (min_billed_seconds >= 0),
  input_per_mtok_usd        numeric(12,6) CHECK (input_per_mtok_usd >= 0),          -- LLM
  cached_input_per_mtok_usd numeric(12,6) CHECK (cached_input_per_mtok_usd >= 0),
  output_per_mtok_usd       numeric(12,6) CHECK (output_per_mtok_usd >= 0),
  is_active                 boolean       NOT NULL DEFAULT true,     -- false = no se usa aunque esté en una ruta
  shutdown_on               date,                                    -- fecha de retiro anunciada por el proveedor
  prices_checked_on         date          NOT NULL,
  notes                     text,
  created_at                timestamptz   NOT NULL DEFAULT now(),
  updated_at                timestamptz   NOT NULL DEFAULT now(),
  CONSTRAINT models_provider_model_uq UNIQUE (provider, model),
  CONSTRAINT models_prices_chk CHECK (
    CASE kind WHEN 'stt' THEN price_per_minute_usd IS NOT NULL
              ELSE input_per_mtok_usd IS NOT NULL AND output_per_mtok_usd IS NOT NULL END)
);
CREATE TRIGGER models_set_updated_at BEFORE UPDATE ON ai.models
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE ai.models IS 'Modelos disponibles y su precio. Agregar un proveedor es un INSERT aquí y una ruta.';

-- -----------------------------------------------------------------------------
-- Rutas: principal y respaldos por tarea
-- -----------------------------------------------------------------------------
CREATE TABLE ai.routes (
  task         text        NOT NULL REFERENCES ai.tasks (key),
  position     smallint    NOT NULL CHECK (position > 0),           -- 1 = principal
  model_code   text        NOT NULL REFERENCES ai.models (code),
  is_active    boolean     NOT NULL DEFAULT true,
  timeout_ms   integer     NOT NULL DEFAULT 8000 CHECK (timeout_ms BETWEEN 500 AND 60000),
  max_retries  smallint    NOT NULL DEFAULT 1 CHECK (max_retries BETWEEN 0 AND 3),   -- reintentos antes de pasar al siguiente
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (task, position),
  CONSTRAINT routes_task_model_uq UNIQUE (task, model_code)
);
CREATE TRIGGER routes_set_updated_at BEFORE UPDATE ON ai.routes
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE ai.routes IS 'Orden de proveedores por tarea. El worker prueba la posición 1 y, si falla, la 2, la 3…';

-- El modelo debe ser del tipo que pide la tarea (no se puede poner un LLM a transcribir)
CREATE OR REPLACE FUNCTION ai.routes_check_kind() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_need text;
  v_kind text;
BEGIN
  SELECT model_kind INTO v_need FROM ai.tasks WHERE key = NEW.task;
  SELECT kind INTO v_kind FROM ai.models WHERE code = NEW.model_code;
  IF v_kind IS DISTINCT FROM v_need THEN
    RAISE EXCEPTION 'La tarea % necesita un modelo %; % es %', NEW.task, v_need, NEW.model_code, v_kind
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER routes_check_kind BEFORE INSERT OR UPDATE OF task, model_code ON ai.routes
  FOR EACH ROW EXECUTE FUNCTION ai.routes_check_kind();

CREATE TABLE ai.route_changes (
  id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task        text        NOT NULL REFERENCES ai.tasks (key),
  changed_at  timestamptz NOT NULL DEFAULT now(),
  changed_by  text        NOT NULL,
  old_order   text[]      NOT NULL,
  new_order   text[]      NOT NULL,
  reason      text
);
COMMENT ON TABLE ai.route_changes IS 'Historial de cambios de principal y respaldos.';

-- Orden vigente de una tarea: lo lee el worker (puede cachearlo 60 s)
CREATE OR REPLACE FUNCTION ai.route(p_task text)
RETURNS TABLE (pos smallint, model_code text, provider text, model text, timeout_ms integer, max_retries smallint)
LANGUAGE sql STABLE AS $$
  SELECT r.position, r.model_code, m.provider, m.model, r.timeout_ms, r.max_retries
  FROM ai.routes r
  JOIN ai.models m ON m.code = r.model_code
  WHERE r.task = p_task AND r.is_active AND m.is_active
    AND (m.shutdown_on IS NULL OR m.shutdown_on > current_date)
  ORDER BY r.position;
$$;

-- Cambia el orden de una tarea de una vez. Los modelos que no se nombran quedan
-- al final, desactivados. Ejemplo:
--   SELECT set_config('app.actor', 'dana@moneymap.team', true);
--   SELECT ai.set_route_order('voice.extract',
--            ARRAY['deepseek.deepseek-flash', 'openai.gpt-6-luna'], 'OpenAI con errores 503');
CREATE OR REPLACE FUNCTION ai.set_route_order(p_task text, p_models text[], p_reason text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  v_old   text[];
  v_new   text[];
  v_actor text := coalesce(nullif(current_setting('app.actor', true), ''), session_user::text);
  i       int;
BEGIN
  IF p_models IS NULL OR cardinality(p_models) = 0 THEN
    RAISE EXCEPTION 'Indica al menos un modelo para %', p_task USING ERRCODE = 'invalid_parameter_value';
  END IF;
  IF (SELECT count(DISTINCT m) FROM unnest(p_models) m) <> cardinality(p_models) THEN
    RAISE EXCEPTION 'Hay modelos repetidos' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  PERFORM 1 FROM ai.routes WHERE task = p_task FOR UPDATE;
  SELECT coalesce(array_agg(model_code ORDER BY position) FILTER (WHERE is_active), '{}')
    INTO v_old FROM ai.routes WHERE task = p_task;

  UPDATE ai.routes SET position = position + 1000 WHERE task = p_task;

  FOR i IN 1 .. cardinality(p_models) LOOP
    INSERT INTO ai.routes (task, position, model_code, is_active)
    VALUES (p_task, i, p_models[i], true)
    ON CONFLICT (task, model_code) DO UPDATE SET position = EXCLUDED.position, is_active = true;
  END LOOP;

  -- El resto queda detrás, desactivado
  WITH rest AS (
    SELECT model_code, cardinality(p_models) + row_number() OVER (ORDER BY position) AS new_pos
    FROM ai.routes WHERE task = p_task AND position > 1000
  )
  UPDATE ai.routes r SET position = rest.new_pos, is_active = false
  FROM rest WHERE r.task = p_task AND r.model_code = rest.model_code;

  SELECT array_agg(model_code ORDER BY position) FILTER (WHERE is_active)
    INTO v_new FROM ai.routes WHERE task = p_task;
  INSERT INTO ai.route_changes (task, changed_by, old_order, new_order, reason)
  VALUES (p_task, v_actor, v_old, v_new, p_reason);
END $$;
COMMENT ON FUNCTION ai.set_route_order(text, text[], text) IS
  'Define principal y respaldos de una tarea en un solo paso y deja el cambio en ai.route_changes.';

-- -----------------------------------------------------------------------------
-- Dictados
-- -----------------------------------------------------------------------------
CREATE TABLE ai.voice_entries (
  id                uuid          NOT NULL DEFAULT core.uuid_v7(),
  created_at        timestamptz   NOT NULL DEFAULT now(),
  user_id           uuid          NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  input_type        text          NOT NULL DEFAULT 'voice' CHECK (input_type IN ('voice', 'text')),
  status            text          NOT NULL DEFAULT 'received'
                                  CHECK (status IN ('received', 'transcribed', 'extracted', 'confirmed', 'discarded', 'failed')),
  audio_seconds     numeric(6,2)  CHECK (audio_seconds >= 0),
  audio_object_key  text,                      -- solo si el usuario acepta guardar el audio
  transcript        text          CHECK (length(transcript) <= 2000),
  stt_model_code    text          REFERENCES ai.models (code),   -- el que logró transcribir (lo llena ai.calls)
  llm_model_code    text          REFERENCES ai.models (code),   -- el que logró extraer
  prompt_version    text,                                         -- para comparar precisión entre versiones del prompt
  extraction        jsonb,        -- {"kind": "expense", "amount": 50, "currency_hint": "BOB", "account_id": "…", "category_id": "…", "missing": []}
  confidence        numeric(4,3)  CHECK (confidence BETWEEN 0 AND 1),
  attempts          smallint      NOT NULL DEFAULT 0,             -- llamadas hechas, sumando respaldos
  fallback_used     boolean       NOT NULL DEFAULT false,         -- true si algún paso usó un respaldo
  input_tokens      integer       NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens     integer       NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  cost_usd          numeric(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),   -- suma de todas las llamadas, también las fallidas
  latency_ms        integer       CHECK (latency_ms >= 0),        -- de punta a punta, lo escribe el worker
  transaction_id    uuid,                                         -- transacción creada al confirmar
  error             text,
  confirmed_at      timestamptz,
  PRIMARY KEY (created_at, id),
  CONSTRAINT voice_entries_audio_chk CHECK (input_type = 'voice' OR audio_seconds IS NULL),
  CONSTRAINT voice_entries_transaction_fk FOREIGN KEY (user_id, transaction_id)
                                          REFERENCES finance.transactions (user_id, id) ON DELETE SET NULL (transaction_id)
) PARTITION BY RANGE (created_at);
CREATE TABLE ai.voice_entries_default PARTITION OF ai.voice_entries DEFAULT;
CREATE INDEX voice_entries_user_idx ON ai.voice_entries (user_id, created_at DESC);
COMMENT ON TABLE ai.voice_entries IS 'Un registro por cada dictado (o frase escrita). Particionada por mes; transcripciones con retención limitada.';

-- -----------------------------------------------------------------------------
-- Llamadas a proveedores: una fila por intento, exitoso o no.
-- Solo métricas (estado, latencia, tokens, costo). El detalle de un error
-- (mensaje, código HTTP, request_id) lo escribe el worker en ops.logs con
-- ops.log(..., p_context => {"call_id": ...}): no se repite aquí.
-- -----------------------------------------------------------------------------
CREATE TABLE ai.calls (
  id                     uuid          NOT NULL DEFAULT core.uuid_v7(),
  created_at             timestamptz   NOT NULL DEFAULT now(),
  task                   text          NOT NULL REFERENCES ai.tasks (key),
  model_code             text          NOT NULL REFERENCES ai.models (code),
  route_position         smallint      NOT NULL CHECK (route_position > 0),   -- 1 = principal; 2+ = respaldo
  attempt                smallint      NOT NULL DEFAULT 1 CHECK (attempt > 0),   -- 2 = primer reintento con el mismo modelo
  status                 text          NOT NULL CHECK (status IN ('ok', 'error', 'timeout', 'rate_limited', 'invalid_output', 'circuit_open')),
  user_id                uuid,                    -- sin FK: el registro de costos sobrevive aunque se borre el usuario
  voice_entry_id         uuid,                    -- sin FK: es un registro operativo con su propia retención
  voice_entry_created_at timestamptz,
  latency_ms             integer       CHECK (latency_ms >= 0),
  audio_seconds          numeric(6,2)  CHECK (audio_seconds >= 0),
  input_tokens           integer       CHECK (input_tokens >= 0),
  cached_input_tokens    integer       CHECK (cached_input_tokens >= 0),
  output_tokens          integer       CHECK (output_tokens >= 0),
  cost_usd               numeric(12,6) CHECK (cost_usd >= 0),   -- si no se envía, se calcula con el precio de ai.models
  PRIMARY KEY (created_at, id),
  CONSTRAINT calls_entry_chk CHECK ((voice_entry_id IS NULL) = (voice_entry_created_at IS NULL))
) PARTITION BY RANGE (created_at);
CREATE TABLE ai.calls_default PARTITION OF ai.calls DEFAULT;
CREATE INDEX calls_model_idx ON ai.calls (model_code, created_at DESC);
CREATE INDEX calls_entry_idx ON ai.calls (voice_entry_id) WHERE voice_entry_id IS NOT NULL;
COMMENT ON TABLE ai.calls IS 'Cada llamada a un proveedor de IA: estado, latencia, tokens y costo. Mide fallas, respaldos y costo real por modelo.';

-- Uso de IA por usuario, mes y tarea. Se acumula con cada llamada, así contar
-- cuánto usa y cuánto cuesta cada usuario no exige recorrer ai.calls.
CREATE TABLE ai.usage_monthly (
  user_id       uuid          NOT NULL,          -- sin FK, como ai.calls
  period        date          NOT NULL CHECK (extract(day FROM period) = 1),
  task          text          NOT NULL REFERENCES ai.tasks (key),
  calls         integer       NOT NULL DEFAULT 0 CHECK (calls >= 0),
  failed_calls  integer       NOT NULL DEFAULT 0 CHECK (failed_calls >= 0),
  audio_seconds numeric(12,2) NOT NULL DEFAULT 0,
  input_tokens  bigint        NOT NULL DEFAULT 0,
  output_tokens bigint        NOT NULL DEFAULT 0,
  cost_usd      numeric(14,6) NOT NULL DEFAULT 0,
  updated_at    timestamptz   NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, period, task)
);
COMMENT ON TABLE ai.usage_monthly IS
  'Llamadas, fallas, audio, tokens y costo de IA por usuario, mes y tarea. La mantiene un trigger de ai.calls.';

-- Costo de la llamada con el precio vigente del modelo
CREATE OR REPLACE FUNCTION ai.calls_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  m ai.models%ROWTYPE;
BEGIN
  SELECT * INTO m FROM ai.models WHERE code = NEW.model_code;
  IF NEW.cost_usd IS NULL THEN
    IF m.kind = 'stt' THEN
      -- Se cobra el audio procesado, con el mínimo por llamada del proveedor
      NEW.cost_usd := CASE WHEN NEW.status IN ('ok', 'invalid_output')
                           THEN round(greatest(coalesce(NEW.audio_seconds, 0), m.min_billed_seconds) / 60
                                      * m.price_per_minute_usd, 6)
                           ELSE 0 END;
    ELSE
      NEW.cost_usd := round((  greatest(coalesce(NEW.input_tokens, 0) - coalesce(NEW.cached_input_tokens, 0), 0) * m.input_per_mtok_usd
                             + coalesce(NEW.cached_input_tokens, 0) * coalesce(m.cached_input_per_mtok_usd, m.input_per_mtok_usd)
                             + coalesce(NEW.output_tokens, 0) * m.output_per_mtok_usd) / 1000000, 6);
    END IF;
  END IF;
  -- Una llamada que no llegó al proveedor no cuesta
  IF NEW.status = 'circuit_open' THEN
    NEW.cost_usd := 0;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER calls_before_insert BEFORE INSERT ON ai.calls
  FOR EACH ROW EXECUTE FUNCTION ai.calls_before_insert();

-- Suma la llamada al dictado y al uso mensual del usuario
CREATE OR REPLACE FUNCTION ai.calls_after_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.voice_entry_id IS NOT NULL THEN
    UPDATE ai.voice_entries v
       SET attempts       = v.attempts + 1,
           fallback_used  = v.fallback_used OR (NEW.status = 'ok' AND NEW.route_position > 1),
           input_tokens   = v.input_tokens  + coalesce(NEW.input_tokens, 0),
           output_tokens  = v.output_tokens + coalesce(NEW.output_tokens, 0),
           cost_usd       = v.cost_usd      + NEW.cost_usd,
           stt_model_code = CASE WHEN NEW.status = 'ok' AND NEW.task = 'voice.transcribe' THEN NEW.model_code ELSE v.stt_model_code END,
           llm_model_code = CASE WHEN NEW.status = 'ok' AND NEW.task = 'voice.extract'    THEN NEW.model_code ELSE v.llm_model_code END
     WHERE v.created_at = NEW.voice_entry_created_at AND v.id = NEW.voice_entry_id;
  END IF;

  IF NEW.user_id IS NOT NULL THEN
    INSERT INTO ai.usage_monthly AS u (user_id, period, task, calls, failed_calls, audio_seconds, input_tokens, output_tokens, cost_usd)
    VALUES (NEW.user_id, date_trunc('month', NEW.created_at)::date, NEW.task, 1, (NEW.status <> 'ok')::int,
            coalesce(NEW.audio_seconds, 0), coalesce(NEW.input_tokens, 0), coalesce(NEW.output_tokens, 0), NEW.cost_usd)
    ON CONFLICT (user_id, period, task) DO UPDATE
       SET calls         = u.calls + 1,
           failed_calls  = u.failed_calls + EXCLUDED.failed_calls,
           audio_seconds = u.audio_seconds + EXCLUDED.audio_seconds,
           input_tokens  = u.input_tokens + EXCLUDED.input_tokens,
           output_tokens = u.output_tokens + EXCLUDED.output_tokens,
           cost_usd      = u.cost_usd + EXCLUDED.cost_usd,
           updated_at    = now();
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER calls_after_insert AFTER INSERT ON ai.calls
  FOR EACH ROW EXECUTE FUNCTION ai.calls_after_insert();

-- -----------------------------------------------------------------------------
-- Vistas para el equipo
-- -----------------------------------------------------------------------------

-- Salud de cada proveedor en las últimas 24 horas
CREATE VIEW ai.provider_health_24h AS
SELECT c.task,
       c.model_code,
       m.provider,
       count(*)                                                    AS calls,
       count(*) FILTER (WHERE c.status = 'ok')                     AS ok,
       count(*) FILTER (WHERE c.status <> 'ok')                    AS failed,
       round(count(*) FILTER (WHERE c.status <> 'ok')::numeric / count(*), 3) AS error_rate,
       count(*) FILTER (WHERE c.status = 'ok' AND c.route_position > 1) AS served_as_fallback,
       percentile_disc(0.5)  WITHIN GROUP (ORDER BY c.latency_ms)  AS p50_ms,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY c.latency_ms)  AS p95_ms,
       sum(c.cost_usd)                                             AS cost_usd,
       max(c.created_at) FILTER (WHERE c.status <> 'ok')           AS last_failure_at
FROM ai.calls c
JOIN ai.models m ON m.code = c.model_code
WHERE c.created_at >= now() - interval '24 hours'
GROUP BY c.task, c.model_code, m.provider;

-- Costo real por modelo y mes (incluye llamadas fallidas)
CREATE VIEW ai.monthly_cost_by_model AS
SELECT date_trunc('month', created_at)::date AS period,
       task,
       model_code,
       count(*)                                  AS calls,
       count(*) FILTER (WHERE status = 'ok')     AS ok,
       sum(coalesce(audio_seconds, 0))           AS audio_seconds,
       sum(coalesce(input_tokens, 0))            AS input_tokens,
       sum(coalesce(output_tokens, 0))           AS output_tokens,
       sum(cost_usd)                             AS cost_usd
FROM ai.calls
GROUP BY 1, 2, 3;

-- Costo de IA por usuario y mes (para comparar con el precio de cada plan)
CREATE VIEW ai.monthly_cost_by_user AS
SELECT user_id,
       date_trunc('month', created_at)::date               AS period,
       count(*)                                            AS entries,
       count(*) FILTER (WHERE status = 'confirmed')        AS confirmed,
       count(*) FILTER (WHERE fallback_used)               AS used_fallback,
       round(avg(confidence), 3)                           AS avg_confidence,
       coalesce(sum(cost_usd), 0)                          AS cost_usd
FROM ai.voice_entries
GROUP BY 1, 2;
-- =============================================================================
-- MoneyMap · 095 · ops (logs e incidentes)
--
-- ops.logs       Registro de solo inserción de todo lo importante que pasa en el
--                sistema: errores, fallos de integraciones (tiendas, IA, tipo de
--                cambio, push), eventos de seguridad y jobs. Particionado por mes.
-- ops.incidents  Agrupa errores repetidos por "huella" (fingerprint) y sigue su
--                ciclo de vida: open → investigating → identified → monitoring →
--                resolved → closed.
--
-- Diferencia con core.audit_log: la auditoría guarda QUIÉN CAMBIÓ QUÉ DATO;
-- ops.logs guarda QUÉ PASÓ EN EL SISTEMA.
--
-- Todo se escribe con ops.log(...). La función nunca lanza error por datos de
-- entrada mal formados: un log no puede romper la operación que lo registra.
-- Los logs de depuración y de cada petición van a Cloud Logging; aquí solo lo
-- que alguien del equipo necesita consultar, contar o investigar.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Logs operativos de solo inserción e incidentes con su seguimiento.';

-- -----------------------------------------------------------------------------
-- Incidentes
-- -----------------------------------------------------------------------------
CREATE SEQUENCE ops.incident_number_seq;

CREATE TABLE ops.incidents (
  id                   uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  number               bigint      NOT NULL UNIQUE DEFAULT nextval('ops.incident_number_seq'),
  code                 text        GENERATED ALWAYS AS ('INC-' || lpad(number::text, 6, '0')) STORED,
  title                text        NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  description          text,
  -- sev1: caída total o datos financieros incorrectos · sev2: función principal
  -- caída (login, registro, cobros) · sev3: función secundaria o pocos usuarios
  -- · sev4: menor, sin impacto visible
  severity             text        NOT NULL CHECK (severity IN ('sev1', 'sev2', 'sev3', 'sev4')),
  status               text        NOT NULL DEFAULT 'open'
                                   CHECK (status IN ('open', 'investigating', 'identified', 'monitoring', 'resolved', 'closed')),
  category             text        NOT NULL,
  fingerprint          text,                       -- agrupa errores iguales
  detected_by          text        NOT NULL DEFAULT 'automatic'
                                   CHECK (detected_by IN ('automatic', 'monitoring', 'user_report', 'manual')),
  previous_incident_id uuid        REFERENCES ops.incidents (id),   -- regresión de uno ya resuelto
  first_seen_at        timestamptz NOT NULL DEFAULT now(),
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  occurrences          integer     NOT NULL DEFAULT 1 CHECK (occurrences > 0),
  affected_users       integer     NOT NULL DEFAULT 0 CHECK (affected_users >= 0),
  assigned_to          text,                       -- persona del equipo
  acknowledged_at      timestamptz,
  resolved_at          timestamptz,
  closed_at            timestamptz,
  impact               text,
  root_cause           text,
  resolution           text,
  postmortem_url       text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT incidents_resolved_chk CHECK ((status IN ('resolved', 'closed')) = (resolved_at IS NOT NULL))
);
-- Un solo incidente abierto por huella: los errores repetidos se suman a él
CREATE UNIQUE INDEX incidents_open_fingerprint_uq ON ops.incidents (fingerprint)
  WHERE fingerprint IS NOT NULL AND status NOT IN ('resolved', 'closed');
CREATE INDEX incidents_open_idx ON ops.incidents (severity, last_seen_at DESC) WHERE status NOT IN ('resolved', 'closed');
CREATE INDEX incidents_fingerprint_idx ON ops.incidents (fingerprint, created_at DESC);
CREATE TRIGGER incidents_set_updated_at BEFORE UPDATE ON ops.incidents
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
COMMENT ON TABLE ops.incidents IS 'Incidentes con severidad, responsable, causa raíz y resolución. Código legible INC-000123.';

-- Línea de tiempo de cada incidente (cambios de estado y notas del equipo)
CREATE TABLE ops.incident_updates (
  id            uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  incident_id   uuid        NOT NULL REFERENCES ops.incidents (id) ON DELETE CASCADE,
  created_at    timestamptz NOT NULL DEFAULT now(),
  author        text        NOT NULL DEFAULT 'system',
  status_from   text,
  status_to     text,
  severity_from text,
  severity_to   text,
  note          text,
  is_public     boolean     NOT NULL DEFAULT false      -- se puede comunicar a los usuarios
);
CREATE INDEX incident_updates_incident_idx ON ops.incident_updates (incident_id, created_at);

-- Usuarios afectados por cada incidente (para avisarles o compensarlos)
CREATE TABLE ops.incident_affected_users (
  incident_id   uuid        NOT NULL REFERENCES ops.incidents (id) ON DELETE CASCADE,
  user_id       uuid        NOT NULL,                   -- sin FK: el registro sobrevive al usuario
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  notified_at   timestamptz,
  PRIMARY KEY (incident_id, user_id)
);

-- Fechas y línea de tiempo automáticas al cambiar estado o severidad
CREATE OR REPLACE FUNCTION ops.incidents_on_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_author text := coalesce(nullif(current_setting('app.actor', true), ''), 'system');
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF OLD.status = 'open' AND NEW.acknowledged_at IS NULL THEN
      NEW.acknowledged_at := now();
    END IF;
    IF NEW.status IN ('resolved', 'closed') THEN
      NEW.resolved_at := coalesce(NEW.resolved_at, now());
    ELSE
      NEW.resolved_at := NULL;                     -- reabierto
    END IF;
    NEW.closed_at := CASE WHEN NEW.status = 'closed' THEN coalesce(NEW.closed_at, now()) END;
  END IF;

  IF NEW.status IS DISTINCT FROM OLD.status OR NEW.severity IS DISTINCT FROM OLD.severity THEN
    INSERT INTO ops.incident_updates (incident_id, author, status_from, status_to, severity_from, severity_to)
    VALUES (NEW.id, v_author,
            OLD.status,   NEW.status,
            OLD.severity, NEW.severity);
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER incidents_on_change BEFORE UPDATE ON ops.incidents
  FOR EACH ROW EXECUTE FUNCTION ops.incidents_on_change();
CREATE OR REPLACE FUNCTION ops.incidents_after_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO ops.incident_updates (incident_id, author, status_to, severity_to, note)
  VALUES (NEW.id, coalesce(nullif(current_setting('app.actor', true), ''), 'system'),
          NEW.status, NEW.severity, 'Incidente creado (' || NEW.detected_by || ')');
  RETURN NULL;
END $$;
CREATE TRIGGER incidents_after_insert AFTER INSERT ON ops.incidents
  FOR EACH ROW EXECUTE FUNCTION ops.incidents_after_insert();

-- -----------------------------------------------------------------------------
-- Logs (solo inserción, particionados por mes)
-- -----------------------------------------------------------------------------
CREATE TABLE ops.logs (
  id            uuid        NOT NULL DEFAULT core.uuid_v7(),
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  level         text        NOT NULL CHECK (level IN ('debug', 'info', 'notice', 'warning', 'error', 'critical')),
  severity      smallint    GENERATED ALWAYS AS (
                  CASE level WHEN 'debug' THEN 10 WHEN 'info' THEN 20 WHEN 'notice' THEN 30
                             WHEN 'warning' THEN 40 WHEN 'error' THEN 50 ELSE 60 END) STORED,
  category      text        NOT NULL CHECK (category IN ('api', 'auth', 'security', 'billing', 'finance', 'ai',
                                                         'notify', 'integration', 'job', 'database', 'client', 'system')),
  event_code    text        NOT NULL,          -- 'billing.webhook.invalid_signature'
  message       text        NOT NULL,
  service       text        NOT NULL CHECK (service IN ('api', 'worker', 'scheduler', 'ios', 'android', 'web', 'database')),
  environment   text        NOT NULL CHECK (environment IN ('prod', 'staging', 'dev')),
  release       text,                        -- versión de la app o commit desplegado
  user_id       uuid,
  device_id     uuid,
  request_id    text,
  trace_id      text,
  http_method   text,
  http_path     text,
  http_status   smallint,
  duration_ms   integer,
  error_type    text,
  error_message text,
  stack_trace   text,
  fingerprint   text,
  incident_id   uuid,
  context       jsonb       NOT NULL DEFAULT '{}',   -- nunca contraseñas, tokens ni números de tarjeta
  ip            inet,
  PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
CREATE TABLE ops.logs_default PARTITION OF ops.logs DEFAULT;

CREATE INDEX logs_severity_idx ON ops.logs (severity, occurred_at DESC) WHERE severity >= 40;
CREATE INDEX logs_event_idx    ON ops.logs (event_code, occurred_at DESC);
CREATE INDEX logs_category_idx ON ops.logs (category, occurred_at DESC);
CREATE INDEX logs_user_idx     ON ops.logs (user_id, occurred_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX logs_request_idx  ON ops.logs (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX logs_incident_idx ON ops.logs (incident_id, occurred_at DESC) WHERE incident_id IS NOT NULL;
COMMENT ON TABLE ops.logs IS 'Eventos operativos de solo inserción. Retención por particiones mensuales completas.';

-- Nadie edita ni borra un log; la retención borra meses completos con DROP.
CREATE OR REPLACE FUNCTION ops.logs_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ops.logs es de solo inserción: no se puede % un log', lower(TG_OP)
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER logs_append_only BEFORE UPDATE OR DELETE ON ops.logs
  FOR EACH ROW EXECUTE FUNCTION ops.logs_append_only();

-- -----------------------------------------------------------------------------
-- ops.log(): única forma de escribir. Los errores con la misma huella se
-- agrupan en un incidente abierto; si uno resuelto vuelve a ocurrir, se abre
-- otro enlazado al anterior (regresión).
-- Ejemplo desde Python:
--   SELECT ops.log(p_level => 'error', p_category => 'billing',
--                  p_event_code => 'billing.webhook.invalid_signature',
--                  p_message => 'Firma inválida en notificación de App Store',
--                  p_service => 'worker', p_context => '{"provider": "app_store"}');
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.log(
  p_level         text,
  p_category      text,
  p_event_code    text,
  p_message       text,
  p_context       jsonb    DEFAULT '{}',
  p_service       text     DEFAULT 'api',
  p_user_id       uuid     DEFAULT NULL,
  p_request_id    text     DEFAULT NULL,
  p_trace_id      text     DEFAULT NULL,
  p_error_type    text     DEFAULT NULL,
  p_error_message text     DEFAULT NULL,
  p_stack_trace   text     DEFAULT NULL,
  p_http_method   text     DEFAULT NULL,
  p_http_path     text     DEFAULT NULL,
  p_http_status   integer  DEFAULT NULL,
  p_duration_ms   integer  DEFAULT NULL,
  p_fingerprint   text     DEFAULT NULL,
  p_release       text     DEFAULT NULL,
  p_device_id     uuid     DEFAULT NULL,
  p_ip            inet     DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  v_levels   constant text[] := ARRAY['debug', 'info', 'notice', 'warning', 'error', 'critical'];
  v_level    text := lower(coalesce(p_level, ''));
  v_category text := lower(coalesce(p_category, ''));
  v_service  text := lower(coalesce(p_service, ''));
  v_env      text := coalesce(nullif(current_setting('app.environment', true), ''), 'prod');
  v_min      text := coalesce(nullif(current_setting('app.log_min_level', true), ''), 'info');
  v_event    text;
  v_context  jsonb := coalesce(p_context, '{}'::jsonb);
  v_fp       text;
  v_incident uuid;
  v_prev     uuid;
  v_new_user int;
  v_id       uuid := core.uuid_v7();
BEGIN
  -- Normalizar en lugar de fallar
  IF NOT v_level = ANY (v_levels) THEN
    v_context := v_context || jsonb_build_object('original_level', p_level);
    v_level   := 'warning';
  END IF;
  IF array_position(v_levels, v_level) < coalesce(array_position(v_levels, v_min), 2) THEN
    RETURN NULL;                                   -- por debajo del nivel mínimo configurado
  END IF;
  IF v_category NOT IN ('api', 'auth', 'security', 'billing', 'finance', 'ai', 'notify',
                        'integration', 'job', 'database', 'client', 'system') THEN
    v_context  := v_context || jsonb_build_object('original_category', p_category);
    v_category := 'system';
  END IF;
  IF v_service NOT IN ('api', 'worker', 'scheduler', 'ios', 'android', 'web', 'database') THEN
    v_context := v_context || jsonb_build_object('original_service', p_service);
    v_service := 'api';
  END IF;
  IF v_env NOT IN ('prod', 'staging', 'dev') THEN
    v_env := 'dev';
  END IF;
  v_event := trim(BOTH '._' FROM regexp_replace(lower(coalesce(p_event_code, '')), '[^a-z0-9_.]+', '_', 'g'));
  IF v_event = '' THEN
    v_event := 'unknown';
  END IF;
  IF position('.' IN v_event) = 0 THEN
    v_event := v_category || '.' || v_event;
  END IF;

  -- Agrupar errores en incidentes (un fallo aquí nunca impide guardar el log)
  IF v_level IN ('error', 'critical') THEN
    v_fp := left(coalesce(nullif(p_fingerprint, ''), v_event || ':' || coalesce(p_error_type, '')), 300);
    BEGIN
      SELECT i.id INTO v_prev FROM ops.incidents i
      WHERE i.fingerprint = v_fp AND i.status IN ('resolved', 'closed')
      ORDER BY i.created_at DESC LIMIT 1;

      INSERT INTO ops.incidents (title, severity, category, fingerprint, previous_incident_id)
      VALUES (left(v_event || ': ' || coalesce(p_message, ''), 200),
              CASE v_level WHEN 'critical' THEN 'sev2' ELSE 'sev3' END,
              v_category, v_fp, v_prev)
      ON CONFLICT (fingerprint) WHERE fingerprint IS NOT NULL AND status NOT IN ('resolved', 'closed')
      DO UPDATE SET occurrences  = ops.incidents.occurrences + 1,
                    last_seen_at = now(),
                    severity     = least(ops.incidents.severity, EXCLUDED.severity)   -- un critical escala
      RETURNING id INTO v_incident;

      IF p_user_id IS NOT NULL THEN
        INSERT INTO ops.incident_affected_users (incident_id, user_id)
        VALUES (v_incident, p_user_id)
        ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS v_new_user = ROW_COUNT;
        IF v_new_user > 0 THEN
          UPDATE ops.incidents SET affected_users = affected_users + 1 WHERE id = v_incident;
        END IF;
      END IF;
    EXCEPTION WHEN OTHERS THEN
      v_context  := v_context || jsonb_build_object('incident_error', SQLERRM);
      v_incident := NULL;
    END;
  END IF;

  INSERT INTO ops.logs (id, level, category, event_code, message, service, environment, release,
                        user_id, device_id, request_id, trace_id,
                        http_method, http_path, http_status, duration_ms,
                        error_type, error_message, stack_trace, fingerprint, incident_id, context, ip)
  VALUES (v_id, v_level, v_category, left(v_event, 120), left(coalesce(p_message, ''), 2000), v_service, v_env,
          left(p_release, 60), p_user_id, p_device_id, left(p_request_id, 100), left(p_trace_id, 100),
          left(upper(p_http_method), 10), left(p_http_path, 300),
          CASE WHEN p_http_status BETWEEN 100 AND 599 THEN p_http_status END, p_duration_ms,
          left(p_error_type, 200), left(p_error_message, 2000), left(p_stack_trace, 20000),
          v_fp, v_incident, v_context, p_ip);
  RETURN v_id;
END $$;
COMMENT ON FUNCTION ops.log IS
  'Registra un evento. error y critical abren o suman a un incidente. Devuelve el id del log, o NULL si está bajo app.log_min_level.';

-- -----------------------------------------------------------------------------
-- Vistas para el equipo
-- -----------------------------------------------------------------------------
CREATE VIEW ops.open_incidents AS
SELECT code, severity, status, title, category, occurrences, affected_users,
       first_seen_at, last_seen_at, assigned_to, id
FROM ops.incidents
WHERE status NOT IN ('resolved', 'closed')
ORDER BY severity, last_seen_at DESC;

CREATE VIEW ops.error_summary_24h AS
SELECT event_code,
       category,
       CASE max(severity) WHEN 40 THEN 'warning' WHEN 50 THEN 'error' ELSE 'critical' END AS worst_level,
       count(*)                       AS events,
       count(DISTINCT user_id)        AS users,
       min(occurred_at)               AS first_at,
       max(occurred_at)               AS last_at,
       max(incident_id::text)::uuid   AS incident_id
FROM ops.logs
WHERE occurred_at > now() - INTERVAL '24 hours' AND severity >= 40
GROUP BY event_code, category
ORDER BY events DESC;
-- =============================================================================
-- MoneyMap · 900 · roles, permisos y Row-Level Security
--
-- Roles (sin login; los usuarios con login los crea Terraform y heredan de estos):
--   moneymap_app     API FastAPI. Sujeto a RLS: solo ve las filas cuyo user_id
--                    es app.user_id. Segunda barrera si un bug olvida un filtro.
--   moneymap_worker  Workers de Celery (Money Story, recurrentes, tipos de
--                    cambio, webhooks de las tiendas). Procesa todos los usuarios.
--   moneymap_ops     Equipo de soporte y operaciones: lee logs y gestiona
--                    incidentes; cambia el orden de proveedores de IA.
--                    No ve datos financieros.
-- El dueño de las tablas (rol de migraciones) no se usa en la API.
--
-- Sin RLS a propósito: iam.users, terms_versions, auth_identities, sessions,
-- devices y verification_tokens (el login ocurre antes de conocer al usuario). Su acceso
-- se controla en la API.
-- Billing: la API solo lee (y solo lo suyo, con RLS); las suscripciones las
-- escriben los workers que procesan los webhooks de App Store y Play Store.
-- Ops: la API y los workers solo escriben logs con ops.log(); no pueden leerlos.
-- =============================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_app') THEN
    CREATE ROLE moneymap_app NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_worker') THEN
    CREATE ROLE moneymap_worker NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_ops') THEN
    CREATE ROLE moneymap_ops NOLOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA core, catalog, iam, billing, finance, goals, planning, reports, notify, ai, ops
  TO moneymap_app, moneymap_worker;

GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO moneymap_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA catalog TO moneymap_worker;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON ALL TABLES IN SCHEMA iam, finance, goals, planning, reports, notify, ai
  TO moneymap_app, moneymap_worker;

-- Los términos los publica el equipo; la API solo lee la versión vigente
REVOKE INSERT, UPDATE, DELETE ON iam.terms_versions FROM moneymap_app, moneymap_worker;

-- Billing: catálogo de planes visible; suscripciones y pagos solo lectura para la API
GRANT SELECT ON billing.plans, billing.plan_prices, billing.features, billing.plan_features,
                billing.subscriptions, billing.subscription_changes, billing.payments
  TO moneymap_app;
GRANT SELECT, INSERT, UPDATE ON billing.usage_counters TO moneymap_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA billing TO moneymap_worker;
GRANT SELECT ON billing.user_plans, billing.user_entitlements, billing.price_catalog
  TO moneymap_app, moneymap_worker;

-- Ops: escribir solo a través de ops.log(); leer y gestionar, solo el equipo
REVOKE ALL ON ALL TABLES IN SCHEMA ops FROM moneymap_app, moneymap_worker;
GRANT EXECUTE ON FUNCTION ops.log TO moneymap_app, moneymap_worker;
GRANT USAGE ON SCHEMA ops, core TO moneymap_ops;
GRANT SELECT ON ops.logs, ops.incidents, ops.incident_updates, ops.incident_affected_users,
                ops.open_incidents, ops.error_summary_24h TO moneymap_ops;
GRANT INSERT, UPDATE ON ops.incidents TO moneymap_ops;
GRANT INSERT ON ops.incident_updates TO moneymap_ops;
GRANT UPDATE (notified_at) ON ops.incident_affected_users TO moneymap_ops;
GRANT USAGE ON SEQUENCE ops.incident_number_seq TO moneymap_ops;
GRANT EXECUTE ON FUNCTION ops.log, core.uuid_v7(), core.set_updated_at() TO moneymap_ops;

GRANT INSERT ON core.audit_log, core.outbox_events TO moneymap_app;
GRANT SELECT, INSERT ON core.audit_log TO moneymap_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.outbox_events TO moneymap_worker;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA core, catalog, iam, billing, finance, goals, reports, notify
  TO moneymap_app, moneymap_worker;

-- IA: la API solo ve sus dictados (con RLS). Modelos, rutas y llamadas son del
-- worker (lee rutas, inserta llamadas) y del equipo (cambia el orden de proveedores).
REVOKE ALL ON ai.tasks, ai.models, ai.routes, ai.route_changes, ai.calls, ai.usage_monthly,
              ai.provider_health_24h, ai.monthly_cost_by_model FROM moneymap_app;
REVOKE INSERT, UPDATE, DELETE ON ai.tasks, ai.models, ai.routes, ai.route_changes FROM moneymap_worker;
REVOKE UPDATE, DELETE ON ai.calls FROM moneymap_worker;
REVOKE DELETE ON ai.usage_monthly FROM moneymap_worker;     -- solo la suma el trigger de ai.calls
GRANT SELECT ON ai.provider_health_24h, ai.monthly_cost_by_model TO moneymap_worker;
REVOKE EXECUTE ON FUNCTION ai.set_route_order(text, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ai.route(text) TO moneymap_worker;
GRANT USAGE ON SCHEMA ai TO moneymap_ops;
GRANT SELECT ON ai.tasks, ai.models, ai.routes, ai.route_changes, ai.calls, ai.usage_monthly,
                ai.provider_health_24h, ai.monthly_cost_by_model TO moneymap_ops;
GRANT UPDATE (is_active) ON ai.models TO moneymap_ops;     -- apagar un proveedor en una emergencia
GRANT EXECUTE ON FUNCTION ai.set_route_order(text, text[], text), ai.route(text) TO moneymap_ops;

-- Las vistas se evalúan con los permisos de quien consulta, así respetan la RLS.
ALTER VIEW finance.account_balances  SET (security_invoker = true);
ALTER VIEW finance.balance_totals    SET (security_invoker = true);
ALTER VIEW billing.user_plans         SET (security_invoker = true);
ALTER VIEW billing.user_entitlements  SET (security_invoker = true);
ALTER VIEW billing.price_catalog      SET (security_invoker = true);
ALTER VIEW ai.monthly_cost_by_user    SET (security_invoker = true);
ALTER VIEW ai.provider_health_24h     SET (security_invoker = true);
ALTER VIEW ai.monthly_cost_by_model   SET (security_invoker = true);
ALTER VIEW ops.open_incidents         SET (security_invoker = true);
ALTER VIEW ops.error_summary_24h      SET (security_invoker = true);

-- Las particiones solo se acceden a través de la tabla padre (que tiene RLS).
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS part
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('core', 'finance', 'notify', 'ai', 'ops') AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format('REVOKE ALL ON %s FROM moneymap_app, moneymap_worker, moneymap_ops', r.part);
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- Row-Level Security: cada usuario ve y escribe solo sus propias filas.
-- Los datos son personales: no hay roles ni cuentas compartidas.
-- (SELECT core.current_user_id()) se evalúa una vez por consulta.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'iam.user_preferences',
    'finance.user_settings', 'finance.user_currencies', 'finance.accounts', 'finance.cards', 'finance.categories',
    'finance.recurring_rules', 'finance.transactions',
    'goals.goals', 'goals.goal_contributions',
    'planning.affordability_checks',
    'reports.money_stories',
    'ai.voice_entries',
    'notify.preferences', 'notify.notifications',
    'billing.subscriptions', 'billing.subscription_changes', 'billing.payments', 'billing.usage_counters'
  ] LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY own_rows ON %s FOR ALL TO moneymap_app
                      USING (user_id = (SELECT core.current_user_id()))
                      WITH CHECK (user_id = (SELECT core.current_user_id()))$p$, t);
    EXECUTE format('CREATE POLICY worker_all ON %s FOR ALL TO moneymap_worker USING (true) WITH CHECK (true)', t);
  END LOOP;
END $$;

-- Solo los roles de la app escriben logs
REVOKE EXECUTE ON FUNCTION ops.log FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.log TO moneymap_app, moneymap_worker, moneymap_ops;
-- =============================================================================
-- MoneyMap · 950 · datos iniciales
-- Monedas, tipos de cuenta, grupos del Money Flow, categorías iniciales, catálogo de
-- funcionalidades, planes, tipos de notificación, proveedores de IA y primeras
-- particiones mensuales. Idempotente.
-- =============================================================================

-- Términos y política de privacidad vigentes (las URL son PROVISIONALES)
INSERT INTO iam.terms_versions (version, terms_url, privacy_url, is_current) VALUES
  ('2026-10', 'https://moneymap.app/legal/terminos', 'https://moneymap.app/legal/privacidad', true)
ON CONFLICT (version) DO NOTHING;

-- Monedas (ISO 4217). Para ofrecer otra: INSERT con is_active = true.
-- Para dejar de ofrecer una: is_active = false (los datos existentes se conservan).
INSERT INTO catalog.currencies (code, name, symbol, decimals, sort_order) VALUES
  ('BOB', 'Boliviano',              'Bs',  2, 10),
  ('USD', 'Dólar estadounidense',   '$',   2, 20),
  ('EUR', 'Euro',                   '€',   2, 30),
  ('GBP', 'Libra esterlina',        '£',   2, 40),
  ('ARS', 'Peso argentino',         '$',   2, 50),
  ('BRL', 'Real brasileño',         'R$',  2, 50),
  ('CLP', 'Peso chileno',           '$',   0, 50),
  ('COP', 'Peso colombiano',        '$',   2, 50),
  ('MXN', 'Peso mexicano',          '$',   2, 50),
  ('PEN', 'Sol peruano',            'S/',  2, 50),
  ('PYG', 'Guaraní paraguayo',      '₲',   0, 50),
  ('UYU', 'Peso uruguayo',          '$U',  2, 50)
ON CONFLICT (code) DO NOTHING;

-- Tipos de cuenta: efectivo y tarjeta (sin distinguir débito de crédito).
-- is_card cuenta para el límite de tarjetas y responde "¿pagó con tarjeta?".
INSERT INTO catalog.account_types (code, names, icon, is_card, sort_order) VALUES
  ('cash', '{"es": "Efectivo", "en": "Cash"}', 'payments',    false, 10),
  ('card', '{"es": "Tarjeta", "en": "Card"}',  'credit_card', true,  20)
ON CONFLICT (code) DO NOTHING;

-- Países: los de las monedas del catálogo. Agregar otro es un INSERT.
INSERT INTO catalog.countries (code, name, currency, sort_order) VALUES
  ('BO', 'Bolivia',         'BOB', 10),
  ('AR', 'Argentina',       'ARS', 20),
  ('BR', 'Brasil',          'BRL', 20),
  ('CL', 'Chile',           'CLP', 20),
  ('CO', 'Colombia',        'COP', 20),
  ('MX', 'México',          'MXN', 20),
  ('PE', 'Perú',            'PEN', 20),
  ('PY', 'Paraguay',        'PYG', 20),
  ('UY', 'Uruguay',         'UYU', 20),
  ('US', 'Estados Unidos',  'USD', 30),
  ('ES', 'España',          'EUR', 30),
  ('GB', 'Reino Unido',     'GBP', 30)
ON CONFLICT (code) DO NOTHING;

-- Instituciones financieras que emiten tarjetas. PROVISIONAL: lista inicial
-- para revisar con el equipo (bancos de Bolivia regulados por ASFI y los
-- principales de los países vecinos). Agregar o desactivar una es un INSERT o UPDATE.
INSERT INTO catalog.financial_institutions (code, country_code, name, short_name, kind, sort_order) VALUES
  -- Bolivia
  ('bo.bnb',        'BO', 'Banco Nacional de Bolivia',              'BNB',            'bank',         10),
  ('bo.bmsc',       'BO', 'Banco Mercantil Santa Cruz',             'Mercantil',      'bank',         10),
  ('bo.union',      'BO', 'Banco Unión',                            'Banco Unión',    'bank',         10),
  ('bo.bcp',        'BO', 'Banco de Crédito de Bolivia',            'BCP',            'bank',         10),
  ('bo.bisa',       'BO', 'Banco BISA',                             'BISA',           'bank',         10),
  ('bo.economico',  'BO', 'Banco Económico',                        'Económico',      'bank',         20),
  ('bo.ganadero',   'BO', 'Banco Ganadero',                         'Ganadero',       'bank',         20),
  ('bo.sol',        'BO', 'Banco Solidario',                        'BancoSol',       'microfinance', 20),
  ('bo.fie',        'BO', 'Banco para el Fomento a Iniciativas Económicas', 'Banco FIE', 'microfinance', 20),
  ('bo.fortaleza',  'BO', 'Banco Fortaleza',                        'Fortaleza',      'bank',         20),
  ('bo.prodem',     'BO', 'Banco Prodem',                           'Prodem',         'microfinance', 30),
  ('bo.ecofuturo',  'BO', 'Banco Pyme Ecofuturo',                   'Ecofuturo',      'microfinance', 30),
  ('bo.comunidad',  'BO', 'Banco Pyme de la Comunidad',             'Banco Comunidad','microfinance', 30),
  -- Argentina
  ('ar.nacion',     'AR', 'Banco de la Nación Argentina',           'Banco Nación',   'bank',    10),
  ('ar.galicia',    'AR', 'Banco Galicia',                          'Galicia',        'bank',    10),
  ('ar.santander',  'AR', 'Banco Santander Argentina',              'Santander',      'bank',    10),
  ('ar.bbva',       'AR', 'BBVA Argentina',                         'BBVA',           'bank',    10),
  ('ar.macro',      'AR', 'Banco Macro',                            'Macro',          'bank',    10),
  ('ar.provincia',  'AR', 'Banco de la Provincia de Buenos Aires',  'Banco Provincia','bank',    20),
  ('ar.mercadopago','AR', 'Mercado Pago',                           'Mercado Pago',   'fintech', 20),
  ('ar.uala',       'AR', 'Ualá',                                   'Ualá',           'fintech', 20),
  ('ar.brubank',    'AR', 'Brubank',                                'Brubank',        'bank',    30),
  -- Brasil
  ('br.itau',       'BR', 'Itaú Unibanco',                          'Itaú',           'bank',    10),
  ('br.bb',         'BR', 'Banco do Brasil',                        'Banco do Brasil','bank',    10),
  ('br.bradesco',   'BR', 'Banco Bradesco',                         'Bradesco',       'bank',    10),
  ('br.caixa',      'BR', 'Caixa Econômica Federal',                'Caixa',          'bank',    10),
  ('br.santander',  'BR', 'Banco Santander Brasil',                 'Santander',      'bank',    10),
  ('br.nubank',     'BR', 'Nu Pagamentos',                          'Nubank',         'fintech', 20),
  ('br.inter',      'BR', 'Banco Inter',                            'Inter',          'bank',    20),
  -- Chile
  ('cl.bancochile', 'CL', 'Banco de Chile',                         'Banco de Chile', 'bank',    10),
  ('cl.estado',     'CL', 'BancoEstado',                            'BancoEstado',    'bank',    10),
  ('cl.santander',  'CL', 'Banco Santander Chile',                  'Santander',      'bank',    10),
  ('cl.bci',        'CL', 'Banco de Crédito e Inversiones',         'BCI',            'bank',    10),
  ('cl.scotiabank', 'CL', 'Scotiabank Chile',                       'Scotiabank',     'bank',    20),
  ('cl.itau',       'CL', 'Banco Itaú Chile',                       'Itaú',           'bank',    20),
  -- Colombia
  ('co.bancolombia','CO', 'Bancolombia',                            'Bancolombia',    'bank',    10),
  ('co.bogota',     'CO', 'Banco de Bogotá',                        'Banco de Bogotá','bank',    10),
  ('co.davivienda', 'CO', 'Davivienda',                             'Davivienda',     'bank',    10),
  ('co.bbva',       'CO', 'BBVA Colombia',                          'BBVA',           'bank',    20),
  ('co.nequi',      'CO', 'Nequi',                                  'Nequi',          'fintech', 20),
  ('co.nu',         'CO', 'Nu Colombia',                            'Nu',             'fintech', 20),
  -- México
  ('mx.bbva',       'MX', 'BBVA México',                            'BBVA',           'bank',    10),
  ('mx.banorte',    'MX', 'Banorte',                                'Banorte',        'bank',    10),
  ('mx.santander',  'MX', 'Banco Santander México',                 'Santander',      'bank',    10),
  ('mx.banamex',    'MX', 'Banamex',                                'Banamex',        'bank',    10),
  ('mx.hsbc',       'MX', 'HSBC México',                            'HSBC',           'bank',    20),
  ('mx.nu',         'MX', 'Nu México',                              'Nu',             'fintech', 20),
  -- Perú
  ('pe.bcp',        'PE', 'Banco de Crédito del Perú',              'BCP',            'bank',    10),
  ('pe.bbva',       'PE', 'BBVA Perú',                              'BBVA',           'bank',    10),
  ('pe.interbank',  'PE', 'Interbank',                              'Interbank',      'bank',    10),
  ('pe.scotiabank', 'PE', 'Scotiabank Perú',                        'Scotiabank',     'bank',    10),
  ('pe.nacion',     'PE', 'Banco de la Nación',                     'Banco de la Nación', 'bank', 20),
  -- Paraguay
  ('py.itau',       'PY', 'Banco Itaú Paraguay',                    'Itaú',           'bank',    10),
  ('py.continental','PY', 'Banco Continental',                      'Continental',    'bank',    10),
  ('py.basa',       'PY', 'Banco Basa',                             'Basa',           'bank',    10),
  ('py.ueno',       'PY', 'ueno bank',                              'ueno',           'bank',    20),
  ('py.bnf',        'PY', 'Banco Nacional de Fomento',              'BNF',            'bank',    20),
  -- Uruguay
  ('uy.brou',       'UY', 'Banco de la República Oriental del Uruguay', 'BROU',       'bank',    10),
  ('uy.itau',       'UY', 'Banco Itaú Uruguay',                     'Itaú',           'bank',    10),
  ('uy.santander',  'UY', 'Banco Santander Uruguay',                'Santander',      'bank',    10),
  ('uy.bbva',       'UY', 'BBVA Uruguay',                           'BBVA',           'bank',    20),
  ('uy.scotiabank', 'UY', 'Scotiabank Uruguay',                     'Scotiabank',     'bank',    20)
ON CONFLICT (code) DO NOTHING;

-- Categorías iniciales. Cada gasto lleva su grupo del Money Flow; los ingresos, ninguno.
INSERT INTO catalog.category_templates (key, kind, flow_group, names, icon, color, sort_order) VALUES
  -- Ingresos (FTR-031)
  ('salary',            'income',  NULL,        '{"es": "Salario", "en": "Salary"}',                          'payments',          '#16A34A', 10),
  ('freelance',         'income',  NULL,        '{"es": "Trabajo independiente", "en": "Freelance"}',         'work',              '#059669', 20),
  ('business',          'income',  NULL,        '{"es": "Emprendimiento", "en": "Business"}',                 'storefront',        '#0D9488', 30),
  ('family_support',    'income',  NULL,        '{"es": "Mesada familiar", "en": "Family support"}',          'family_restroom',   '#0891B2', 40),
  ('investment_income', 'income',  NULL,        '{"es": "Inversiones e intereses", "en": "Investments"}',     'trending_up',       '#2563EB', 50),
  ('other_income',      'income',  NULL,        '{"es": "Otros ingresos", "en": "Other income"}',             'add_card',          '#64748B', 90),
  -- Necesidades
  ('housing',           'expense', 'needs',     '{"es": "Vivienda y alquiler", "en": "Housing"}',             'home',              '#7C3AED', 10),
  ('utilities',         'expense', 'needs',     '{"es": "Servicios básicos", "en": "Utilities"}',             'bolt',              '#6D28D9', 20),
  ('groceries',         'expense', 'needs',     '{"es": "Supermercado", "en": "Groceries"}',                  'shopping_cart',     '#4F46E5', 30),
  ('transport',         'expense', 'needs',     '{"es": "Transporte", "en": "Transport"}',                    'directions_bus',    '#2563EB', 40),
  ('health',            'expense', 'needs',     '{"es": "Salud", "en": "Health"}',                            'medical_services',  '#DC2626', 50),
  ('education',         'expense', 'needs',     '{"es": "Educación", "en": "Education"}',                     'school',            '#0284C7', 60),
  ('debt_payments',     'expense', 'needs',     '{"es": "Deudas y créditos", "en": "Debt payments"}',         'credit_card',       '#B91C1C', 70),
  ('insurance',         'expense', 'needs',     '{"es": "Seguros", "en": "Insurance"}',                       'shield',            '#475569', 80),
  -- Estilo de vida
  ('restaurants',       'expense', 'lifestyle', '{"es": "Restaurantes", "en": "Restaurants"}',                'restaurant',        '#EA580C', 10),
  ('food_delivery',     'expense', 'lifestyle', '{"es": "Delivery de comida", "en": "Food delivery"}',        'delivery_dining',   '#F97316', 20),
  ('entertainment',     'expense', 'lifestyle', '{"es": "Entretenimiento", "en": "Entertainment"}',           'movie',             '#DB2777', 30),
  ('subscriptions',     'expense', 'lifestyle', '{"es": "Suscripciones", "en": "Subscriptions"}',             'subscriptions',     '#C026D3', 40),
  ('shopping',          'expense', 'lifestyle', '{"es": "Compras", "en": "Shopping"}',                        'shopping_bag',      '#E11D48', 50),
  ('travel',            'expense', 'lifestyle', '{"es": "Viajes", "en": "Travel"}',                           'flight',            '#0EA5E9', 60),
  ('personal_care',     'expense', 'lifestyle', '{"es": "Cuidado personal", "en": "Personal care"}',          'spa',               '#EC4899', 70),
  ('gifts',             'expense', 'lifestyle', '{"es": "Regalos", "en": "Gifts"}',                           'redeem',            '#F43F5E', 80),
  ('other_expense',     'expense', 'lifestyle', '{"es": "Otros gastos", "en": "Other expenses"}',             'more_horiz',        '#64748B', 90)
ON CONFLICT (key) DO NOTHING;

-- Funcionalidades que un plan puede habilitar o limitar
INSERT INTO billing.features (key, description, value_type, limit_period) VALUES
  ('finance.cards',                 'Tarjetas activas',                           'limit',   'total'),
  ('finance.currencies',            'Monedas distintas entre las cuentas activas', 'limit',   'total'),
  ('goals.active',                  'Metas activas',                              'limit',   'total'),
  ('ai.voice_entries',              'Registros por voz al mes',                   'limit',   'month'),
  ('planning.affordability_checks', 'Consultas de Can I Afford It? al mes',       'limit',   'month'),
  ('reports.money_story',           'Monthly Money Story',                        'boolean', NULL),
  ('notify.push',                   'Notificaciones push',                        'boolean', NULL)
ON CONFLICT (key) DO NOTHING;

-- Planes. PROVISIONAL: nombres, precios y límites están por definir (PRD, preguntas abiertas).
-- Los precios mensual y anual de cada plan de pago se cargan en billing.plan_prices
-- cuando el equipo los defina; hasta entonces los planes de pago quedan inactivos.
INSERT INTO billing.plans (code, name, tier, is_public, is_active) VALUES
  ('free',   'Gratuito',       0, true,  true),
  ('paid_1', 'Plan de pago 1', 1, false, false),
  ('paid_2', 'Plan de pago 2', 2, false, false),
  ('paid_3', 'Plan de pago 3', 3, false, false)
ON CONFLICT (code) DO NOTHING;

-- Límites PROVISIONALES (NULL = ilimitado). El gratuito permite 1 tarjeta y
-- 1 moneda (Bs o USD, la que elija); los planes de pago, sin límite.
-- Cambiar un número es un UPDATE, sin desplegar código.
INSERT INTO billing.plan_features (plan_id, feature_key, is_enabled, limit_value)
SELECT p.id, v.feature_key, v.is_enabled, v.limit_value
FROM billing.plans p
JOIN (VALUES
  ('free',   'finance.cards',                 true,  1),
  ('free',   'finance.currencies',            true,  1),
  ('free',   'goals.active',                  true,  2),
  ('free',   'ai.voice_entries',              true,  30),
  ('free',   'planning.affordability_checks', true,  10),
  ('free',   'reports.money_story',           true,  NULL),
  ('free',   'notify.push',                   true,  NULL),
  ('paid_1', 'finance.cards',                 true,  NULL),
  ('paid_1', 'finance.currencies',            true,  NULL),
  ('paid_1', 'goals.active',                  true,  NULL),
  ('paid_1', 'ai.voice_entries',              true,  NULL),
  ('paid_1', 'planning.affordability_checks', true,  NULL),
  ('paid_1', 'reports.money_story',           true,  NULL),
  ('paid_1', 'notify.push',                   true,  NULL),
  ('paid_2', 'finance.cards',                 true,  NULL),
  ('paid_2', 'finance.currencies',            true,  NULL),
  ('paid_2', 'goals.active',                  true,  NULL),
  ('paid_2', 'ai.voice_entries',              true,  NULL),
  ('paid_2', 'planning.affordability_checks', true,  NULL),
  ('paid_2', 'reports.money_story',           true,  NULL),
  ('paid_2', 'notify.push',                   true,  NULL),
  ('paid_3', 'finance.cards',                 true,  NULL),
  ('paid_3', 'finance.currencies',            true,  NULL),
  ('paid_3', 'goals.active',                  true,  NULL),
  ('paid_3', 'ai.voice_entries',              true,  NULL),
  ('paid_3', 'planning.affordability_checks', true,  NULL),
  ('paid_3', 'reports.money_story',           true,  NULL),
  ('paid_3', 'notify.push',                   true,  NULL)
) AS v (plan_code, feature_key, is_enabled, limit_value) ON v.plan_code = p.code
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Tipos de aviso de la V1 (FTR-023)
INSERT INTO notify.notification_types (key, description, default_enabled, is_transactional) VALUES
  ('money_story.ready',   'Tu Monthly Money Story está lista',                  true, false),
  ('recurring.due_soon',  'Se acerca un pago o ingreso recurrente',             true, false),
  ('goal.milestone',      'Te falta poco para el próximo hito de una meta',     true, false),
  ('goal.achieved',       'Alcanzaste una meta',                                true, false),
  ('security.new_login',  'Nuevo inicio de sesión en tu cuenta',                true, true),
  ('subscription.status', 'Cambios en tu suscripción',                          true, true),
  ('subscription.renewal_failed', 'No pudimos cobrar tu suscripción',           true, true),
  ('subscription.ending',  'Tu plan de pago termina pronto',                    true, false),
  ('subscription.reverted_to_free', 'Tu cuenta volvió al plan gratuito',       true, true)
ON CONFLICT (key) DO NOTHING;

-- IA: tareas, modelos y orden de proveedores (FTR-007)
-- Precios oficiales consultados el 13-10-2026, en USD. El orden de las rutas es
-- PROVISIONAL hasta que la prueba de concepto elija el principal:
--   SELECT ai.set_route_order('voice.extract', ARRAY['…principal…', '…respaldo…'], 'motivo');
INSERT INTO ai.tasks (key, model_kind, description) VALUES
  ('voice.transcribe', 'stt', 'Convierte el audio del dictado en texto'),
  ('voice.extract',    'llm', 'Convierte la frase en un movimiento: tipo, monto, moneda, categoría, cuenta, descripción y fecha')
ON CONFLICT (key) DO NOTHING;

INSERT INTO ai.models (code, provider, model, kind, price_per_minute_usd, min_billed_seconds,
                       input_per_mtok_usd, cached_input_per_mtok_usd, output_per_mtok_usd,
                       is_active, shutdown_on, prices_checked_on, notes) VALUES
  -- Voz a texto
  ('openai.gpt-transcribe',        'openai',   'gpt-transcribe',        'stt', 0.004500,  0, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Reemplazo de whisper-1 en la API de OpenAI. Acepta pistas de palabras (comercios, categorías)'),
  ('groq.whisper-large-v3-turbo',  'groq',     'whisper-large-v3-turbo','stt', 0.000667, 10, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Whisper (modelo abierto de OpenAI) servido por Groq: 0,04 USD por hora; cobra mínimo 10 s por llamada'),
  ('groq.whisper-large-v3',        'groq',     'whisper-large-v3',      'stt', 0.001850, 10, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Whisper large v3 completo en Groq: 0,111 USD por hora; cobra mínimo 10 s'),
  ('deepgram.nova-3',              'deepgram', 'nova-3',                'stt', 0.004300,  0, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Audio pregrabado, un idioma. 200 USD de crédito inicial'),
  ('openai.whisper-1',             'openai',   'whisper-1',             'stt', 0.006000,  0, NULL, NULL, NULL, false, '2027-02-26', '2026-10-13',
   'Retirado: OpenAI lo apaga el 26-02-2027 y recomienda gpt-transcribe. Precio histórico'),
  -- LLM para extraer el movimiento
  ('openai.gpt-6-luna',            'openai',   'gpt-6-luna',            'llm', NULL, 0, 0.100000, 0.010000, 0.500000, true, NULL, '2026-10-13',
   'Usar reasoning.effort = none y salidas estructuradas (JSON con esquema)'),
  ('deepseek.deepseek-flash',      'deepseek', 'deepseek-flash',        'llm', NULL, 0, 0.300000, 0.006000, 1.200000, true, NULL, '2026-10-13',
   'Precio en hora pico (01-04 y 06-10 UTC, lunes a viernes); fuera de pico cuesta la mitad. Usar modo sin razonamiento. Datos procesados en China'),
  ('anthropic.claude-haiku-5-5',   'anthropic','claude-haiku-5-5',      'llm', NULL, 0, 0.100000, 0.010000, 0.500000, true, NULL, '2026-10-13',
   'Precio para prompts de hasta 100.000 tokens. Anthropic no ofrece voz a texto'),
  ('google.gemini-3.1-flash-lite', 'google',   'gemini-3.1-flash-lite', 'llm', NULL, 0, 0.250000, NULL,     1.500000, true, NULL, '2026-10-13',
   'Corre en Google Cloud, la misma nube del backend')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ai.routes (task, position, model_code, timeout_ms, max_retries) VALUES
  ('voice.transcribe', 1, 'openai.gpt-transcribe',       10000, 1),
  ('voice.transcribe', 2, 'groq.whisper-large-v3-turbo', 10000, 1),
  ('voice.transcribe', 3, 'deepgram.nova-3',             10000, 0),
  ('voice.extract',    1, 'openai.gpt-6-luna',            6000, 1),
  ('voice.extract',    2, 'deepseek.deepseek-flash',      6000, 1),
  ('voice.extract',    3, 'anthropic.claude-haiku-5-5',   6000, 0)
ON CONFLICT DO NOTHING;

-- Primeras particiones mensuales (luego las crea un job mensual de Celery Beat)
SELECT core.ensure_monthly_partitions('core.audit_log',       current_date, 4);
SELECT core.ensure_monthly_partitions('notify.notifications', current_date, 4);
SELECT core.ensure_monthly_partitions('ai.voice_entries',     current_date, 4);
SELECT core.ensure_monthly_partitions('ai.calls',             current_date, 4);
SELECT core.ensure_monthly_partitions('ops.logs',             current_date, 4);

-- Las particiones nuevas solo se acceden a través de la tabla padre
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS part
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('core', 'notify', 'ai', 'ops') AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format('REVOKE ALL ON %s FROM moneymap_app, moneymap_worker, moneymap_ops', r.part);
  END LOOP;
END $$;
-- =============================================================================
-- MoneyMap · 990 · comentarios de tablas y columnas
-- La descripción de cada tabla (para qué sirve, quién la escribe y un ejemplo)
-- y de cada columna. DBeaver las muestra, y DICCIONARIO_CAMPOS.md se genera
-- desde aquí con tools/dictionary.sql y tools/build_dictionary.py.
-- Al agregar una columna, agrega también su comentario en este archivo.
-- =============================================================================

-- ai.calls
COMMENT ON TABLE ai.calls IS
  'Cada llamada a un proveedor de IA, exitosa o no: estado, latencia, tokens o audio y costo. El detalle de un error va a ops.logs. Particionada por mes. Quién escribe: el worker (solo inserta). Ejemplo: DeepSeek extrajo en 1.400 ms con 800/100 tokens, 0,00036 USD.';
COMMENT ON COLUMN ai.calls.id IS 'Identificador; la clave primaria es (created_at, id)';
COMMENT ON COLUMN ai.calls.created_at IS 'Cuándo se hizo la llamada; define la partición mensual';
COMMENT ON COLUMN ai.calls.task IS 'Paso: voice.transcribe o voice.extract';
COMMENT ON COLUMN ai.calls.model_code IS 'Modelo llamado';
COMMENT ON COLUMN ai.calls.route_position IS 'Posición del modelo en la ruta: 1 = principal; 2 o más = respaldo';
COMMENT ON COLUMN ai.calls.attempt IS 'Número de intento con ese modelo (2 = primer reintento). Por defecto 1';
COMMENT ON COLUMN ai.calls.status IS 'ok, error, timeout, rate_limited, invalid_output o circuit_open (saltada porque el proveedor venía fallando). El mensaje del error va a ops.logs';
COMMENT ON COLUMN ai.calls.user_id IS 'Usuario del dictado (sin FK)';
COMMENT ON COLUMN ai.calls.voice_entry_id IS 'Dictado al que pertenece (sin FK)';
COMMENT ON COLUMN ai.calls.voice_entry_created_at IS 'Fecha del dictado, para encontrarlo en su partición; va junto con voice_entry_id';
COMMENT ON COLUMN ai.calls.latency_ms IS 'Cuánto tardó';
COMMENT ON COLUMN ai.calls.audio_seconds IS 'Segundos de audio enviados (voz a texto)';
COMMENT ON COLUMN ai.calls.input_tokens IS 'Tokens de entrada (LLM)';
COMMENT ON COLUMN ai.calls.cached_input_tokens IS 'De esos, cuántos venían de caché (más baratos)';
COMMENT ON COLUMN ai.calls.output_tokens IS 'Tokens de salida (LLM)';
COMMENT ON COLUMN ai.calls.cost_usd IS 'Costo en dólares. Si no se envía, lo calcula un trigger con el precio de ai.models; las llamadas que no llegaron al proveedor cuestan 0';

-- ai.models
COMMENT ON TABLE ai.models IS
  'Modelos de IA disponibles con su precio. Agregar un proveedor es un INSERT aquí y una ruta. Quién escribe: el equipo. Ejemplo: openai.gpt-transcribe, 0,0045 USD por minuto.';
COMMENT ON COLUMN ai.models.code IS 'Clave proveedor.modelo, por ejemplo openai.gpt-transcribe';
COMMENT ON COLUMN ai.models.provider IS 'Proveedor: openai, groq, deepgram, deepseek, anthropic, google';
COMMENT ON COLUMN ai.models.model IS 'Id del modelo que espera la API del proveedor; único por proveedor';
COMMENT ON COLUMN ai.models.kind IS 'stt, llm, audio_llm o vision_llm';
COMMENT ON COLUMN ai.models.price_per_minute_usd IS 'Precio por minuto de audio; obligatorio en stt';
COMMENT ON COLUMN ai.models.min_billed_seconds IS 'Mínimo que cobra el proveedor por llamada (Groq cobra 10 s). Por defecto 0';
COMMENT ON COLUMN ai.models.input_per_mtok_usd IS 'Precio por millón de tokens de entrada; obligatorio en LLM';
COMMENT ON COLUMN ai.models.cached_input_per_mtok_usd IS 'Precio por millón de tokens de entrada en caché';
COMMENT ON COLUMN ai.models.output_per_mtok_usd IS 'Precio por millón de tokens de salida; obligatorio en LLM';
COMMENT ON COLUMN ai.models.is_active IS 'false = no se usa aunque esté en una ruta (apagado de emergencia). Por defecto sí';
COMMENT ON COLUMN ai.models.shutdown_on IS 'Fecha de retiro anunciada por el proveedor; desde ese día sale solo de las rutas';
COMMENT ON COLUMN ai.models.prices_checked_on IS 'Cuándo se verificaron los precios';
COMMENT ON COLUMN ai.models.notes IS 'Notas para el equipo';
COMMENT ON COLUMN ai.models.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ai.models.updated_at IS 'Última modificación; la actualiza un trigger';

-- ai.route_changes
COMMENT ON TABLE ai.route_changes IS
  'Historial de cambios del orden de proveedores: quién, cuándo, el orden anterior, el nuevo y el motivo. Quién escribe: ai.set_route_order(). Ejemplo: Dana puso a DeepSeek de principal por timeouts de OpenAI.';
COMMENT ON COLUMN ai.route_changes.id IS 'Número correlativo del cambio';
COMMENT ON COLUMN ai.route_changes.task IS 'Paso que cambió';
COMMENT ON COLUMN ai.route_changes.changed_at IS 'Cuándo';
COMMENT ON COLUMN ai.route_changes.changed_by IS 'Quién (correo del equipo)';
COMMENT ON COLUMN ai.route_changes.old_order IS 'Orden anterior de modelos activos';
COMMENT ON COLUMN ai.route_changes.new_order IS 'Orden nuevo';
COMMENT ON COLUMN ai.route_changes.reason IS 'Motivo, por ejemplo "OpenAI con timeouts"';

-- ai.routes
COMMENT ON TABLE ai.routes IS
  'Orden de proveedores por tarea: posición 1 = principal, 2+ = respaldos, con tiempo límite y reintentos. Quién escribe: el equipo con ai.set_route_order(). Ejemplo: voice.extract → 1 GPT-6 Luna, 2 DeepSeek, 3 Claude Haiku.';
COMMENT ON COLUMN ai.routes.task IS 'Paso; parte de la clave primaria';
COMMENT ON COLUMN ai.routes.position IS '1 = principal, 2 = primer respaldo…; parte de la clave primaria';
COMMENT ON COLUMN ai.routes.model_code IS 'Modelo que se usa en esa posición';
COMMENT ON COLUMN ai.routes.is_active IS 'Si la posición se usa. Por defecto sí';
COMMENT ON COLUMN ai.routes.timeout_ms IS 'Tiempo máximo de espera (500 a 60.000 ms) antes de pasar al siguiente. Por defecto 8.000';
COMMENT ON COLUMN ai.routes.max_retries IS 'Reintentos con el mismo modelo antes de pasar al siguiente (0 a 3). Por defecto 1';
COMMENT ON COLUMN ai.routes.updated_at IS 'Última modificación; la actualiza un trigger';

-- ai.tasks
COMMENT ON TABLE ai.tasks IS
  'Pasos que hace la IA. Una tarea nueva (por ejemplo leer facturas) es una fila más. Quién escribe: el equipo. Ejemplo: voice.transcribe (voz a texto) y voice.extract (frase a movimiento).';
COMMENT ON COLUMN ai.tasks.key IS 'Clave del paso, por ejemplo voice.transcribe';
COMMENT ON COLUMN ai.tasks.model_kind IS 'Tipo de modelo que necesita: stt (voz a texto), llm, audio_llm o vision_llm';
COMMENT ON COLUMN ai.tasks.description IS 'Qué hace el paso';

-- ai.usage_monthly
COMMENT ON TABLE ai.usage_monthly IS
  'Uso de IA por usuario, mes y tarea: llamadas, fallas, audio, tokens y costo. Permite contar cuánto usa y cuánto cuesta cada usuario sin recorrer ai.calls. Quién escribe: un trigger de ai.calls. Ejemplo: María, octubre, voice.extract: 24 llamadas, 1 fallida, 0,0086 USD.';
COMMENT ON COLUMN ai.usage_monthly.user_id IS 'Usuario (sin FK: el registro de costos sobrevive aunque se borre el usuario); parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.period IS 'Mes (siempre el día 1); parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.task IS 'Tarea: voice.transcribe o voice.extract; parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.calls IS 'Llamadas hechas en el mes, sumando reintentos y respaldos';
COMMENT ON COLUMN ai.usage_monthly.failed_calls IS 'De esas, cuántas no respondieron bien (status distinto de ok)';
COMMENT ON COLUMN ai.usage_monthly.audio_seconds IS 'Segundos de audio enviados (voz a texto)';
COMMENT ON COLUMN ai.usage_monthly.input_tokens IS 'Tokens de entrada enviados al LLM';
COMMENT ON COLUMN ai.usage_monthly.output_tokens IS 'Tokens de salida recibidos del LLM';
COMMENT ON COLUMN ai.usage_monthly.cost_usd IS 'Costo total en dólares, incluidas las llamadas fallidas que se cobraron';
COMMENT ON COLUMN ai.usage_monthly.updated_at IS 'Última vez que se sumó una llamada';

-- ai.voice_entries
COMMENT ON TABLE ai.voice_entries IS
  'Cada dictado (o frase escrita) y su resultado: transcripción, movimiento extraído, modelos que respondieron, intentos y costo. Particionada por mes. Quién escribe: la API lo crea; el worker y los triggers de ai.calls lo completan. Ejemplo: ''gasté 50 en comida'' → gasto de 50 BOB en Restaurantes, confirmado.';
COMMENT ON COLUMN ai.voice_entries.id IS 'Identificador; la clave primaria es (created_at, id)';
COMMENT ON COLUMN ai.voice_entries.created_at IS 'Cuándo se recibió; define la partición mensual';
COMMENT ON COLUMN ai.voice_entries.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN ai.voice_entries.input_type IS 'voice (dictado) o text (frase escrita). Por defecto voice';
COMMENT ON COLUMN ai.voice_entries.status IS 'received, transcribed, extracted, confirmed, discarded o failed. Por defecto received';
COMMENT ON COLUMN ai.voice_entries.audio_seconds IS 'Duración del audio; solo en dictados';
COMMENT ON COLUMN ai.voice_entries.audio_object_key IS 'Ruta del audio en Cloud Storage, solo si el usuario acepta guardarlo';
COMMENT ON COLUMN ai.voice_entries.transcript IS 'Texto transcrito o escrito (hasta 2.000 caracteres)';
COMMENT ON COLUMN ai.voice_entries.stt_model_code IS 'Modelo de voz a texto que respondió; lo completa la base de datos';
COMMENT ON COLUMN ai.voice_entries.llm_model_code IS 'LLM que respondió; lo completa la base de datos';
COMMENT ON COLUMN ai.voice_entries.prompt_version IS 'Versión del prompt, para comparar precisión entre versiones';
COMMENT ON COLUMN ai.voice_entries.extraction IS 'Movimiento extraído en JSON: tipo, monto, moneda, categoría, cuenta, descripción, fecha y lo que falta';
COMMENT ON COLUMN ai.voice_entries.confidence IS 'Confianza del LLM entre 0 y 1';
COMMENT ON COLUMN ai.voice_entries.attempts IS 'Llamadas hechas sumando respaldos. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.fallback_used IS 'true si algún paso lo resolvió un respaldo. Por defecto no';
COMMENT ON COLUMN ai.voice_entries.input_tokens IS 'Tokens de entrada sumados. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.output_tokens IS 'Tokens de salida sumados. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.cost_usd IS 'Costo total del dictado, incluidas las llamadas fallidas. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.latency_ms IS 'Tiempo de punta a punta; lo escribe el worker';
COMMENT ON COLUMN ai.voice_entries.transaction_id IS 'Transacción creada al confirmar; si se borra, queda vacío y el dictado se conserva';
COMMENT ON COLUMN ai.voice_entries.error IS 'Error, si falló';
COMMENT ON COLUMN ai.voice_entries.confirmed_at IS 'Cuándo lo confirmó el usuario';

-- billing.features
COMMENT ON TABLE billing.features IS
  'Funcionalidades que un plan habilita o limita. total = recursos vivos (tarjetas, monedas, metas); month = usos en el mes (dictados, consultas). Quién escribe: el equipo. Ejemplo: finance.cards (límite total), ai.voice_entries (límite al mes).';
COMMENT ON COLUMN billing.features.key IS 'Clave, por ejemplo finance.cards o ai.voice_entries';
COMMENT ON COLUMN billing.features.description IS 'Qué significa, para el equipo';
COMMENT ON COLUMN billing.features.value_type IS 'boolean (sí o no) o limit (con un número máximo)';
COMMENT ON COLUMN billing.features.limit_period IS 'Solo en limit: total (por ejemplo, tarjetas activas) o month (por ejemplo, dictados al mes)';

-- billing.payments
COMMENT ON TABLE billing.payments IS
  'Cada cobro, renovación o reembolso informado por las tiendas. La clave (provider, provider_transaction_id) evita registrar dos veces el mismo cobro. Quién escribe: los workers. Ejemplo: App Store, renovación, 4,99 USD.';
COMMENT ON COLUMN billing.payments.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.payments.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.payments.subscription_id IS 'Suscripción cobrada; si se borra, queda vacío';
COMMENT ON COLUMN billing.payments.plan_price_id IS 'Precio cobrado';
COMMENT ON COLUMN billing.payments.provider IS 'app_store, play_store, web o internal';
COMMENT ON COLUMN billing.payments.provider_transaction_id IS 'Id del cobro en la tienda';
COMMENT ON COLUMN billing.payments.kind IS 'initial, renewal, upgrade, refund o chargeback';
COMMENT ON COLUMN billing.payments.status IS 'pending, succeeded, failed o refunded';
COMMENT ON COLUMN billing.payments.amount IS 'Monto cobrado; negativo en reembolsos';
COMMENT ON COLUMN billing.payments.currency IS 'Moneda local que cobró la tienda';
COMMENT ON COLUMN billing.payments.billing_period IS 'month o year';
COMMENT ON COLUMN billing.payments.period_start IS 'Inicio del periodo pagado';
COMMENT ON COLUMN billing.payments.period_end IS 'Fin del periodo pagado';
COMMENT ON COLUMN billing.payments.store_fee IS 'Comisión de la tienda, si se conoce';
COMMENT ON COLUMN billing.payments.occurred_at IS 'Cuándo ocurrió el cobro';
COMMENT ON COLUMN billing.payments.created_at IS 'Cuándo se creó la fila';

-- billing.plan_features
COMMENT ON TABLE billing.plan_features IS
  'Cuánto permite cada plan de cada funcionalidad. Cambiar un límite es un UPDATE, sin desplegar. Quién escribe: el equipo. Ejemplo: free → finance.cards 1, finance.currencies 1, ai.voice_entries 30.';
COMMENT ON COLUMN billing.plan_features.plan_id IS 'Plan; parte de la clave primaria. Si se borra el plan, se borran sus filas';
COMMENT ON COLUMN billing.plan_features.feature_key IS 'Funcionalidad; parte de la clave primaria';
COMMENT ON COLUMN billing.plan_features.is_enabled IS 'Si el plan la incluye. Por defecto sí';
COMMENT ON COLUMN billing.plan_features.limit_value IS 'Máximo permitido; vacío = ilimitado. 0 = nada (el plan gratuito tiene 0 tarjetas)';

-- billing.plan_prices
COMMENT ON TABLE billing.plan_prices IS
  'Precio mensual y anual de cada plan de pago, con el producto de App Store y de Google Play. Un cambio de precio es una fila nueva: quien ya pagaba conserva su precio. Quién escribe: el equipo. Ejemplo: paid_1 mensual 4,99 USD, mm.plus.monthly.';
COMMENT ON COLUMN billing.plan_prices.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.plan_prices.plan_id IS 'Plan al que pertenece';
COMMENT ON COLUMN billing.plan_prices.billing_period IS 'month o year';
COMMENT ON COLUMN billing.plan_prices.currency IS 'Moneda del precio';
COMMENT ON COLUMN billing.plan_prices.amount IS 'Precio por periodo, mayor que 0';
COMMENT ON COLUMN billing.plan_prices.trial_days IS 'Días de prueba gratis (0 a 90). Por defecto 0';
COMMENT ON COLUMN billing.plan_prices.app_store_product_id IS 'Id del producto en App Store';
COMMENT ON COLUMN billing.plan_prices.play_store_product_id IS 'Id del producto y plan base en Google Play';
COMMENT ON COLUMN billing.plan_prices.web_price_id IS 'Id en una pasarela web, si algún día se cobra fuera de las tiendas';
COMMENT ON COLUMN billing.plan_prices.is_active IS 'Si se ofrece a suscriptores nuevos. Por defecto sí';
COMMENT ON COLUMN billing.plan_prices.valid_from IS 'Desde cuándo rige el precio';
COMMENT ON COLUMN billing.plan_prices.valid_until IS 'Hasta cuándo rige; vacío = vigente';
COMMENT ON COLUMN billing.plan_prices.created_at IS 'Cuándo se creó la fila';

-- billing.plans
COMMENT ON TABLE billing.plans IS
  'Planes de la app: uno gratuito (tier 0) y tres de pago. Quién escribe: el equipo. Ejemplo: free, paid_1, paid_2, paid_3.';
COMMENT ON COLUMN billing.plans.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.plans.code IS 'Código interno: free, paid_1, paid_2, paid_3; único';
COMMENT ON COLUMN billing.plans.name IS 'Nombre comercial';
COMMENT ON COLUMN billing.plans.description IS 'Descripción para la pantalla de planes';
COMMENT ON COLUMN billing.plans.tier IS 'Nivel: 0 = gratuito, mayor = plan superior; único. Sirve para saber si un cambio es subida o bajada';
COMMENT ON COLUMN billing.plans.is_public IS 'Si se muestra en la pantalla de planes. Por defecto sí';
COMMENT ON COLUMN billing.plans.is_active IS 'Si se puede contratar. Por defecto sí';
COMMENT ON COLUMN billing.plans.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN billing.plans.updated_at IS 'Última modificación; la actualiza un trigger';

-- billing.subscription_changes
COMMENT ON TABLE billing.subscription_changes IS
  'Historial de cada cambio de suscripción: alta, renovación, subida o bajada de plan, cancelación, expiración, vuelta a gratuito. Quién escribe: un trigger de billing.subscriptions; nadie lo edita. Ejemplo: 14-10 started; 20-10 period_changed (mensual → anual).';
COMMENT ON COLUMN billing.subscription_changes.seq IS 'Número correlativo del cambio';
COMMENT ON COLUMN billing.subscription_changes.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.subscription_changes.subscription_id IS 'Suscripción que cambió; si se borra, queda vacío y el historial se conserva';
COMMENT ON COLUMN billing.subscription_changes.change_type IS 'Qué pasó: started, renewed, upgraded, downgraded, period_changed, auto_renew_disabled, expired, reverted_to_free y otros 13 tipos';
COMMENT ON COLUMN billing.subscription_changes.from_plan_id IS 'Plan anterior';
COMMENT ON COLUMN billing.subscription_changes.to_plan_id IS 'Plan nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_price_id IS 'Precio anterior';
COMMENT ON COLUMN billing.subscription_changes.to_price_id IS 'Precio nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_period IS 'Periodo anterior (month o year)';
COMMENT ON COLUMN billing.subscription_changes.to_period IS 'Periodo nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_status IS 'Estado anterior';
COMMENT ON COLUMN billing.subscription_changes.to_status IS 'Estado nuevo';
COMMENT ON COLUMN billing.subscription_changes.source IS 'Quién lo originó: store_webhook, user, admin, job o system. Por defecto system';
COMMENT ON COLUMN billing.subscription_changes.effective_at IS 'Cuándo tuvo efecto';

-- billing.subscription_events
COMMENT ON TABLE billing.subscription_events IS
  'Avisos crudos recibidos de App Store y Google Play, para procesarlos una sola vez y poder reintentarlos. Quién escribe: el worker de webhooks. Ejemplo: DID_RENEW recibido a las 10:02, procesado a las 10:02.';
COMMENT ON COLUMN billing.subscription_events.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.subscription_events.subscription_id IS 'Suscripción a la que se refiere, una vez identificada';
COMMENT ON COLUMN billing.subscription_events.provider IS 'Tienda que la envió';
COMMENT ON COLUMN billing.subscription_events.provider_event_id IS 'Id del aviso en la tienda';
COMMENT ON COLUMN billing.subscription_events.event_type IS 'Tipo de aviso según la tienda';
COMMENT ON COLUMN billing.subscription_events.payload IS 'Contenido completo del aviso, en JSON';
COMMENT ON COLUMN billing.subscription_events.received_at IS 'Cuándo llegó';
COMMENT ON COLUMN billing.subscription_events.processed_at IS 'Cuándo lo procesó el worker; vacío = pendiente';
COMMENT ON COLUMN billing.subscription_events.error IS 'Error al procesarlo, si lo hubo';

-- billing.subscriptions
COMMENT ON TABLE billing.subscriptions IS
  'Suscripción de un usuario a un plan de pago, mensual o anual, con su estado. Sin suscripción con acceso, el usuario está en el plan gratuito. Quién escribe: los workers que procesan los avisos de App Store y Google Play. Ejemplo: María en paid_1 mensual, activa hasta el 14-11.';
COMMENT ON COLUMN billing.subscriptions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.subscriptions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.subscriptions.plan_id IS 'Plan contratado';
COMMENT ON COLUMN billing.subscriptions.plan_price_id IS 'Precio contratado; la FK (plan_price_id, plan_id, billing_period) exige que sea de ese plan y ese periodo';
COMMENT ON COLUMN billing.subscriptions.billing_period IS 'month o year';
COMMENT ON COLUMN billing.subscriptions.status IS 'trialing, active, grace_period, on_hold, paused, expired o revoked. Los tres primeros dan acceso al plan de pago';
COMMENT ON COLUMN billing.subscriptions.provider IS 'Dónde se pagó: app_store, play_store, web o internal';
COMMENT ON COLUMN billing.subscriptions.provider_subscription_id IS 'Id en la tienda (original_transaction_id en App Store, purchase token en Google Play); único por tienda';
COMMENT ON COLUMN billing.subscriptions.auto_renew IS 'false = el usuario canceló; conserva el acceso hasta current_period_end. Por defecto sí';
COMMENT ON COLUMN billing.subscriptions.started_at IS 'Cuándo empezó la suscripción';
COMMENT ON COLUMN billing.subscriptions.trial_ends_at IS 'Fin de la prueba gratis';
COMMENT ON COLUMN billing.subscriptions.current_period_start IS 'Inicio del periodo pagado actual';
COMMENT ON COLUMN billing.subscriptions.current_period_end IS 'Hasta cuándo tiene acceso pagado';
COMMENT ON COLUMN billing.subscriptions.grace_period_ends_at IS 'Fin del periodo de gracia tras un cobro fallido';
COMMENT ON COLUMN billing.subscriptions.pending_plan_price_id IS 'Cambio programado para el fin del periodo (por ejemplo, de mensual a anual)';
COMMENT ON COLUMN billing.subscriptions.pending_change_at IS 'Cuándo se aplica el cambio programado; existe solo junto con pending_plan_price_id';
COMMENT ON COLUMN billing.subscriptions.canceled_at IS 'Cuándo apagó la renovación';
COMMENT ON COLUMN billing.subscriptions.cancel_reason IS 'user, billing_error, refund, price_increase_declined, replaced u other';
COMMENT ON COLUMN billing.subscriptions.ended_at IS 'Cuándo perdió el acceso; existe solo si status es expired o revoked';
COMMENT ON COLUMN billing.subscriptions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN billing.subscriptions.updated_at IS 'Última modificación; la actualiza un trigger';

-- billing.usage_counters
COMMENT ON TABLE billing.usage_counters IS
  'Usos del mes de las funcionalidades con límite mensual. Se descuentan con billing.try_consume() y se devuelven con billing.release(). Quién escribe: esas funciones. Ejemplo: María, ai.voice_entries, octubre: 12 usados.';
COMMENT ON COLUMN billing.usage_counters.user_id IS 'Usuario; parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.feature_key IS 'Funcionalidad; parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.period_start IS 'Mes (día 1); parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.used IS 'Usos en el mes. billing.release() lo devuelve si la acción falló por nosotros. Por defecto 0';
COMMENT ON COLUMN billing.usage_counters.updated_at IS 'Última vez que se sumó o devolvió un uso';

-- catalog.account_types
COMMENT ON TABLE catalog.account_types IS
  'Tipos de cuenta: efectivo y tarjeta (sin distinguir débito de crédito). De aquí sale si un movimiento se pagó en efectivo o con tarjeta (is_card). Quién escribe: el equipo. Ejemplo: card, Tarjeta, es tarjeta.';
COMMENT ON COLUMN catalog.account_types.code IS 'Clave: cash (efectivo) o card (tarjeta)';
COMMENT ON COLUMN catalog.account_types.names IS 'Nombre por idioma en JSON; el español es obligatorio';
COMMENT ON COLUMN catalog.account_types.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN catalog.account_types.is_card IS 'true = es una tarjeta: cuenta para el límite de tarjetas del plan y sus movimientos se pagan "con tarjeta". false = efectivo';
COMMENT ON COLUMN catalog.account_types.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN catalog.account_types.is_active IS 'Si se puede usar; desactivar no borra nada. Por defecto sí';

-- catalog.category_templates
COMMENT ON TABLE catalog.category_templates IS
  'Categorías iniciales que recibe cada usuario nuevo. Solo categorías, sin subcategorías. Quién escribe: el equipo. Ejemplo: groceries (Supermercado), gasto, grupo Necesidades.';
COMMENT ON COLUMN catalog.category_templates.key IS 'Clave en minúsculas, por ejemplo groceries';
COMMENT ON COLUMN catalog.category_templates.kind IS 'income (ingreso) o expense (gasto). Lista fija catalog.money_kind';
COMMENT ON COLUMN catalog.category_templates.flow_group IS 'Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos';
COMMENT ON COLUMN catalog.category_templates.names IS 'Nombre por idioma en JSON, por ejemplo {"es": "Comida", "en": "Food"}; el español es obligatorio';
COMMENT ON COLUMN catalog.category_templates.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN catalog.category_templates.color IS 'Color en hexadecimal (#RRGGBB)';
COMMENT ON COLUMN catalog.category_templates.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN catalog.category_templates.is_active IS 'Si se puede usar; desactivar no borra nada. Por defecto sí';

-- catalog.countries
COMMENT ON TABLE catalog.countries IS
  'Países (ISO 3166-1) con su moneda local. Sirve para el país del perfil y para mostrar los bancos de cada país. Quién escribe: el equipo; agregar un país es un INSERT. Ejemplo: BO, Bolivia, BOB.';
COMMENT ON COLUMN catalog.countries.code IS 'Código ISO 3166-1 de 2 letras, por ejemplo BO';
COMMENT ON COLUMN catalog.countries.name IS 'Nombre del país en español';
COMMENT ON COLUMN catalog.countries.currency IS 'Moneda local del país (opcional); la app la propone como moneda principal';
COMMENT ON COLUMN catalog.countries.is_active IS 'Si se ofrece en la app. Por defecto sí';
COMMENT ON COLUMN catalog.countries.sort_order IS 'Orden en el selector. Por defecto 100';

-- catalog.currencies
COMMENT ON TABLE catalog.currencies IS
  'Monedas que ofrece la app (ISO 4217). Agregar una es un INSERT; desactivarla la oculta para cuentas nuevas sin tocar lo existente. Quién escribe: el equipo. Ejemplo: BOB, Boliviano, Bs, 2 decimales.';
COMMENT ON COLUMN catalog.currencies.code IS 'Código ISO de 3 letras, por ejemplo BOB';
COMMENT ON COLUMN catalog.currencies.name IS 'Nombre de la moneda';
COMMENT ON COLUMN catalog.currencies.symbol IS 'Símbolo, por ejemplo Bs o $';
COMMENT ON COLUMN catalog.currencies.decimals IS 'Cuántos decimales acepta un monto en esta moneda: BOB y USD 2, CLP y PYG 0 (0 a 4). Por defecto 2. 1000,5 pesos chilenos se rechaza (invalid_amount)';
COMMENT ON COLUMN catalog.currencies.is_active IS 'Si se ofrece en la app. Inactiva = no se acepta en cuentas, metas, moneda principal ni Mis monedas nuevos; las cuentas que ya existen siguen registrando. Por defecto sí';
COMMENT ON COLUMN catalog.currencies.sort_order IS 'Orden en el selector, después de Mis monedas. Por defecto 100';

-- catalog.financial_institutions
COMMENT ON TABLE catalog.financial_institutions IS
  'Bancos, cooperativas, microfinancieras y billeteras de cada país que emiten tarjetas. La app muestra la lista del país del usuario en vez de pedir el nombre como texto. Quién escribe: el equipo. Ejemplo: bo.bnb, Banco Nacional de Bolivia (BNB), banco.';
COMMENT ON COLUMN catalog.financial_institutions.code IS 'Clave: país en minúsculas, punto y nombre corto, por ejemplo bo.bnb';
COMMENT ON COLUMN catalog.financial_institutions.country_code IS 'País de la institución';
COMMENT ON COLUMN catalog.financial_institutions.name IS 'Nombre completo, por ejemplo Banco Nacional de Bolivia';
COMMENT ON COLUMN catalog.financial_institutions.short_name IS 'Nombre corto que muestra la app, por ejemplo BNB; único dentro del país';
COMMENT ON COLUMN catalog.financial_institutions.kind IS 'bank (banco), cooperative (cooperativa), microfinance (microfinanciera) o fintech (billetera o banco digital). Por defecto bank';
COMMENT ON COLUMN catalog.financial_institutions.is_active IS 'Si se ofrece en la app; desactivarla no afecta las tarjetas que ya la usan. Por defecto sí';
COMMENT ON COLUMN catalog.financial_institutions.sort_order IS 'Orden en la lista: los más usados primero. Por defecto 100';

-- core.audit_log
COMMENT ON TABLE core.audit_log IS
  'Historial de quién cambió qué dato sensible (cuentas, configuración, metas, suscripciones), solo con las columnas que cambiaron. Particionada por mes. Quién escribe: triggers de auditoría. Ejemplo: María cambió el nombre de su cuenta de ''Efectivo'' a ''Billetera''.';
COMMENT ON COLUMN core.audit_log.id IS 'Identificador; la clave primaria es (occurred_at, id)';
COMMENT ON COLUMN core.audit_log.occurred_at IS 'Cuándo; define la partición mensual';
COMMENT ON COLUMN core.audit_log.actor_user_id IS 'Quién hizo el cambio';
COMMENT ON COLUMN core.audit_log.owner_user_id IS 'De quién es el dato cambiado';
COMMENT ON COLUMN core.audit_log.entity IS 'Tabla, por ejemplo finance.accounts';
COMMENT ON COLUMN core.audit_log.entity_id IS 'Id de la fila';
COMMENT ON COLUMN core.audit_log.action IS 'insert, update, delete, login, export o plan_change';
COMMENT ON COLUMN core.audit_log.changes IS 'Columnas cambiadas con su valor antes y después, en JSON';
COMMENT ON COLUMN core.audit_log.ip IS 'IP de origen';

-- core.outbox_events
COMMENT ON TABLE core.outbox_events IS
  'Eventos de dominio pendientes de publicar (patrón outbox): se escriben en la misma transacción que el cambio y un worker los envía a Celery. Quién escribe: la API y los workers; el worker los marca publicados. Ejemplo: transaction.created de María.';
COMMENT ON COLUMN core.outbox_events.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN core.outbox_events.aggregate_type IS 'Tipo de entidad: transaction, goal, subscription…';
COMMENT ON COLUMN core.outbox_events.aggregate_id IS 'Id de la entidad';
COMMENT ON COLUMN core.outbox_events.user_id IS 'Dueño del dato, si aplica';
COMMENT ON COLUMN core.outbox_events.event_type IS 'Evento, por ejemplo transaction.created';
COMMENT ON COLUMN core.outbox_events.payload IS 'Datos del evento en JSON';
COMMENT ON COLUMN core.outbox_events.occurred_at IS 'Cuándo ocurrió';
COMMENT ON COLUMN core.outbox_events.published_at IS 'Cuándo se publicó; vacío = pendiente';
COMMENT ON COLUMN core.outbox_events.attempts IS 'Intentos de publicación. Por defecto 0';

-- finance.accounts
COMMENT ON TABLE finance.accounts IS
  'Dónde está el dinero del usuario: su efectivo y sus tarjetas, cada una con su saldo. Una moneda por cuenta y una sola cuenta por defecto. Quién escribe: la API (crear, renombrar, archivar); los triggers (saldo, cuenta por defecto, límites del plan). Ejemplo: ''Tarjeta BNB Bs'', tarjeta, BOB, saldo 1.525,40.';
COMMENT ON COLUMN finance.accounts.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.accounts.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.accounts.name IS 'Nombre que le da el usuario (1 a 80 caracteres)';
COMMENT ON COLUMN finance.accounts.type IS 'cash (efectivo) o card (tarjeta). Las dos tienen saldo. Crear una tarjeta, desarchivarla o convertir una cuenta en tarjeta cuenta para el límite de tarjetas del plan. No cambia si la cuenta ya tiene movimientos';
COMMENT ON COLUMN finance.accounts.currency IS 'Moneda de la cuenta; debe estar activa. Todo lo que pasa en la cuenta queda en esta moneda. Para tener Bs y USD se crean dos cuentas; una moneda nueva cuenta para el límite de monedas del plan. Solo se corrige mientras la cuenta no tenga movimientos ni recurrentes (account_currency_locked)';
COMMENT ON COLUMN finance.accounts.opening_balance IS 'Saldo con el que se creó la cuenta. Por defecto 0';
COMMENT ON COLUMN finance.accounts.current_balance IS 'Saldo actual. Lo mantiene un trigger con cada movimiento; la API no lo escribe. En tarjetas de crédito es negativo (deuda). Por defecto 0';
COMMENT ON COLUMN finance.accounts.is_default IS 'Cuenta por defecto: la que la app propone primero en Quick Add, voz y escaneo. Una sola por usuario. La primera cuenta lo es sola; marcar otra desmarca la anterior; si se archiva, pasa a la siguiente cuenta activa';
COMMENT ON COLUMN finance.accounts.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN finance.accounts.archived_at IS 'Archivada: se oculta en la app y conserva su historial. Una cuenta archivada no cuenta para los límites del plan ni puede ser la cuenta por defecto';
COMMENT ON COLUMN finance.accounts.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.accounts.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.accounts.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.cards
COMMENT ON TABLE finance.cards IS
  'Datos que solo tienen las tarjetas (1 a 1 con su cuenta): banco emisor del catálogo y últimos 4 dígitos. El saldo y la moneda están en finance.accounts. Quién escribe: la API al crear o editar una tarjeta. Ejemplo: Visa del BNB ••9012.';
COMMENT ON COLUMN finance.cards.account_id IS 'Cuenta de tipo tarjeta a la que pertenecen estos datos; es también la clave primaria (1 a 1)';
COMMENT ON COLUMN finance.cards.user_id IS 'Usuario dueño; junto con account_id y account_type asegura que la tarjeta sea suya';
COMMENT ON COLUMN finance.cards.account_type IS 'Siempre card: junto con account_id asegura que la cuenta sea una tarjeta. El efectivo no puede tener fila aquí';
COMMENT ON COLUMN finance.cards.institution_code IS 'Banco emisor, elegido de catalog.financial_institutions (opcional)';
COMMENT ON COLUMN finance.cards.last4 IS 'Últimos 4 dígitos para reconocer la tarjeta (opcional). Nunca se guarda el número completo';
COMMENT ON COLUMN finance.cards.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.cards.updated_at IS 'Última modificación; la actualiza un trigger';

-- finance.categories
COMMENT ON TABLE finance.categories IS
  'Categorías de cada usuario: copia editable de las iniciales más las que cree. kind dice si es ingreso o gasto; flow_group, a qué nodo del Money Flow va un gasto. Quién escribe: finance.setup_user() al registrarse; la API cuando el usuario crea, renombra o borra. Ejemplo: ''Supermercado'', gasto, Necesidades.';
COMMENT ON COLUMN finance.categories.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.categories.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.categories.template_key IS 'Plantilla de la que salió; se conserva aunque el usuario la renombre';
COMMENT ON COLUMN finance.categories.kind IS 'income (ingreso) o expense (gasto). Decide si un movimiento suma o resta, y no deja registrar un gasto en una categoría de ingreso';
COMMENT ON COLUMN finance.categories.flow_group IS 'Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos';
COMMENT ON COLUMN finance.categories.name IS 'Nombre que ve el usuario (1 a 60 caracteres)';
COMMENT ON COLUMN finance.categories.icon IS 'Nombre del ícono. Por defecto label';
COMMENT ON COLUMN finance.categories.color IS 'Color en hexadecimal. Por defecto #6B7280';
COMMENT ON COLUMN finance.categories.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN finance.categories.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.categories.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.categories.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.recurring_rules
COMMENT ON TABLE finance.recurring_rules IS
  'Gastos e ingresos que se repiten: alquiler, sueldo, Netflix. Sirven para recordatorios, para registrarse solos (auto_post) y para restarse en Safe to Spend (is_committed). Ingreso o gasto sale de su categoría. Quién escribe: la API (onboarding y Ajustes); el worker avanza next_due_on. Ejemplo: Alquiler, 1.500 Bs desde Efectivo, mensual desde el 31-01.';
COMMENT ON COLUMN finance.recurring_rules.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.recurring_rules.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.recurring_rules.account_id IS 'Cuenta de la que sale o a la que entra; debe ser del mismo usuario';
COMMENT ON COLUMN finance.recurring_rules.category_id IS 'Categoría del mismo usuario. De ella sale si la regla es un ingreso o un gasto';
COMMENT ON COLUMN finance.recurring_rules.amount IS 'Monto de cada repetición, mayor que 0';
COMMENT ON COLUMN finance.recurring_rules.currency IS 'Moneda de la cuenta; si no se envía, la completa la base de datos y otra se rechaza (currency_mismatch)';
COMMENT ON COLUMN finance.recurring_rules.description IS 'Texto que ve el usuario (1 a 120 caracteres)';
COMMENT ON COLUMN finance.recurring_rules.frequency IS 'weekly (cada semana), biweekly (cada 2 semanas), monthly (cada mes) o yearly (cada año). Las fechas se cuentan desde start_date: un pago del 31 cae el 28 o 29 en febrero y vuelve al 31';
COMMENT ON COLUMN finance.recurring_rules.start_date IS 'Desde cuándo rige';
COMMENT ON COLUMN finance.recurring_rules.end_date IS 'Hasta cuándo rige; vacío = sin fin';
COMMENT ON COLUMN finance.recurring_rules.next_due_on IS 'Próximo vencimiento; si no se envía, es start_date. De aquí salen los recordatorios y lo comprometido del periodo. El worker lo avanza con finance.next_occurrence()';
COMMENT ON COLUMN finance.recurring_rules.is_committed IS 'Si Safe to Spend lo resta como gasto comprometido. Por defecto sí';
COMMENT ON COLUMN finance.recurring_rules.auto_post IS 'Si al vencer se registra solo como transacción. Por defecto no';
COMMENT ON COLUMN finance.recurring_rules.remind_days_before IS 'Días de anticipación del recordatorio (0 a 14). Por defecto 1';
COMMENT ON COLUMN finance.recurring_rules.is_active IS 'Si la regla sigue vigente. Por defecto sí';
COMMENT ON COLUMN finance.recurring_rules.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.recurring_rules.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.recurring_rules.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.transactions
COMMENT ON TABLE finance.transactions IS
  'Cada ingreso, gasto o transferencia, en la moneda de su cuenta. Es la tabla más grande: está dividida en 16 particiones por usuario. Guarda la moneda (copia de la de su cuenta) para sumar por moneda sin unir tablas. Quién escribe: la API (Quick Add, voz, escaneo) y el worker (recurrentes); los triggers ajustan los saldos. Ejemplo: gasto de 105 Bs, ''Netflix'', con la tarjeta BNB el 14-10.';
COMMENT ON COLUMN finance.transactions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.transactions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.transactions.kind IS 'income (ingreso, suma al saldo), expense (gasto, resta) o transfer (transferencia entre dos cuentas propias). Debe coincidir con el tipo de su categoría';
COMMENT ON COLUMN finance.transactions.account_id IS 'Cuenta de origen. La FK compuesta (user_id, account_id, currency) exige que sea del mismo usuario y que currency sea su moneda';
COMMENT ON COLUMN finance.transactions.category_id IS 'Categoría del mismo usuario y del mismo tipo; vacía solo en transferencias';
COMMENT ON COLUMN finance.transactions.amount IS 'Monto en la moneda de la cuenta, mayor que 0 y con los decimales de esa moneda; de aquí sale el saldo';
COMMENT ON COLUMN finance.transactions.currency IS 'Moneda de la cuenta, copiada aquí para sumar por moneda sin unir con accounts. Si no se envía, la completa la base de datos; otra se rechaza (currency_mismatch)';
COMMENT ON COLUMN finance.transactions.transfer_account_id IS 'Cuenta de destino; solo en transferencias, activa, del mismo usuario y en la misma moneda (transfer_currency_mismatch)';
COMMENT ON COLUMN finance.transactions.occurred_on IS 'Fecha del movimiento';
COMMENT ON COLUMN finance.transactions.description IS 'Qué fue, en palabras del usuario (hasta 200 caracteres): ''Netflix'', ''Almuerzo''. Se busca por texto y sirve para sugerir categoría y cuenta en Quick Add (finance.suggest_from_history)';
COMMENT ON COLUMN finance.transactions.source IS 'Cómo se registró: manual, quick_add, voice (dictado), scan (factura), recurring (lo registró un recurrente), onboarding o adjustment (corrección de saldo). Por defecto manual';
COMMENT ON COLUMN finance.transactions.recurring_rule_id IS 'Regla recurrente que lo generó; si se borra la regla, queda vacío';
COMMENT ON COLUMN finance.transactions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.transactions.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.transactions.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.user_currencies
COMMENT ON TABLE finance.user_currencies IS
  'Mis monedas: las que el usuario ve primero al elegir moneda. Se llena sola con la moneda principal y las de sus cuentas. Quién escribe: triggers, y la API cuando el usuario agrega o quita una. Ejemplo: María tiene BOB y USD.';
COMMENT ON COLUMN finance.user_currencies.user_id IS 'Usuario dueño; parte de la clave primaria';
COMMENT ON COLUMN finance.user_currencies.currency IS 'Moneda; debe estar activa al agregarla. No se puede quitar la moneda principal ni la de una cuenta activa';
COMMENT ON COLUMN finance.user_currencies.sort_order IS 'Orden en el selector de monedas. Por defecto 0';
COMMENT ON COLUMN finance.user_currencies.created_at IS 'Cuándo se creó la fila';

-- finance.user_settings
COMMENT ON TABLE finance.user_settings IS
  'Configuración financiera de cada usuario (una fila): moneda principal, periodo financiero y ahorro planificado. Quién escribe: finance.setup_user() en el onboarding y la API desde Ajustes. Ejemplo: moneda principal BOB, periodo mensual desde el día 25 (su día de cobro), ahorra 500 Bs por periodo.';
COMMENT ON COLUMN finance.user_settings.user_id IS 'Usuario dueño; es también la clave primaria (una fila por usuario)';
COMMENT ON COLUMN finance.user_settings.main_currency IS 'Moneda principal: la que la app muestra primero. Se elige en el onboarding y se cambia en Ajustes; cambiarla no convierte ningún monto. Debe estar activa y entra sola a Mis monedas';
COMMENT ON COLUMN finance.user_settings.period_type IS 'Cómo agrupa su dinero: weekly (semanal), semi_monthly (quincenal: dos por mes) o monthly (mensual). Por defecto monthly. Lo usan Safe to Spend, Money Flow y Money Story';
COMMENT ON COLUMN finance.user_settings.period_start_day IS 'Día en que empieza el periodo. weekly: día de la semana (0 domingo … 6 sábado). semi_monthly: día d del mes (1 a 13); la segunda quincena empieza el d + 15. monthly: día del mes (1 a 28), por ejemplo su día de cobro. Por defecto 1';
COMMENT ON COLUMN finance.user_settings.planned_savings IS 'Cuánto quiere ahorrar en cada periodo, en la moneda principal. Safe to Spend de esa moneda lo resta. Por defecto 0';
COMMENT ON COLUMN finance.user_settings.updated_at IS 'Última modificación; la actualiza un trigger';

-- goals.goal_contributions
COMMENT ON TABLE goals.goal_contributions IS
  'Aportes y retiros de cada meta, en la moneda de la meta. Su ritmo alimenta el Goal Forecast. Quién escribe: la API. Ejemplo: +300 Bs el 01-10; −50 Bs el 10-10.';
COMMENT ON COLUMN goals.goal_contributions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN goals.goal_contributions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN goals.goal_contributions.goal_id IS 'Meta; la FK (user_id, goal_id) exige que sea del mismo usuario';
COMMENT ON COLUMN goals.goal_contributions.amount IS 'Monto del aporte; negativo = retiro. No puede ser 0';
COMMENT ON COLUMN goals.goal_contributions.contributed_on IS 'Fecha del aporte. Por defecto hoy';
COMMENT ON COLUMN goals.goal_contributions.source IS 'manual, transaction o adjustment. Por defecto manual';
COMMENT ON COLUMN goals.goal_contributions.transaction_id IS 'Transferencia que lo originó; evita contar dos veces el mismo dinero';
COMMENT ON COLUMN goals.goal_contributions.note IS 'Nota opcional (hasta 500 caracteres)';
COMMENT ON COLUMN goals.goal_contributions.created_at IS 'Cuándo se creó la fila';

-- goals.goals
COMMENT ON TABLE goals.goals IS
  'Metas de ahorro: fondo de emergencia, laptop, viaje. Cada meta tiene su moneda y no se vincula a una cuenta. Quién escribe: la API; current_amount lo mantiene un trigger con los aportes. Ejemplo: Fondo de emergencia, 5.000 Bs, lleva 450, aporta 300 por periodo.';
COMMENT ON COLUMN goals.goals.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN goals.goals.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN goals.goals.name IS 'Nombre de la meta (1 a 80 caracteres)';
COMMENT ON COLUMN goals.goals.target_amount IS 'Monto objetivo, mayor que 0';
COMMENT ON COLUMN goals.goals.currency IS 'Moneda de la meta y de sus aportes; debe estar activa al crearla';
COMMENT ON COLUMN goals.goals.current_amount IS 'Monto ahorrado; lo suma un trigger con cada aporte o retiro. Por defecto 0';
COMMENT ON COLUMN goals.goals.target_date IS 'Fecha objetivo (opcional)';
COMMENT ON COLUMN goals.goals.priority IS 'Prioridad de 1 (más alta) a 5. Por defecto 3; Can I Afford It? la usa para decidir qué meta se retrasa';
COMMENT ON COLUMN goals.goals.planned_contribution IS 'Cuánto piensa aportar en cada periodo (semana, quincena o mes), opcional. Safe to Spend lo resta';
COMMENT ON COLUMN goals.goals.status IS 'active, paused, achieved o archived. Por defecto active';
COMMENT ON COLUMN goals.goals.achieved_at IS 'Cuándo se alcanzó; existe solo si status es achieved';
COMMENT ON COLUMN goals.goals.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN goals.goals.color IS 'Color en hexadecimal (#RRGGBB)';
COMMENT ON COLUMN goals.goals.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN goals.goals.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN goals.goals.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- iam.auth_identities
COMMENT ON TABLE iam.auth_identities IS
  'Formas de entrar de cada usuario: correo y contraseña, Google, Meta o Apple. Un usuario puede tener varias; cada una identifica a un solo usuario. Quién escribe: la API al registrarse o vincular un método. Ejemplo: María entra con Google (sub 1093…) y con su contraseña.';
COMMENT ON COLUMN iam.auth_identities.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.auth_identities.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.auth_identities.provider IS 'password, google, meta o apple. Un usuario tiene como máximo una identidad por proveedor';
COMMENT ON COLUMN iam.auth_identities.provider_subject IS 'El correo para password; el id que entrega el proveedor en los demás. La pareja (provider, provider_subject) es única: una cuenta de Google no se liga a dos usuarios';
COMMENT ON COLUMN iam.auth_identities.password_hash IS 'Contraseña cifrada con argon2id; solo existe cuando provider es password';
COMMENT ON COLUMN iam.auth_identities.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.auth_identities.last_used_at IS 'Último inicio de sesión con este método';

-- iam.devices
COMMENT ON TABLE iam.devices IS
  'Teléfonos y navegadores del usuario: token de notificaciones push y si activó huella o rostro. Quién escribe: la API al iniciar sesión o renovar el token push. Ejemplo: iPhone de María, iOS 19, biometría activada.';
COMMENT ON COLUMN iam.devices.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.devices.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.devices.platform IS 'ios, android o web';
COMMENT ON COLUMN iam.devices.push_token IS 'Token de Firebase Cloud Messaging para enviar notificaciones';
COMMENT ON COLUMN iam.devices.app_version IS 'Versión de la app instalada';
COMMENT ON COLUMN iam.devices.os_version IS 'Versión del sistema operativo';
COMMENT ON COLUMN iam.devices.biometric_enabled IS 'Si activó huella o rostro; la validación la hace el sistema operativo, no la app. Por defecto no';
COMMENT ON COLUMN iam.devices.last_seen_at IS 'Última vez que el dispositivo usó la app';
COMMENT ON COLUMN iam.devices.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.devices.revoked_at IS 'Cuándo se cerró la sesión en este dispositivo';

-- iam.sessions
COMMENT ON TABLE iam.sessions IS
  'Sesiones abiertas: cada refresh token (guardado como hash) y su dispositivo. Permite cerrar sesión en un dispositivo, ver dispositivos activos y detectar un token robado que se reusa. Quién escribe: la API al iniciar sesión y en cada renovación (rotación). Ejemplo: sesión del iPhone, vence en 30 días.';
COMMENT ON COLUMN iam.sessions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.sessions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.sessions.device_id IS 'Dispositivo de la sesión; si se borra el dispositivo, queda vacío';
COMMENT ON COLUMN iam.sessions.refresh_token_hash IS 'Hash del refresh token (nunca el token); único';
COMMENT ON COLUMN iam.sessions.replaced_by IS 'Sesión nueva creada al renovar. Si alguien usa un token ya reemplazado, se detecta un posible robo';
COMMENT ON COLUMN iam.sessions.ip IS 'IP desde la que se abrió';
COMMENT ON COLUMN iam.sessions.user_agent IS 'Navegador o app que la abrió';
COMMENT ON COLUMN iam.sessions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.sessions.expires_at IS 'Vencimiento; debe ser posterior a created_at';
COMMENT ON COLUMN iam.sessions.revoked_at IS 'Cuándo se cerró la sesión';

-- iam.terms_versions
COMMENT ON TABLE iam.terms_versions IS
  'Versiones publicadas de los términos de uso y la política de privacidad; solo una es la vigente. Quién escribe: el equipo, al publicar una versión nueva. Ejemplo: 2026-10, vigente, con sus dos enlaces.';
COMMENT ON COLUMN iam.terms_versions.version IS 'Versión, por ejemplo 2026-10';
COMMENT ON COLUMN iam.terms_versions.terms_url IS 'Enlace a los términos';
COMMENT ON COLUMN iam.terms_versions.privacy_url IS 'Enlace a la política de privacidad';
COMMENT ON COLUMN iam.terms_versions.is_current IS 'Si es la vigente; solo una puede serlo';
COMMENT ON COLUMN iam.terms_versions.published_at IS 'Cuándo se publicó';

-- iam.user_preferences
COMMENT ON TABLE iam.user_preferences IS
  'Personalización de la app guardada en el servidor, para que sea igual en todos los dispositivos. Quién escribe: un trigger la crea al registrarse; después la API cuando el usuario cambia tema, color, modo privado o inicio de semana. Ejemplo: tema oscuro, acento verde, montos ocultos, semana desde el lunes.';
COMMENT ON COLUMN iam.user_preferences.user_id IS 'Usuario dueño; es también la clave primaria';
COMMENT ON COLUMN iam.user_preferences.theme IS 'system (del teléfono), light o dark. Por defecto system';
COMMENT ON COLUMN iam.user_preferences.accent_color IS 'Color de acento #RRGGBB; vacío = color de la marca';
COMMENT ON COLUMN iam.user_preferences.hide_amounts IS 'Modo privado: la app abre con los montos ocultos. Por defecto no';
COMMENT ON COLUMN iam.user_preferences.week_starts_on IS 'Día de inicio de semana: 0 domingo a 6 sábado. Por defecto 1 (lunes)';
COMMENT ON COLUMN iam.user_preferences.updated_at IS 'Última modificación; la actualiza un trigger';

-- iam.users
COMMENT ON TABLE iam.users IS
  'Una fila por persona registrada: es la cuenta que inicia sesión, paga y es dueña de todos sus datos financieros. Quién escribe: la API al registrarse y al editar el perfil; la base limpia nombres, teléfono y país y exige 18 años y los términos vigentes. Ejemplo: María José Rojas, maria@correo.com, nacida en 1995, estudiante en La Paz.';
COMMENT ON COLUMN iam.users.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.users.email IS 'Correo de la cuenta; único sin distinguir mayúsculas';
COMMENT ON COLUMN iam.users.email_verified_at IS 'Cuándo confirmó su correo; vacío si no lo confirmó';
COMMENT ON COLUMN iam.users.first_name IS 'Nombre (1 a 60 caracteres); se guarda sin espacios de más';
COMMENT ON COLUMN iam.users.last_name IS 'Apellido (1 a 60 caracteres); se guarda sin espacios de más';
COMMENT ON COLUMN iam.users.display_name IS 'Cómo quiere que lo llame la app (1 a 120 caracteres); vacío = su nombre';
COMMENT ON COLUMN iam.users.avatar_object_key IS 'Ruta de la foto de perfil en Cloud Storage';
COMMENT ON COLUMN iam.users.birth_date IS 'Fecha de nacimiento; la base de datos rechaza menores de 18 años';
COMMENT ON COLUMN iam.users.phone_e164 IS 'Teléfono en formato E.164 (+59171234567); se guarda sin espacios, guiones ni paréntesis';
COMMENT ON COLUMN iam.users.country_code IS 'País ISO 3166-1 en mayúsculas (BO)';
COMMENT ON COLUMN iam.users.city IS 'Ciudad (hasta 80 caracteres)';
COMMENT ON COLUMN iam.users.occupation IS 'student, employee, self_employed, entrepreneur, unemployed, retired u other';
COMMENT ON COLUMN iam.users.terms_version IS 'Versión de los términos que aceptó; al registrarse debe ser la vigente (terms_outdated)';
COMMENT ON COLUMN iam.users.terms_accepted_at IS 'Cuándo aceptó los términos';
COMMENT ON COLUMN iam.users.locale IS 'Idioma y región de la app. Por defecto es-BO';
COMMENT ON COLUMN iam.users.timezone IS 'Zona horaria para fechas y avisos. Por defecto America/La_Paz';
COMMENT ON COLUMN iam.users.status IS 'active, suspended, pending_deletion o deleted. Por defecto active';
COMMENT ON COLUMN iam.users.onboarding_completed_at IS 'Cuándo terminó el onboarding; con fecha, no se vuelve a mostrar';
COMMENT ON COLUMN iam.users.last_login_at IS 'Último inicio de sesión';
COMMENT ON COLUMN iam.users.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.users.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN iam.users.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- iam.verification_tokens
COMMENT ON TABLE iam.verification_tokens IS
  'Códigos de un solo uso para verificar el correo, recuperar la contraseña o cambiar el correo, guardados como hash. Quién escribe: la API al enviar el correo; se marca usado al confirmarlo. Ejemplo: recuperación de contraseña, vence en 1 hora.';
COMMENT ON COLUMN iam.verification_tokens.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.verification_tokens.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.verification_tokens.purpose IS 'email_verification, password_reset o email_change';
COMMENT ON COLUMN iam.verification_tokens.token_hash IS 'Hash del código; único';
COMMENT ON COLUMN iam.verification_tokens.expires_at IS 'Hasta cuándo vale el código';
COMMENT ON COLUMN iam.verification_tokens.used_at IS 'Cuándo se usó; un código usado no vale otra vez';
COMMENT ON COLUMN iam.verification_tokens.created_at IS 'Cuándo se creó la fila';

-- notify.notification_types
COMMENT ON TABLE notify.notification_types IS
  'Tipos de aviso que existen y si el usuario los puede apagar (los de seguridad y suscripción no). Quién escribe: el equipo. Ejemplo: recurring.due_soon, activado por defecto.';
COMMENT ON COLUMN notify.notification_types.key IS 'Clave del aviso, por ejemplo recurring.due_soon';
COMMENT ON COLUMN notify.notification_types.description IS 'Qué avisa';
COMMENT ON COLUMN notify.notification_types.default_enabled IS 'Si está activo para quien no cambió sus preferencias. Por defecto sí';
COMMENT ON COLUMN notify.notification_types.is_transactional IS 'true = obligatorio (seguridad, suscripción): no se puede desactivar. Por defecto no';

-- notify.notifications
COMMENT ON TABLE notify.notifications IS
  'Bandeja y registro de envíos de cada aviso. Particionada por mes. Quién escribe: los workers al encolar y al enviar; la API marca read_at. Ejemplo: ''Mañana vence tu alquiler de 1.500 Bs'', enviada el 30-10.';
COMMENT ON COLUMN notify.notifications.id IS 'Identificador; la clave primaria es (created_at, id) por estar particionada por mes';
COMMENT ON COLUMN notify.notifications.created_at IS 'Cuándo se creó; define la partición mensual';
COMMENT ON COLUMN notify.notifications.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN notify.notifications.type_key IS 'Tipo de aviso';
COMMENT ON COLUMN notify.notifications.channel IS 'push, email o in_app. Por defecto push';
COMMENT ON COLUMN notify.notifications.title IS 'Título (hasta 120 caracteres)';
COMMENT ON COLUMN notify.notifications.body IS 'Texto (hasta 500 caracteres)';
COMMENT ON COLUMN notify.notifications.data IS 'Enlace a la pantalla e ids relacionados, en JSON';
COMMENT ON COLUMN notify.notifications.dedupe_key IS 'Evita enviar el mismo aviso dos veces, por ejemplo recurring:<id>:2026-10';
COMMENT ON COLUMN notify.notifications.status IS 'queued, sent, failed, skipped o read. Por defecto queued';
COMMENT ON COLUMN notify.notifications.scheduled_for IS 'Cuándo debe enviarse';
COMMENT ON COLUMN notify.notifications.sent_at IS 'Cuándo se envió';
COMMENT ON COLUMN notify.notifications.read_at IS 'Cuándo lo leyó el usuario';
COMMENT ON COLUMN notify.notifications.error IS 'Error de envío, si lo hubo';

-- notify.preferences
COMMENT ON TABLE notify.preferences IS
  'Avisos que el usuario cambió en Ajustes; sin fila se usa el valor por defecto del tipo. Quién escribe: la API. Ejemplo: María apagó goal.milestone por push.';
COMMENT ON COLUMN notify.preferences.user_id IS 'Usuario; parte de la clave primaria';
COMMENT ON COLUMN notify.preferences.type_key IS 'Tipo de aviso; parte de la clave primaria';
COMMENT ON COLUMN notify.preferences.channel IS 'push, email o in_app; parte de la clave primaria. Por defecto push';
COMMENT ON COLUMN notify.preferences.is_enabled IS 'Si quiere recibirlo';
COMMENT ON COLUMN notify.preferences.updated_at IS 'Última vez que cambió la preferencia';

-- ops.incident_affected_users
COMMENT ON TABLE ops.incident_affected_users IS
  'Usuarios afectados por cada incidente, para avisarles o compensarlos. Quién escribe: ops.log() cuando el error tiene usuario. Ejemplo: INC-000012 afectó a María; avisada el 15-10.';
COMMENT ON COLUMN ops.incident_affected_users.incident_id IS 'Incidente; parte de la clave primaria';
COMMENT ON COLUMN ops.incident_affected_users.user_id IS 'Usuario afectado (sin FK); parte de la clave primaria';
COMMENT ON COLUMN ops.incident_affected_users.first_seen_at IS 'Cuándo lo afectó por primera vez';
COMMENT ON COLUMN ops.incident_affected_users.notified_at IS 'Cuándo se le avisó';

-- ops.incident_updates
COMMENT ON TABLE ops.incident_updates IS
  'Línea de tiempo de cada incidente: cambios de estado y severidad, y notas del equipo. Quién escribe: triggers de ops.incidents y el equipo. Ejemplo: 10:05 open → investigating, por dana@moneymap.team.';
COMMENT ON COLUMN ops.incident_updates.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN ops.incident_updates.incident_id IS 'Incidente';
COMMENT ON COLUMN ops.incident_updates.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ops.incident_updates.author IS 'Quién hizo el cambio (correo del equipo o system). Por defecto system';
COMMENT ON COLUMN ops.incident_updates.status_from IS 'Estado anterior';
COMMENT ON COLUMN ops.incident_updates.status_to IS 'Estado nuevo';
COMMENT ON COLUMN ops.incident_updates.severity_from IS 'Severidad anterior';
COMMENT ON COLUMN ops.incident_updates.severity_to IS 'Severidad nueva';
COMMENT ON COLUMN ops.incident_updates.note IS 'Nota del equipo';
COMMENT ON COLUMN ops.incident_updates.is_public IS 'Si se puede comunicar a los usuarios. Por defecto no';

-- ops.incidents
COMMENT ON TABLE ops.incidents IS
  'Agrupa errores repetidos con la misma huella y sigue su ciclo: abierto → investigando → identificado → monitoreo → resuelto → cerrado, con responsable y causa raíz. Quién escribe: ops.log() abre o suma; el equipo cambia el estado. Ejemplo: INC-000012, sev3, push.fcm.timeout, 37 ocurrencias.';
COMMENT ON COLUMN ops.incidents.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN ops.incidents.number IS 'Número correlativo; único';
COMMENT ON COLUMN ops.incidents.code IS 'INC- más el número con 6 dígitos (INC-000123)';
COMMENT ON COLUMN ops.incidents.title IS 'Título (1 a 200 caracteres)';
COMMENT ON COLUMN ops.incidents.description IS 'Descripción';
COMMENT ON COLUMN ops.incidents.severity IS 'sev1 (caída total o datos incorrectos) a sev4 (menor)';
COMMENT ON COLUMN ops.incidents.status IS 'open, investigating, identified, monitoring, resolved o closed. Por defecto open';
COMMENT ON COLUMN ops.incidents.category IS 'Categoría del log que lo abrió';
COMMENT ON COLUMN ops.incidents.fingerprint IS 'Huella de los errores agrupados; solo un incidente abierto por huella';
COMMENT ON COLUMN ops.incidents.detected_by IS 'automatic, monitoring, user_report o manual. Por defecto automatic';
COMMENT ON COLUMN ops.incidents.previous_incident_id IS 'Incidente resuelto del que este es una regresión';
COMMENT ON COLUMN ops.incidents.first_seen_at IS 'Primera ocurrencia';
COMMENT ON COLUMN ops.incidents.last_seen_at IS 'Última ocurrencia';
COMMENT ON COLUMN ops.incidents.occurrences IS 'Veces que ocurrió. Por defecto 1';
COMMENT ON COLUMN ops.incidents.affected_users IS 'Usuarios distintos afectados. Por defecto 0';
COMMENT ON COLUMN ops.incidents.assigned_to IS 'Persona del equipo a cargo';
COMMENT ON COLUMN ops.incidents.acknowledged_at IS 'Cuándo el equipo lo tomó';
COMMENT ON COLUMN ops.incidents.resolved_at IS 'Cuándo se resolvió; existe solo en resolved o closed';
COMMENT ON COLUMN ops.incidents.closed_at IS 'Cuándo se cerró';
COMMENT ON COLUMN ops.incidents.impact IS 'Impacto en los usuarios';
COMMENT ON COLUMN ops.incidents.root_cause IS 'Causa raíz';
COMMENT ON COLUMN ops.incidents.resolution IS 'Cómo se resolvió';
COMMENT ON COLUMN ops.incidents.postmortem_url IS 'Enlace al análisis posterior';
COMMENT ON COLUMN ops.incidents.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ops.incidents.updated_at IS 'Última modificación; la actualiza un trigger';

-- ops.logs
COMMENT ON TABLE ops.logs IS
  'Eventos importantes del sistema, de solo inserción: errores, fallos de integraciones (tiendas, IA, push), eventos de seguridad y jobs. Nadie puede editar ni borrar un log. Particionada por mes. Quién escribe: la API y los workers con ops.log(). Ejemplo: warning ai.call.timeout de GPT-6 Luna.';
COMMENT ON COLUMN ops.logs.id IS 'Identificador; la clave primaria es (occurred_at, id)';
COMMENT ON COLUMN ops.logs.occurred_at IS 'Cuándo ocurrió; define la partición mensual';
COMMENT ON COLUMN ops.logs.level IS 'debug, info, notice, warning, error o critical';
COMMENT ON COLUMN ops.logs.severity IS 'Se calcula desde level (10 a 60) para ordenar y filtrar';
COMMENT ON COLUMN ops.logs.category IS 'api, auth, security, billing, finance, ai, notify, integration, job, database, client o system';
COMMENT ON COLUMN ops.logs.event_code IS 'Código estable del evento, por ejemplo billing.webhook.invalid_signature';
COMMENT ON COLUMN ops.logs.message IS 'Descripción legible';
COMMENT ON COLUMN ops.logs.service IS 'Quién lo escribió: api, worker, scheduler, ios, android, web o database';
COMMENT ON COLUMN ops.logs.environment IS 'prod, staging o dev';
COMMENT ON COLUMN ops.logs.release IS 'Versión de la app o commit desplegado';
COMMENT ON COLUMN ops.logs.user_id IS 'Usuario afectado (sin FK)';
COMMENT ON COLUMN ops.logs.device_id IS 'Dispositivo afectado';
COMMENT ON COLUMN ops.logs.request_id IS 'Id de la petición';
COMMENT ON COLUMN ops.logs.trace_id IS 'Id de traza, para seguir una petición entre servicios';
COMMENT ON COLUMN ops.logs.http_method IS 'Método HTTP';
COMMENT ON COLUMN ops.logs.http_path IS 'Ruta de la API';
COMMENT ON COLUMN ops.logs.http_status IS 'Código HTTP';
COMMENT ON COLUMN ops.logs.duration_ms IS 'Duración';
COMMENT ON COLUMN ops.logs.error_type IS 'Tipo de excepción, por ejemplo TimeoutError';
COMMENT ON COLUMN ops.logs.error_message IS 'Mensaje del error';
COMMENT ON COLUMN ops.logs.stack_trace IS 'Traza del error';
COMMENT ON COLUMN ops.logs.fingerprint IS 'Huella que agrupa errores iguales en un incidente';
COMMENT ON COLUMN ops.logs.incident_id IS 'Incidente al que se sumó (errores y critical); sin FK';
COMMENT ON COLUMN ops.logs.context IS 'Datos extra en JSON; nunca contraseñas, tokens ni números de tarjeta';
COMMENT ON COLUMN ops.logs.ip IS 'IP de origen';

-- planning.affordability_checks
COMMENT ON TABLE planning.affordability_checks IS
  'Historial de Can I Afford It?: qué consultó el usuario, el veredicto, el impacto en sus metas y lo que decidió. Cuenta para la North Star. Quién escribe: la API. Ejemplo: Laptop 4.000 Bs → affordable_with_impact, retrasa el Fondo 2 meses; decidió esperar.';
COMMENT ON COLUMN planning.affordability_checks.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN planning.affordability_checks.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN planning.affordability_checks.description IS 'Qué quería comprar (opcional, hasta 120 caracteres)';
COMMENT ON COLUMN planning.affordability_checks.amount IS 'Monto de la compra, mayor que 0';
COMMENT ON COLUMN planning.affordability_checks.currency IS 'Moneda del monto';
COMMENT ON COLUMN planning.affordability_checks.verdict IS 'affordable (alcanza), affordable_with_impact (alcanza retrasando metas) o not_now (todavía no)';
COMMENT ON COLUMN planning.affordability_checks.safe_to_spend_before IS 'Safe to Spend antes de la compra';
COMMENT ON COLUMN planning.affordability_checks.safe_to_spend_after IS 'Safe to Spend si hace la compra';
COMMENT ON COLUMN planning.affordability_checks.earliest_affordable_on IS 'Desde cuándo podría comprarlo, cuando el veredicto es not_now';
COMMENT ON COLUMN planning.affordability_checks.impacts IS 'Metas afectadas y cuántos meses se retrasa cada una, en JSON';
COMMENT ON COLUMN planning.affordability_checks.assumptions IS 'Supuestos que se mostraron al usuario, en JSON';
COMMENT ON COLUMN planning.affordability_checks.algorithm_version IS 'Versión del cálculo, para explicar resultados pasados';
COMMENT ON COLUMN planning.affordability_checks.decision IS 'Lo que hizo el usuario: bought, postponed o dismissed (opcional)';
COMMENT ON COLUMN planning.affordability_checks.created_at IS 'Cuándo se creó la fila';

-- reports.money_stories
COMMENT ON TABLE reports.money_stories IS
  'Resumen semanal (Weekly Check-in) o mensual (Monthly Money Story) por moneda: cuánto ganó, gastó y ahorró, y frases destacadas guardadas como claves. Quién escribe: el worker al cerrar la semana o el mes; la API marca viewed_at. Ejemplo: octubre en BOB: ingresó 5.000, gastó 3.800, ahorró 24 %.';
COMMENT ON COLUMN reports.money_stories.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN reports.money_stories.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN reports.money_stories.period_type IS 'week (Weekly Check-in) o month (Monthly Money Story)';
COMMENT ON COLUMN reports.money_stories.period_start IS 'Primer día del periodo resumido';
COMMENT ON COLUMN reports.money_stories.period_end IS 'Último día del periodo resumido';
COMMENT ON COLUMN reports.money_stories.status IS 'pending, ready o failed. Por defecto pending';
COMMENT ON COLUMN reports.money_stories.currency IS 'Moneda de los totales: hay una historia por moneda con movimientos';
COMMENT ON COLUMN reports.money_stories.income_total IS 'Ingresos del periodo';
COMMENT ON COLUMN reports.money_stories.expense_total IS 'Gastos del periodo';
COMMENT ON COLUMN reports.money_stories.savings_total IS 'Ahorro del periodo (ingresos − gastos)';
COMMENT ON COLUMN reports.money_stories.savings_rate IS 'Tasa de ahorro (ahorro ÷ ingresos)';
COMMENT ON COLUMN reports.money_stories.highlights IS 'Frases destacadas como claves y parámetros en JSON, no texto final: se pueden traducir o redactar distinto sin recalcular';
COMMENT ON COLUMN reports.money_stories.template_version IS 'Versión de las plantillas de texto';
COMMENT ON COLUMN reports.money_stories.generated_at IS 'Cuándo se generó';
COMMENT ON COLUMN reports.money_stories.viewed_at IS 'Cuándo la abrió el usuario';
COMMENT ON COLUMN reports.money_stories.created_at IS 'Cuándo se creó la fila';

-- -----------------------------------------------------------------------------
-- Lo que la base hace sola (funciones de los triggers)
-- -----------------------------------------------------------------------------
COMMENT ON FUNCTION core.set_updated_at() IS 'updated_at se actualiza solo en cada cambio.';
COMMENT ON FUNCTION core.audit_row_change() IS 'Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).';
COMMENT ON FUNCTION iam.users_before_write() IS 'Limpia nombre, apellido, teléfono, país y ciudad; display_name vacío toma el nombre; al registrarse exige los términos vigentes (terms_outdated).';
COMMENT ON FUNCTION iam.users_create_preferences() IS 'Crea las preferencias por defecto de cada usuario nuevo.';
COMMENT ON FUNCTION billing.subscriptions_before_write() IS 'Mantiene canceled_at, cancel_reason y ended_at según el estado y la renovación automática.';
COMMENT ON FUNCTION billing.log_subscription_change() IS 'Escribe cada cambio de la suscripción en billing.subscription_changes.';
COMMENT ON FUNCTION finance.user_currencies_guard() IS 'Solo monedas activas; no deja quitar la moneda principal ni la de una cuenta activa (currency_in_use).';
COMMENT ON FUNCTION finance.user_settings_before_write() IS 'La moneda principal debe estar activa.';
COMMENT ON FUNCTION finance.user_settings_after_write() IS 'La moneda principal entra sola a Mis monedas.';
COMMENT ON FUNCTION finance.sync_opening_balance() IS 'El saldo actual arranca en el saldo inicial y se corrige si este cambia.';
COMMENT ON FUNCTION finance.accounts_before_write() IS 'Valida tipo y moneda, bloquea la moneda de una cuenta usada, aplica los límites de tarjetas y monedas del plan (MM001) y deja por defecto la primera cuenta.';
COMMENT ON FUNCTION finance.accounts_after_write() IS 'Agrega la moneda a Mis monedas y mantiene una sola cuenta por defecto (marcar otra desmarca la anterior; si se archiva, pasa a la siguiente).';
COMMENT ON FUNCTION finance.recurring_rules_before_write() IS 'Toma la moneda de la cuenta (currency_mismatch si se envía otra) y usa start_date como primer vencimiento.';
COMMENT ON FUNCTION finance.transactions_before_write() IS 'Toma la moneda de la cuenta, valida los decimales y que una transferencia vaya a otra cuenta activa de la misma moneda.';
COMMENT ON FUNCTION finance.apply_transaction_to_balances() IS 'Ajusta el saldo de las cuentas con cada alta, edición o borrado de un movimiento.';
COMMENT ON FUNCTION goals.goals_before_write() IS 'La moneda de la meta debe estar activa.';
COMMENT ON FUNCTION goals.apply_contribution() IS 'Suma o resta cada aporte al monto ahorrado de la meta.';
COMMENT ON FUNCTION ai.routes_check_kind() IS 'El modelo debe ser del tipo que pide la tarea (no se pone un LLM a transcribir).';
COMMENT ON FUNCTION ai.calls_before_insert() IS 'Calcula el costo de la llamada con el precio del modelo; una llamada que no llegó al proveedor cuesta 0.';
COMMENT ON FUNCTION ai.calls_after_insert() IS 'Suma la llamada al dictado (intentos, tokens, costo, modelo que respondió) y al uso mensual del usuario.';
COMMENT ON FUNCTION ops.logs_append_only() IS 'Impide editar o borrar un log.';
COMMENT ON FUNCTION ops.incidents_on_change() IS 'Al cambiar estado o severidad, completa las fechas y escribe la línea de tiempo.';
COMMENT ON FUNCTION ops.incidents_after_insert() IS 'Escribe la primera entrada de la línea de tiempo.';

-- Listas fijas
COMMENT ON TYPE finance.period_type IS 'weekly (semanal), semi_monthly (quincenal: dos por mes, desde el día d y el d + 15) o monthly (mensual).';
COMMENT ON TYPE finance.frequency IS 'Cada cuánto se repite un recurrente: weekly (semana), biweekly (2 semanas), monthly (mes) o yearly (año).';
COMMENT ON TYPE finance.transaction_source IS 'Cómo se registró un movimiento: manual, quick_add, voice, scan, recurring, onboarding o adjustment.';

-- Vistas
COMMENT ON VIEW billing.price_catalog IS 'Pantalla de planes: precio mensual, anual, precio por mes pagando el año y porcentaje de ahorro.';
COMMENT ON VIEW ai.provider_health_24h IS 'Salud de cada proveedor de IA en las últimas 24 horas: llamadas, fallas, tasa de error, veces que salvó como respaldo, latencia p50/p95 y costo.';
COMMENT ON VIEW ai.monthly_cost_by_model IS 'Costo real de IA por modelo, tarea y mes, incluidas las llamadas fallidas.';
COMMENT ON VIEW ai.monthly_cost_by_user IS 'Dictados por usuario y mes: cuántos, confirmados, con respaldo, confianza promedio y costo.';
COMMENT ON VIEW ops.open_incidents IS 'Tablero del equipo: incidentes abiertos por severidad y última vez que ocurrieron.';
COMMENT ON VIEW ops.error_summary_24h IS 'Errores y advertencias de las últimas 24 horas agrupados por código, con usuarios afectados.';

-- Funciones que usa la API o los workers
COMMENT ON FUNCTION catalog.assert_currency_active(char) IS 'Falla con currency_unavailable si la moneda no existe o está desactivada.';
COMMENT ON FUNCTION billing.resource_usage(uuid, text) IS 'Cuántos recursos vivos tiene el usuario de una funcionalidad: tarjetas, monedas o metas activas.';
COMMENT ON FUNCTION billing.limit_status(uuid, text) IS 'Para mostrar "1 de 1 tarjetas": límite, usado, restante y si puede agregar otra.';
COMMENT ON FUNCTION finance.recalculate_account_balance(uuid, uuid) IS 'Recalcula el saldo de una cuenta desde cero (conciliación nocturna o soporte) y lo devuelve.';
COMMENT ON FUNCTION ai.route(text) IS 'Orden vigente de proveedores de una tarea (activos y no retirados). El worker lo lee y puede cachearlo 60 s.';
