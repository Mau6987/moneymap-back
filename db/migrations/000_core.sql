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
