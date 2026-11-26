-- Solo desarrollo: usuarios con login para la API y el worker de voz. Hereda de moneymap_app, así
-- que la RLS se aplica (el dueño de las tablas se la saltaría).
-- Con `docker compose up -d --build` lo crea db/deploy/api_role.sql. Este
-- queda para la base sola (uv run uvicorn) y para la CI.
-- Uso (después de alembic upgrade head):
--   docker compose exec db psql -U moneymap -d moneymap -f /db/dev/api_role.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_api') THEN
    CREATE ROLE moneymap_api LOGIN PASSWORD 'moneymap' IN ROLE moneymap_app;
  END IF;
  -- El worker de voz (spec 012): hereda de moneymap_worker, sin RLS por usuario.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_worker_login') THEN
    CREATE ROLE moneymap_worker_login LOGIN PASSWORD 'moneymap' IN ROLE moneymap_worker;
  END IF;
END $$;
