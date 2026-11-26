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
