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
