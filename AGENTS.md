# AGENTS.md — MoneyMap Backend

## Proyecto
API de MoneyMap, un SaaS para registrar y entender ingresos y gastos personales desde iOS y Android (la versión web es un proyecto aparte). Python 3.12 con FastAPI asíncrono y Pydantic v2; PostgreSQL 16 con SQLAlchemy 2 (async) y Alembic; Redis con Celery y Celery Beat para los trabajos en segundo plano; una capa propia de IA para el registro por voz (voz a texto + LLM, con proveedor principal y respaldos). Corre en nuestro propio servidor con Dokploy: el mismo `docker-compose.yml` de desarrollo levanta PostgreSQL, Redis, la API y el worker, y el Traefik de Dokploy pone el dominio y el HTTPS. Lo que cambia entre ambientes está en el `.env`. Los secretos van en las variables de entorno de Dokploy, nunca en el repositorio.

Está organizada por módulos de dominio, los mismos de la base de datos:

```
app/
  main.py                  arranque, routers, middlewares (request_id, CORS, errores)
  core/                    config, sesión de base de datos por usuario (RLS), dinero (app/core/money/), identidad y dependencias, errores problem+json
  modules/<módulo>/        iam, billing, finance, goals, planning, reports, notify, ai, ops
    router.py              endpoints /v1/...: HTTP, sin SQL ni reglas
    schemas.py             Pydantic: XxxCreate, XxxUpdate, XxxRead
    application/commands/  un caso de uso de escritura por requisito funcional
    application/queries/   un caso de uso de lectura por consulta
    domain/                read models, puertos (Protocol) y errores del módulo
    infrastructure/        SQL con SQLAlchemy; implementa los puertos de domain/
    deps.py                cableado: arma cada pieza con la sesión de la petición
  workers/                 tareas de Celery: voz, recurrentes, reportes, Money Story, suscripciones, outbox
db/                        migraciones SQL base, pruebas de humo y diccionarios (moneymap-db)
alembic/                   migraciones nuevas, después de la base
tests/unit, tests/integration
docs/constitution.md, docs/engineering.md, docs/adr/, docs/api.md, docs/credenciales.md, docs/specs/NNN-nombre/spec.md
```

## Comandos
- Ejecutar: `docker compose up -d db redis && uv run alembic upgrade head && uv run uvicorn app.main:app --reload`
- Worker: `uv run celery -A app.workers worker --beat --loglevel=info`
- Tests: `uv run pytest` (unitarios + integración contra PostgreSQL 16 con las migraciones aplicadas)
- Pruebas de la base: `docker compose exec db psql -U moneymap -d moneymap -v ON_ERROR_STOP=1 -f /db/tests/smoke_test.sql` (en Git Bash, `MSYS_NO_PATHCONV=1` delante)
- Lint/formato: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
- Contrato para la app: `uv run python -m app.scripts.export_openapi > openapi.json`
- Hooks locales (una sola vez por clon): `git config core.hooksPath .githooks`
- Todo en contenedores, como QA: `docker compose up -d --build`
- Producción y staging: Dokploy con el mismo `docker-compose.yml` y las variables de `.env.prod.example`. Cada despliegue aplica las migraciones y deja al día la clave de `moneymap_api` (`db/deploy/api_role.sql`).

## Estilo y convenciones
- Python 3.12, tipado completo; `mypy --strict` en `app/`.
- Código, nombres y endpoints en inglés; mensajes para el usuario y documentación en español (es-BO).
- `snake_case` para módulos, funciones y columnas; `PascalCase` para clases; esquemas `XxxCreate`, `XxxUpdate`, `XxxRead`.
- Endpoints REST bajo `/v1`, sustantivos en plural (`/v1/accounts`, `/v1/transactions`); lo del usuario autenticado bajo `/v1/me`.
- Montos: `Decimal` en Python y texto en JSON ("69.60"). Nunca `float`.
- Fechas: `timestamptz` en UTC; los días y meses del usuario se calculan con su `timezone`.
- Errores en `application/problem+json` (RFC 9457) con un `code` estable en inglés (`currency_mismatch`, `plan_limit`, `email_taken`) y `detail` en español.
- Dependencias con `uv`; commits con Conventional Commits y scope del módulo (`feat(finance): …`), según `docs/engineering.md` §1.2.

