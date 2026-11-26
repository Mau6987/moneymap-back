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
