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