## Reglas
- Lee docs/constitution.md, docs/engineering.md, docs/adr/ y la spec activa antes de tocar código.
- Cada módulo sigue CQRS por caso de uso (ADR-001): `router.py` no tiene SQL ni reglas; `application/commands/` y `application/queries/` son la lógica; `infrastructure/` es el único lugar con SQL, y solo a través de los puertos de `domain/`.
- **Ningún endpoint se mergea sin documentar.** `docs/api.md` es el contrato que la app y la web leen para programar su cliente: cada endpoint nuevo o cambiado se documenta ahí en el mismo PR, junto con `openapi.json` regenerado. Si falta, el PR está incompleto.
- **Al mergear un PR se borra la rama remota**, para no llenar el repositorio de ramas muertas: `git push --no-verify origin --delete <rama>` (el repositorio es `MoneyMapNexus/<repo>`). El repositorio todavía no tiene activado el borrado automático y no se puede activar desde acá (pide permiso de administrador).
- Los endpoints autenticados sacan el usuario del JWT de la spec 001 (`get_current_user_id`). De ahí sale `app.user_id`; nunca lo tomes del cuerpo, de la ruta ni de un encabezado propio.
- Todo el SQL va con `text()` y parámetros de enlace: nunca f-strings, `%` ni concatenación, ni para un nombre de tabla o de columna. Ruff (`S608`) lo verifica y las pruebas están en `tests/integration/test_sql_injection.py`.
- Detrás de Traefik (Dokploy), `request.client.host` es el proxy: para la IP real se usa la última de `X-Forwarded-For` (las de más arriba las escribe el cliente).
- Toda consulta de un usuario corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`. Usa la dependencia de sesión por usuario; no abras sesiones a mano. Sin eso la RLS no devuelve filas. El registro, el login y el refresh son la excepción: van antes de saber quién es y usan `public_session` (`iam.users`, `iam.auth_identities` y `iam.sessions` no tienen RLS).
- La base de datos aplica las reglas del dinero (saldos, moneda de la cuenta, transferencias en la misma moneda, límite de tarjetas, 18+). No las repitas en Python: traduce su error. `SQLSTATE MM001` → 409 `plan_limit`; `HINT currency_mismatch`, `transfer_currency_mismatch` → 422; `HINT account_currency_locked` → 409.
- Nunca: convertir monedas ni sumar montos de monedas distintas; agregar tipos de cambio; usar `float`; escribir `current_balance` o `current_amount`; usar el rol `moneymap_worker` en la API; guardar en logs contraseñas, tokens, fechas de nacimiento o números de tarjeta; enviar saldos o historial a un LLM.
- Hay un solo `docker-compose.yml` para todos los ambientes. Sus puertos se publican solo en `127.0.0.1`: nunca los abras hacia afuera. Fuera de dev, las claves salen del `.env` de Dokploy y sin ellas no arranca.
- No toques sin preguntar: `db/migrations/*.sql` (los cambios van en una migración nueva de Alembic), roles, permisos y RLS, precios y límites de planes (son datos en `billing.plan_features`), el orden de proveedores de IA (se cambia con `ai.set_route_order`).
- No agregues dependencias ni proveedores externos sin preguntar.
- Lo que está fuera de la V1 (escenarios guardados de What If?, QR, cuentas compartidas, temas personalizados) no se programa aunque parezca fácil.
- Errores de integraciones, seguridad y jobs van a `ops.log()`; el detalle de cada petición va al log del contenedor (en Dokploy, la pestaña Logs) con su `request_id`.

## Al terminar cualquier tarea
- Corre `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest` y deja todo en verde.
- Si cambiaste SQL: aplica las migraciones en una base limpia, corre `db/tests/smoke_test.sql` y actualiza `db/DICCIONARIO_CAMPOS.md`.
- Si cambió un endpoint o un esquema: regenera `openapi.json`, actualiza `docs/api.md` y avisa que la app debe regenerar su cliente.
- Verifica que los espejos sigan sincronizados con los otros dos repos: `tool/check-mirrors.sh`. Es espejo: si lo tocás, tocás los dos en el mismo momento.
- Marca en la spec los requisitos cumplidos y anota las dudas nuevas como `[NECESITA ACLARACIÓN]`.
- Resume qué cambió, cómo lo probaste y qué quedó pendiente.
