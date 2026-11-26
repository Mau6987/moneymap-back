-- El servicio api-role de docker-compose.yml también crea el usuario con login
-- del worker de voz (spec 012). Hereda de moneymap_worker: lee el orden de los
-- modelos (ai.route) y registra cada llamada en ai.calls, que la API no puede.
-- Corre en cada despliegue, como api_role.sql, con la clave de WORKER_DB_PASSWORD.
-- Uso: psql ... -v worker_password="$WORKER_DB_PASSWORD" -f db/deploy/worker_role.sql
SELECT 'CREATE ROLE moneymap_worker_login LOGIN IN ROLE moneymap_worker'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_worker_login') \gexec

SELECT format('ALTER ROLE moneymap_worker_login PASSWORD %L', :'worker_password') \gexec
