# MEMORY.md — memoria de trabajo

Notas cortas para que cualquier sesión nueva sepa dónde está parado el backend.
El detalle está en `docs/` y en el código; aquí solo lo importante.
Se actualiza al cerrar cada tarea.

## Dónde estamos (2026-10-15)

- El backend era un esqueleto. El contenido real está en `docs/` (constitución,
  ingeniería, PRD, 7 specs) y en `db/` (15 migraciones, triggers, RLS, 71 pruebas de humo).
- Arquitectura acordada: **monolito modular con CQRS por caso de uso + DDD pragmático**.
  Está en `docs/adr/001-monolito-modular-cqrs.md` y en `engineering.md` §3.3.
  `router → application → domain`, e `infrastructure` implementa los puertos.
- Regla que no se negocia: **las reglas del dinero las aplica PostgreSQL**. En Python
  no se revalidan, se traducen con `core/errors.py` (constitución §3).
- Sin agregados ricos, sin eventos de dominio y sin bus. Los eventos ya tienen su
  lugar en `core.outbox_events`.
- **La autenticación ya existe** (spec 001): registro con el correo verificado por link,
  login (exige el correo verificado: 409 `email_not_verified`), refresh con rotación,
  `GET /v1/me` y **ingreso con Google**, que vincula por
  correo si la cuenta ya existe. `get_current_user_id` ya no responde 501: todos los
  módulos, `finance` incluido, usan el token de verdad.
- `finance` (spec 002) tiene ya `PUT /v1/me/settings` (moneda principal y siembra de
  categorías), `POST /v1/accounts`, `PATCH /v1/accounts/{id}`, `GET /v1/balances`,
  `GET /v1/currencies`, `DELETE /v1/me/currencies/{code}`, y `POST` y `PATCH`
  `/v1/transactions` (gastos, ingresos y transferencias, con `Idempotency-Key`).
- Los proveedores de identidad son **contraseña, Google y Apple**. Meta se descartó. Apple se verifica con su JWKS público (sin `.p8`) y acepta varias audiencias (`APPLE_CLIENT_IDS`). Las credenciales se sacan como dice `docs/credenciales.md`.
- `docs/engineering.md` y `docs/constitution.md` son **espejo de tres repos** (`moneymap-app`, `moneymap-back`, `moneymap-web`): `tool/check-mirrors.sh` lo verifica.
- **La clave del ticket sale del tablero de Jira (proyecto MM), no de las tablas de las specs**; se sincronizaron el 2026-10-16 (MM-95). Autenticación → MM-32; multicuenta → MM-26 (API: MM-50 y MM-51); onboarding → MM-30 (API: MM-74); restablecer contraseña → MM-89; trabajadores → MM-91. Antes las ramas salían con MM-14 y MM-17, que en el tablero son la web y los mockups.
- El registro **no pide la fecha de nacimiento** (2026-10-16): la quitan la migración 0004 y la constitución §5.

## Pendiente inmediato

- Spec 002 (finance) está casi entera: falta **Safe to Spend y Money Flow** (RF-16 a
  RF-18, que son las specs 003 y 004) y marcar RF-22.
- Spec 001, lo que falta: **Apple** (RF-6 a RF-8), `PATCH /v1/me` (RF-10 a RF-12),
  avatar en Cloud Storage (RF-13, RF-14) y preferencias (RF-15, RF-16).
- **Restablecer la contraseña** (spec 008) está hecho: código de 6 dígitos por correo, guardado
  con argon2id en `iam.verification_tokens` (sin migración), y al cambiarla se cierran todas las
  sesiones. Faltan el aviso de «tu contraseña cambió» y decidir cuánto dura el código.
- El correo sale por **SMTP** (`docs/credenciales.md`); en dev el link va al log.
- **El worker existe** (`app/workers/`): la app de Celery con su calendario y el job diario
  de limpieza, que borra las verificaciones y los tokens de un solo uso de más de 30 días.
  Para los jobs que toquen datos de todos los usuarios hará falta `moneymap_worker`.
