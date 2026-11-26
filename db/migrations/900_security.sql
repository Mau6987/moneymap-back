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
