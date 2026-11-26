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