- **Huecos de las specs que hay que cerrar antes de programar**, anotados en `docs/api.md`:
  listar cuentas, agregar una moneda a Mis monedas, el historial de movimientos (FTR-006),
  la ruta de los recurrentes y quién puede mandar `source`.
- Errores que hoy devuelven 500 y necesitan `code` y estado: nombre de cuenta repetido
  (23505) e institución que no existe (23503). Ver `[NECESITA ACLARACIÓN]` en la spec 002.
- Sin CI (`engineering.md` §6.9): las reglas dependen de disciplina y revisión.

## Trampas conocidas

- El registro necesita un correo verificado: en dev el link sale en el log de uvicorn
  (`[correo de dev] Link para verificar …`). Desde el emulador de Android la API es
  `http://10.0.2.2:8000`, así que `PUBLIC_BASE_URL` va con esa dirección en `.env`.
  En los tests, `register_body` es async y crea la verificación ya verificada.
- En Windows, `export_openapi > openapi.json` escribe en cp1252 y rompe las tildes:
  `PYTHONIOENCODING=utf-8 uv run python -m app.scripts.export_openapi > openapi.json`.
- `iam.email_verifications` sale de la migración de Alembic 0002, no de `db/migrations/`:
  la primera revisión solo aplica los SQL base.
- Los tests de integración van contra PostgreSQL real, no hay mocks:
  `docker compose up -d db redis`, `alembic upgrade head` y `db/dev/api_role.sql`
  (crea el rol `moneymap_api`, que hereda de `moneymap_app` y aplica la RLS).
- `pytest-asyncio` 1.4 con asyncpg necesita **un solo bucle por corrida**
  (`asyncio_default_test_loop_scope = "session"` en `pyproject.toml`).
- **Un `ApiError` hace que la dependencia de sesión haga rollback**: lo que el caso de
  uso escribió antes de levantar el error se pierde. Cuando la escritura tiene que
  sobrevivir al error (el corte de RF-18), se confirma con el puerto `UnitOfWork`.
- El límite de intentos cuenta por IP y en las pruebas todas salen de la misma: hay un
  fixture autouse que limpia Redis (`clear_rate_limits`).
- La identidad en los tests se inyecta con `dependency_overrides[get_current_user_id]`,
  salvo las pruebas que usan el token de verdad.
- `ops.logs` no lo puede leer `moneymap_app`: para comprobarlo hay que usar el fixture
  `owner_connection` (dueño de las tablas).
- El nombre de una cuenta o un correo con SQL se guardan como texto: todo el SQL va
  con `text()` y parámetros, y ruff (`S608`) marca cualquier consulta concatenada.
- **Cada endpoint nuevo se documenta en `docs/api.md` en el mismo PR**, con
  `openapi.json` regenerado: es el contrato que la app y la web leen.
- **Las ramas no se borran solas.** El repositorio no tiene activado el borrado
  automático y no se puede activar sin permiso de administrador, así que al mergear
  se borra la rama a mano: `gh api -X DELETE repos/adminnexusbo/<repo>/git/refs/heads/<rama>`.
- `openapi.json` está en `.gitignore`: se regenera con
  `uv run python -m app.scripts.export_openapi`, no se commitea. El contrato de lo
  que puede consumir la app está en `docs/api.md`, y se actualiza cuando cambia un
  endpoint.
- Para crear datos de prueba: `iam.users` no tiene RLS, pero todo lo financiero sí
  (`finance.user_settings`, `finance.accounts`...): usar `user_session(user_id)`.
- Los montos salen del `Money` de `app/core/money/`: `Decimal` exacto, decimales de la
  moneda como dato y ninguna suma entre monedas distintas.
- `JWT_SECRET` es obligatorio: la API no arranca sin él, para no firmar con un secreto
  por defecto que estaría en el repositorio. En dev va en `.env`.
