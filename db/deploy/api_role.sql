-- El servicio api-role de docker-compose.yml (dev, QA y producción): el usuario
-- con login de la API. Hereda de moneymap_app, así que la RLS se aplica (el dueño de las tablas
-- se la saltaría). Corre en cada despliegue: lo crea si falta y le pone la clave
-- de API_DB_PASSWORD, así cambiarla es cambiar la variable y redesplegar.
-- Uso: psql ... -v api_password="$API_DB_PASSWORD" -f db/deploy/api_role.sql
SELECT 'CREATE ROLE moneymap_api LOGIN IN ROLE moneymap_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneymap_api') \gexec

SELECT format('ALTER ROLE moneymap_api PASSWORD %L', :'api_password') \gexec
