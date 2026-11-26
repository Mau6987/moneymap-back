# MoneyMap · Backend

La API de MoneyMap: registrar ingresos y gastos, ver cuánto podés gastar (Safe to Spend), metas, presupuestos, reportes y registro por voz. La usan la app (iOS y Android) y la web.

**Tecnologías:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis · Celery · Docker Compose. En producción corre en nuestro servidor con Dokploy.

---

## Índice

1. [Qué necesitás instalar](#1-qué-necesitás-instalar)
2. [Levantarlo con Docker Compose (lo más fácil)](#2-levantarlo-con-docker-compose-lo-más-fácil)
3. [Levantarlo a mano (para programar)](#3-levantarlo-a-mano-para-programar)
4. [Probar que funciona](#4-probar-que-funciona)
5. [Registro por voz en local (opcional)](#5-registro-por-voz-en-local-opcional)
6. [Problemas comunes](#6-problemas-comunes)
7. [Comandos del día a día](#7-comandos-del-día-a-día)
8. [Conectarse a la base](#8-conectarse-a-la-base)
9. [Desplegar en el servidor (Dokploy)](#9-desplegar-en-el-servidor-dokploy)
10. [Cómo está organizado](#10-cómo-está-organizado)
11. [Documentación](#11-documentación)

---

## 1. Qué necesitás instalar

| Herramienta | Para qué | Cómo |
|---|---|---|
| **Git** | Bajar el código | [git-scm.com](https://git-scm.com) |
| **Docker Desktop** | La base, Redis y, si querés, todo el backend | [docker.com](https://www.docker.com/products/docker-desktop/) — tiene que estar **abierto** |
| **uv** | Python y las dependencias (solo para la opción manual) | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) — instala Python 3.12 solo, no hace falta bajarlo aparte |

Bajá el repositorio y entrá a la carpeta:

```bash
git clone https://github.com/MoneyMapNexus/moneymap-back.git
cd moneymap-back
cp .env.example .env          # la configuración de desarrollo; ya sirve tal cual
```

> El `.env` de ejemplo trae todo lo necesario para desarrollo (incluido `JWT_SECRET`). No pongas claves reales en él y nunca lo subas al repositorio: ya está en `.gitignore`.

Elegí **una** de las dos formas de levantarlo:

- **Opción A, Docker Compose:** para probar la API, hacer QA o conectar la app y la web. No necesitás uv.
- **Opción B, a mano:** para programar en el backend. La API se recarga sola al guardar un archivo.

---

## 2. Levantarlo con Docker Compose (lo más fácil)

Un solo comando construye la imagen, crea la base, aplica las migraciones, crea los usuarios de la base y levanta la API y el worker.

```bash
docker compose up -d --build
```

La primera vez tarda unos minutos (baja las imágenes y construye la de la API). Después, en **http://localhost:8000/docs** está la documentación interactiva de la API.

Para ver que todo arrancó:

```bash
docker compose ps -a               # db, redis, api y worker en "Up"; migrate y api-role en "Exited (0)"
docker compose logs -f api worker  # los logs; Ctrl+C para salir
```

| Para… | Comando |
|---|---|
| Parar todo (los datos quedan) | `docker compose stop` |
| Volver a arrancar | `docker compose up -d` |
| Actualizar después de un `git pull` | `docker compose up -d --build` (aplica las migraciones nuevas solo) |
| Borrar los contenedores (los datos quedan) | `docker compose down` |
| **Empezar con la base vacía** | `docker compose down -v` y después `docker compose up -d --build` |

Si el puerto 8000 está ocupado: `API_PORT=8010 docker compose up -d`. La API queda en `http://localhost:8010`.

---

## 3. Levantarlo a mano (para programar)

La base y Redis van en Docker; la API y el worker corren en tu máquina con uv.

**Paso 1. Instalar las dependencias** (la primera vez y cuando cambie `pyproject.toml`):

```bash
uv sync
```

**Paso 2. Levantar la base y Redis:**

```bash
docker compose up -d db redis
```

La base queda en `localhost:5436` y Redis en `localhost:6379`.

**Paso 3. Crear las tablas** (la primera vez y después de cada `git pull` que traiga migraciones):

```bash
uv run alembic upgrade head
```

**Paso 4. Crear los usuarios de la base para la API y el worker** (solo la primera vez, o después de borrar la base):

```bash
docker compose exec db psql -U moneymap -d moneymap -f /db/dev/api_role.sql
```

> En **Git Bash** de Windows poné `MSYS_NO_PATHCONV=1` delante. Ver [Problemas comunes](#6-problemas-comunes).

**Paso 5. Arrancar la API:**

```bash
uv run uvicorn app.main:app --reload
```

La API queda en **http://localhost:8000/docs**. Con `--reload`, se reinicia sola cada vez que guardás un archivo.

**Paso 6 (opcional). Arrancar el worker**, en otra terminal. Hace falta para el registro por voz, los gastos fijos, los avisos y los reportes:

```bash
uv run celery -A app.workers worker --beat --loglevel=info
```

> Si la opción A está corriendo, pará antes su API y su worker (`docker compose stop api worker`), o usá otro puerto: `uv run uvicorn app.main:app --reload --port 8010`.

**Paso 7 (una sola vez por clon). Activar los hooks de git**, que revisan el formato del commit y corren las pruebas antes de cada push:

```bash
git config core.hooksPath .githooks
```

---

## 4. Probar que funciona

1. **La API está viva:** abrí http://localhost:8000/health. Tiene que responder `{"status": "ok", "database": true}`.
2. **Crear un usuario:** en http://localhost:8000/docs, pedí la verificación con `POST /v1/auth/email-verifications` y después registrate con `POST /v1/auth/register`. En desarrollo no se manda ningún correo (`EMAIL_BACKEND=log`): **el link de verificación sale en el log de la API**.
   - Opción A: `docker compose logs -f api`.
   - Opción B: en la terminal donde corre `uvicorn`.
3. **Usar el token:** el registro y el login devuelven un `access_token`. En `/docs`, tocá **Authorize** y pegalo para probar los demás endpoints.
4. **Hacerte administrador** (para el panel de planes). Necesita uv:
   ```bash
   uv run python -m app.scripts.make_admin tu-correo@ejemplo.com
   ```
   - Te pide una contraseña dos veces. Si el correo no tiene cuenta, la crea; si la tiene, le cambia la contraseña.
   - Queda como **el único** administrador: el que había deja de serlo.
5. **Conectar la app o la web a tu API local:**
   - **Web, o la app en un dispositivo iOS:** `http://localhost:8000`.
   - **Emulador de Android:** `http://10.0.2.2:8000`.
   - **Celular físico:** la IP de tu computadora en la red Wi-Fi.

Para correr todas las pruebas automáticas (necesita la opción B, con la base levantada):

```bash
uv run pytest
```

---

## 5. Registro por voz en local (opcional)

El registro por voz usa nuestra propia IA, que va en un compose aparte: [`docker-compose.ai.yml`](docker-compose.ai.yml). Si no vas a probar la voz, salteate esta sección.

1. **Voz a texto** en Docker. La primera vez tarda, porque baja los modelos. En la laptop alcanza con el principal: `STT_MODELS=parakeet` delante del comando.
   ```bash
   docker compose -f docker-compose.ai.yml up -d stt
   ```
2. **El LLM** con [Ollama de escritorio](https://ollama.com/download):
   ```bash
   ollama pull qwen3.5:4b
   ollama pull gemma3:4b
   ```
3. **El worker** tiene que estar corriendo: en Docker (opción A) o con el paso 6 de la opción B. Las direcciones ya vienen en el `.env` de ejemplo, así que no hay que configurar nada.
4. **El plan gratuito no incluye la voz.** Para probarla con un usuario gratuito, prendela solo en tu base local:
   ```bash
   docker compose exec db psql -U moneymap -d moneymap -c "UPDATE billing.plan_features SET is_enabled = true, limit_value = 30 WHERE feature_key = 'ai.voice_entries' AND plan_id = (SELECT id FROM billing.plans WHERE code = 'free')"
   ```

---

## 6. Problemas comunes

| Qué pasa | Por qué | Qué hacer |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop está cerrado | Abrilo y esperá a que diga *running* |
| `port is already allocated` en 5436, 6379 u 8000 | Otro programa usa ese puerto | Otro puerto: `DB_PORT=5544`, `REDIS_PORT=6380` o `API_PORT=8010` delante del comando. Si cambiás `DB_PORT`, cambiá también el puerto en `DATABASE_URL`, `MIGRATIONS_DATABASE_URL` y `WORKER_DATABASE_URL` del `.env` |
| `psql: could not open file "C:/Program Files/Git/db/..."` | Git Bash convierte la ruta `/db/...` en una ruta de Windows | Poné `MSYS_NO_PATHCONV=1` delante del comando, o usá PowerShell |
| La API no arranca y pide `JWT_SECRET` | Falta el `.env` | `cp .env.example .env` |
| `password authentication failed for user "moneymap_api"` | Falta el paso 4 de la opción B | Corré `/db/dev/api_role.sql` |
| La API se queda colgada al conectarse, en Windows | `localhost` prueba primero IPv6 | El `.env` usa `127.0.0.1` a propósito: no lo cambies a `localhost` |
| Las pruebas fallan por tablas o columnas que no existen | A tu base le faltan migraciones | `uv run alembic upgrade head` |
| Querés empezar de cero | — | `docker compose down -v` y volvé a levantar. **Borra todos los datos locales.** |

---

## 7. Comandos del día a día

| Qué | Comando |
|---|---|
| Revisar todo antes de subir (lo mismo que la CI) | `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest` |
| Pruebas | `uv run pytest` |
| Pruebas de la base | `docker compose exec db psql -U moneymap -d moneymap -v ON_ERROR_STOP=1 -f /db/tests/smoke_test.sql` |
| Arreglar el formato | `uv run ruff format .` |
| Migración nueva | un archivo nuevo en `alembic/versions/` (nunca se tocan los de `db/migrations/`) |
| Contrato para la app y la web | `uv run python -m app.scripts.export_openapi > openapi.json` |
| Nombrar al administrador del panel (reemplaza al anterior) | `uv run python -m app.scripts.make_admin correo@dominio.com` |
| Restaurar una meta borrada con saldo | `uv run python -m app.scripts.restore_deleted_goal correo@dominio.com "Nombre"` (agregá `--apply` para hacerlo) |
| Borrar una rama ya mergeada | `git push --no-verify origin --delete <rama>` (`--no-verify` para no correr las pruebas por un borrado) |

El diagrama y el diccionario de la base están en [`db/README.md`](db/README.md#ver-el-diagrama-y-regenerar-la-documentación).

---

## 8. Conectarse a la base

Para DBeaver, pgAdmin o `psql`, con los datos de desarrollo:

| | |
|---|---|
| Host y puerto | `localhost:5436` |
| Base | `moneymap` |
| Usuario para mirar y migrar | `moneymap` / `moneymap`. Es el dueño de las tablas: **ve todo, se salta la seguridad por usuario (RLS)** |
| Usuario de la API | `moneymap_api` / `moneymap`. Sujeto a la RLS: sin `app.user_id` no ve filas |
| Redis | `localhost:6379`, sin clave |

```bash
docker compose exec db psql -U moneymap -d moneymap    # consola de la base
```

> La API **nunca** usa el usuario `moneymap`: se saltaría la RLS y un usuario podría ver los datos de otro.

---

## 9. Desplegar en el servidor (Dokploy)

Producción (rama `main`) y staging (rama `develop`) usan **el mismo `docker-compose.yml`**. Lo único que cambia es el `.env`, que escribe Dokploy.

### La API

1. En Dokploy, creá una aplicación **Docker Compose** con el proveedor **GitHub**, este repositorio y la rama. El *Compose Path* es `./docker-compose.yml`.
2. **Environment:** copiá las variables de [`.env.prod.example`](.env.prod.example) con valores reales. Generá cada clave aparte, distinta en cada ambiente:
   ```bash
   uv run python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Si falta `POSTGRES_PASSWORD`, `API_DB_PASSWORD`, `WORKER_DB_PASSWORD` o `REDIS_PASSWORD`, el despliegue se corta antes de migrar.
3. **Domains:** servicio `api`, puerto `8080`, con HTTPS. Ese mismo dominio va en `PUBLIC_BASE_URL`.
4. **Advanced → Isolated Deployments** activado. Después, **Deploy**.

En cada despliegue pasa esto:
- se aplican las migraciones nuevas (`migrate`);
- se actualizan las claves de los usuarios de la base (`api-role`);
- se levantan la API y el worker.

Los datos quedan en los volúmenes `pgdata` y `redisdata`, así que redesplegar no los borra. La base y Redis no se ven desde afuera: sus puertos se publican solo en `127.0.0.1`.

### La IA del registro por voz

Va en otra aplicación Docker Compose: proveedor **GitHub** y *Compose Path* `docker-compose.ai.yml`. No sirve **Raw**, porque `stt` se construye desde `services/stt`.

- **En el mismo servidor que la API:** no hay que configurar nada. El worker la encuentra por la red `moneymap-ai`.
- **En otro servidor:**
  - En el de la IA, `AI_BIND` va con su IP privada (VPC o Tailscale). **Nunca `0.0.0.0`:** los modelos no tienen clave.
  - En la API, `AI_STT_URL` y `AI_LLM_URL` van con esa IP. El detalle está en [`.env.prod.example`](.env.prod.example).

Los secretos van **solo** en las variables de Dokploy, nunca en el repositorio.

---

## 10. Cómo está organizado

```
app/
  main.py              arranque, routers, manejo de errores, /health
  core/                configuración, base de datos (RLS), dinero, seguridad, errores
  modules/<módulo>/    iam, billing, finance, goals, planning, reports, notify, ai, ops
    router.py          endpoints /v1/...: solo HTTP, sin SQL ni reglas
    schemas.py         lo que entra y lo que sale (Pydantic)
    application/       casos de uso: commands/ (escribir) y queries/ (leer)
    domain/            modelos, puertos y errores del módulo
    infrastructure/    el SQL
  workers/             tareas de Celery: voz, recurrentes, reportes, avisos
  scripts/             export_openapi, make_admin, restore_deleted_goal
alembic/versions/      migraciones (la 0001 aplica el esquema base de db/migrations)
db/                    esquema SQL, pruebas de la base, diccionario y diagrama
services/stt/          el servicio de voz a texto (docker-compose.ai.yml)
docs/                  constitución, ingeniería, ADR, specs, PRD y el contrato de la API
tests/unit, tests/integration
```

Las reglas del dinero (saldos, monedas, límites de los planes) las aplica PostgreSQL. La API solo traduce sus errores a una respuesta. Por qué está armado así: [`docs/adr/001-monolito-modular-cqrs.md`](docs/adr/001-monolito-modular-cqrs.md).

---

## 11. Documentación

| Qué | Dónde |
|---|---|
| Reglas para programar acá (leelo antes de tocar código) | [`AGENTS.md`](AGENTS.md) |
| **Todos los endpoints**: lo que leen la app y la web | [`docs/api.md`](docs/api.md) |
| El producto | [`docs/PRD-MoneyMap-V1.5.md`](docs/PRD-MoneyMap-V1.5.md) |
| Requisitos de cada funcionalidad (specs 001 a 013) | [`docs/specs/`](docs/specs) |
| Principios y forma de trabajar | [`docs/constitution.md`](docs/constitution.md), [`docs/engineering.md`](docs/engineering.md), [`docs/adr/`](docs/adr) |
| La base de datos | [`db/README.md`](db/README.md), [`db/DICCIONARIO_CAMPOS.md`](db/DICCIONARIO_CAMPOS.md) |
| Correo, Google y Apple | [`docs/credenciales.md`](docs/credenciales.md) |
