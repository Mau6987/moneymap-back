# MoneyMap · Base de datos V1

PostgreSQL 16 o superior. Esquema modular de la V1 del PRD: 48 tablas y 10 vistas en 11 módulos, probado con 71 pruebas automáticas.

Los datos son personales: cada fila financiera lleva `user_id` y solo su dueño la ve. No hay cuentas compartidas ni roles entre usuarios. Cada cuenta tiene una moneda y nada se convierte.

## Estructura

```
migrations/            V1: se aplican en orden numérico
  000_core.sql         UUID v7, updated_at, contexto de usuario, particiones, outbox, auditoría
  010_catalog.sql      monedas, países, instituciones financieras, tipos de cuenta, categorías iniciales y listas fijas (tipo de movimiento, grupo del Money Flow)
  020_iam.sql          usuarios (18+), perfil, términos aceptados, personalización, métodos de acceso, sesiones, dispositivos
  030_billing.sql      planes, precios mensual y anual, suscripciones, historial, pagos, límites y cuotas
  040_finance.sql      configuración y periodo, Mis monedas, cuentas, tarjetas, categorías, recurrentes, transacciones (16 particiones)
  050_goals.sql        metas y aportes
  060_planning.sql     historial de Can I Afford It?
  070_reports.sql      totales por categoría, Money Flow, efectivo o tarjeta (funciones) y Money Story semanal y mensual
  080_notify.sql       tipos de aviso, preferencias, notificaciones (particionada)
  090_ai.sql           registro por voz con LLM: proveedores con principal y respaldos, llamadas, uso por usuario (particionadas)
  095_ops.sql          logs de solo inserción e incidentes
  900_security.sql     roles, permisos y Row-Level Security
  950_seed.sql         datos iniciales (idempotente)
  990_comments.sql     descripción de cada tabla, columna, vista y función (la muestra DBeaver)
future/                se aplican cuando cada funcionalidad entre al alcance
  110_budgets.sql      presupuestos por categoría y moneda, y Spending Pace (FTR-014, FTR-015)
  120_scenarios.sql    What If? (FTR-011)
  130_attachments.sql  comprobantes y OCR (FTR-030)
  140_insights.sql     insights y fugas de dinero (FTR-016, FTR-017, FTR-021)
tests/smoke_test.sql   pruebas (corren en una transacción y se revierten)
tools/export_dbml.sql  exporta el esquema a DBML para dbdiagram.io
tools/dictionary.sql + tools/build_dictionary.py   generan DICCIONARIO_CAMPOS.md desde la base
docs/moneymap.dbml     diagrama de todas las tablas
DICCIONARIO_CAMPOS.md  cada tabla y campo: para qué sirve, quién la escribe, ejemplo, relaciones y reglas
moneymap_schema.sql    migrations/ concatenado en un solo archivo, para leer o revisar
```

## Aplicar y probar

```bash
createdb moneymap
for f in migrations/*.sql; do psql -d moneymap -v ON_ERROR_STOP=1 -f "$f"; done
psql -d moneymap -v ON_ERROR_STOP=1 -f tests/smoke_test.sql
```

Con Alembic, la primera revisión ejecuta estos archivos en orden con `op.execute(Path(f).read_text())`. Las migraciones siguientes se escriben normalmente con Alembic.

## Ver el diagrama y regenerar la documentación

- **dbdiagram.io (todas las tablas en un solo diagrama):** abre https://dbdiagram.io/d, borra el ejemplo del editor y pega el contenido de `docs/moneymap.dbml`. No uses "Importar desde PostgreSQL": no entiende triggers, funciones ni particiones. Cada módulo sale como un grupo de color.
- **DBeaver:** clic derecho en un esquema (`finance`, `iam`…) → *View Diagram*, o en *Diagrams* → *Create ER diagram* y arrastra las tablas de varios esquemas. Al pasar el cursor por una columna se ve su descripción.
- **Después de cambiar una migración** (y agregar el comentario de cada columna nueva en `990_comments.sql`):
  ```bash
  psql -d moneymap -At -f tools/export_dbml.sql > docs/moneymap.dbml
  psql -d moneymap -At -f tools/dictionary.sql | python tools/build_dictionary.py > DICCIONARIO_CAMPOS.md
  cat migrations/*.sql > moneymap_schema.sql
  ```

## Roles

| Rol | Quién lo usa | Puede |
|---|---|---|
| `moneymap_app` | API FastAPI | Solo las filas del usuario de la petición (RLS). Lee su suscripción, no la modifica. Escribe logs con `ops.log()`, no los lee. |
| `moneymap_worker` | Workers de Celery | Datos de todos los usuarios, suscripciones y pagos (webhooks de las tiendas). Escribe logs. |
| `moneymap_ops` | Equipo de soporte y operaciones | Lee logs, gestiona incidentes y cambia el orden de proveedores de IA. No ve datos financieros. |

Ninguno es dueño de las tablas; las migraciones corren con otro usuario.

## Reglas para la API

- Al inicio de cada transacción: `SELECT set_config('app.user_id', '<uuid del usuario>', true);`. Sin eso, la RLS no devuelve filas.
- Los montos van en `numeric(19,4)` y en Python como `Decimal`. Nunca `float`.
- Los saldos de cuentas y metas, la cuenta por defecto y Mis monedas los mantiene la base de datos con triggers; la API no los escribe.
- Las consultas a `finance.transactions` siempre filtran por `user_id`: así tocan 1 de 16 particiones.
- Los totales se piden para el periodo del usuario: `SELECT * FROM finance.current_period(:user)` y luego `reports.money_flow(:user, starts_on, ends_on)`.
- Antes de crear una tarjeta, una cuenta en otra moneda o una meta, o de usar el registro por voz o Can I Afford It?: `SELECT billing.try_consume(:user, '<funcionalidad>')`. Para mostrar "1 de 1 tarjetas": `billing.limit_status(:user, 'finance.cards')`.
- Los límites de tarjetas y monedas además los aplica un trigger en `finance.accounts`: si la API se salta la consulta, el `INSERT` falla con `SQLSTATE MM001` (`HINT plan_limit:finance.cards` o `plan_limit:finance.currencies`). La API lo traduce a la pantalla de planes.
- Los demás errores llegan con `ERRCODE check_violation` y el código en el `HINT`: `currency_unavailable`, `currency_mismatch`, `transfer_currency_mismatch`, `invalid_transfer_target`, `invalid_amount`, `account_currency_locked`, `currency_in_use`, `terms_outdated`.

## Cuentas: efectivo y tarjetas

Una cuenta es efectivo o una tarjeta, y las dos tienen saldo. No se distingue débito de crédito ni se guarda cupo. No hay QR, transferencias bancarias ni billeteras en la V1.

| Tipo (`catalog.account_types`) | ¿Tarjeta? (`is_card`) | Datos en `finance.cards` |
|---|---|---|
| `cash` · Efectivo | No | Ninguno |
| `card` · Tarjeta | Sí | Banco emisor (de `catalog.financial_institutions`) y últimos 4 dígitos, opcionales |

- **Países e instituciones:** `catalog.countries` (con su moneda local) y `catalog.financial_institutions` (bancos, cooperativas, microfinancieras y billeteras de cada país). La app muestra los bancos del país del usuario en vez de pedir el nombre como texto. Se cargan Bolivia y los países de las monedas del catálogo (lista PROVISIONAL para revisar); agregar uno es un `INSERT`.

- **Efectivo o tarjeta** sale del tipo de la cuenta: no hay columna de método de pago. `reports.payment_method_totals()` responde "¿cuánto gasté en efectivo y cuánto con tarjeta?".
- **`finance.accounts`** tiene lo común (nombre, tipo, moneda, saldos, por defecto). **`finance.cards`** (1 a 1) tiene el banco y los últimos 4 dígitos. Su clave `(user_id, account_id, account_type)` impide guardar datos de tarjeta en una cuenta de efectivo o de otro usuario.
- **Cuenta por defecto (`is_default`):** la que la app propone primero en Quick Add, voz y escaneo; puede ser efectivo o tarjeta. Una sola por usuario. La primera cuenta lo es sola; marcar otra desmarca la anterior; si se archiva o borra, pasa a la siguiente cuenta activa.
- **Límites del plan:** `finance.cards` = tarjetas activas y `finance.currencies` = monedas distintas entre las cuentas activas. Provisional: gratuito 1 tarjeta y 1 moneda; planes de pago sin límite. Cambiarlo es un `UPDATE` en `billing.plan_features`.
- **Qué cuenta para el límite:** crear, desarchivar, restaurar o convertir una cuenta en tarjeta; una cuenta en una moneda que el usuario todavía no usa. Archivar o borrar libera el cupo. Las altas del mismo usuario se serializan con un lock, así dos instancias de la API no pasan el límite.
- **Al bajar de plan:** lo que tiene se conserva y se sigue usando; solo se impide agregar más.
- **Tipo fijo:** una cuenta con movimientos no cambia de tipo; se crea una nueva.
- **Saldo de una tarjeta:** sube y baja con sus movimientos, como el efectivo; puede quedar negativo. Pasar dinero entre efectivo y tarjeta es una transferencia de la misma moneda.

## Monedas

MoneyMap no tiene tipos de cambio ni convierte monedas. Cada cuenta tiene una moneda y todo lo que pasa en ella queda en esa moneda: quien maneja Bs y USD crea una cuenta para cada una y ve un total por moneda, nunca uno mezclado.

- **Catálogo configurable:** `catalog.currencies` (12 al inicio: BOB, USD, EUR, GBP, ARS, BRL, CLP, COP, MXN, PEN, PYG, UYU). `decimals` dice cuántos decimales acepta (BOB 2, CLP 0). `is_active = false` la deja de ofrecer para cuentas, metas, Mis monedas y moneda principal nuevas; las cuentas que ya existen siguen registrando.
- **Moneda principal (`finance.user_settings.main_currency`):** la que la app muestra primero. Cambiarla no convierte ningún monto.
- **Mis monedas (`finance.user_currencies`):** las que el usuario ve primero en el selector. Se llena sola con la moneda principal y las de sus cuentas. No se puede quitar la principal ni la de una cuenta activa.
- **Movimientos y recurrentes:** si la API no envía `currency`, se usa la de la cuenta; si envía otra, `currency_mismatch`.
- **Transferencias:** solo entre cuentas activas del usuario en la misma moneda, con el mismo monto en ambas.
- **Moneda de una cuenta:** se corrige mientras la cuenta no tenga movimientos ni recurrentes; después, `account_currency_locked`.
- **Metas:** cada meta tiene su moneda; no se vincula a una cuenta.
- **Totales:** `finance.balance_totals` da una fila por moneda: total, cuánto en efectivo y cuánto en tarjetas. Money Flow, efectivo o tarjeta, Money Story y presupuestos también van por moneda.

## Categorías

- Solo categorías, sin subcategorías. Cada usuario recibe una copia editable de las 23 iniciales (`catalog.category_templates`).
- **`kind`** (lista fija `catalog.money_kind`): `income` o `expense`. Decide si suma o resta y no deja registrar un gasto en una categoría de ingreso.
- **`flow_group`** (lista fija `catalog.flow_group`): a qué nodo del Money Flow va un gasto, `needs` (Necesidades) o `lifestyle` (Estilo de vida). Los ingresos no llevan grupo. El nombre y el color de cada grupo los define la app.
- **Sugerencia de Quick Add:** `finance.suggest_from_history(:user, 'netflix')` devuelve la categoría y la cuenta de la última transacción con esa descripción. No hay tabla aparte.

## Transacciones

`finance.transactions` tiene 15 columnas: `id`, `user_id`, `kind`, `account_id`, `category_id`, `amount`, `currency`, `transfer_account_id`, `occurred_on`, `description`, `source`, `recurring_rule_id`, `created_at`, `updated_at`, `deleted_at`.

- **Sin comercio, hora, notas ni estado:** lo que pasó va en `description` ("Netflix", "Almuerzo"); solo la fecha; borrar es `deleted_at`.
- **Pocos joins:** `currency` se copia de la cuenta para sumar por moneda sin unir con `accounts`. El historial une con `categories` y `accounts` por su clave primaria (menos de 1 ms); no se copian nombres porque renombrar una categoría obligaría a reescribir miles de filas.
- **`source`** (lista fija) dice cómo se registró: `manual`, `quick_add`, `voice`, `scan`, `recurring`, `onboarding` o `adjustment`.

## Periodos y recurrentes

- **Periodo del usuario (`finance.user_settings`):** `period_type` = `weekly` (semanal), `semi_monthly` (quincenal: dos por mes) o `monthly` (mensual), y `period_start_day` = día de la semana (0 domingo … 6 sábado), día d de la primera quincena (1 a 13; la segunda empieza el d + 15) o día del mes (1 a 28, por ejemplo su día de cobro). `planned_savings` es el ahorro por periodo, en la moneda principal.
- **`finance.current_period(:user)`** devuelve inicio y fin del periodo actual. Ejemplos: mensual desde el 25 → del 25 al 24; quincenal desde el 1 → 1-15 y 16-fin de mes; semanal desde el lunes → lunes a domingo.
- **Recurrentes (`finance.recurring_rules`):** ingreso o gasto sale de su categoría. `frequency` = `weekly`, `biweekly` (cada 2 semanas), `monthly` o `yearly`. `next_due_on` empieza en `start_date` y el worker lo avanza con `finance.next_occurrence(start_date, frequency, hoy)`: un alquiler del 31 vence el 28 de febrero y vuelve al 31 de marzo.

## Reportes

Los totales se calculan al momento para el rango que pida la API (normalmente el periodo del usuario). No hay tablas precalculadas que mantener al día.

| Función | Devuelve |
|---|---|
| `reports.category_totals(:user, desde, hasta)` | Total y cantidad por categoría y moneda |
| `reports.money_flow(:user, desde, hasta)` | Nodos del Money Flow por moneda: `income`, cada grupo de gasto, `goals` y `available` |
| `reports.payment_method_totals(:user, desde, hasta)` | Gastos e ingresos en efectivo (`cash`) y con tarjeta (`card`) por moneda |

`reports.money_stories` guarda la "foto" del Weekly Check-in (`period_type = 'week'`) y de la Monthly Money Story (`'month'`), una por moneda con movimientos.

## Registro por voz con LLM

El usuario dice "gasté 50 en comida". El worker transcribe el audio, un LLM extrae el movimiento y la app lo muestra para confirmar.

```
app → ai.voice_entries (received) → worker:
  voice.transcribe  ai.route() → principal; si falla, respaldo 2, 3…   → transcript
  voice.extract     ai.route() → principal; si falla, respaldo 2, 3…   → extraction (JSON)
→ app muestra el movimiento → el usuario confirma → finance.transactions (source = 'voice')
```

| Tabla | Para qué |
|---|---|
| `ai.tasks` | Los pasos: `voice.transcribe` (voz a texto) y `voice.extract` (LLM). Una tarea nueva, como leer facturas, es una fila más |
| `ai.models` | Modelos con su precio. Se desactivan con `is_active`; `shutdown_on` los saca solos de las rutas al retirarse |
| `ai.routes` | Orden por tarea: posición 1 = principal, 2+ = respaldos, con timeout y reintentos |
| `ai.route_changes` | Quién cambió el principal, cuándo, el orden anterior, el nuevo y el motivo |
| `ai.calls` | Cada llamada: modelo, posición, estado, latencia, audio, tokens y costo. Solo métricas (por mes, solo inserción) |
| `ai.usage_monthly` | Llamadas, fallas, audio, tokens y costo por usuario, mes y tarea; la suma un trigger de `ai.calls` |
| `ai.voice_entries` | Cada dictado: transcripción, extracción, modelos que respondieron, intentos, si usó respaldo, costo y transacción creada |

- **El worker** lee el orden con `SELECT * FROM ai.route('voice.extract')` (puede cachearlo 60 s), prueba cada modelo hasta `max_retries` y pasa al siguiente. Cada intento es un `INSERT` en `ai.calls`.
- **Si una llamada falla**, el worker escribe el detalle (mensaje, código HTTP, `request_id`) con `ops.log('warning', 'ai', 'ai.call.<estado>', …, p_context => '{"call_id": …}')`. En `ai.calls` solo queda el estado.
- **La base de datos** calcula el costo de cada llamada con el precio del modelo (incluido el mínimo de 10 s de Groq y los tokens en caché), suma intentos, tokens y costo al dictado y al uso mensual del usuario, y anota qué modelo respondió.
- **Si fallan todos**, el worker marca el dictado `failed`, escribe `ops.log('error', 'ai', 'ai.voice.all_providers_failed', …)` (abre un incidente) y devuelve el uso a la cuota con `billing.release(user, 'ai.voice_entries')`.
- **Cambiar el principal** no requiere desplegar:
  ```sql
  SELECT set_config('app.actor', 'dana@moneymap.team', true);
  SELECT ai.set_route_order('voice.extract', ARRAY['deepseek.deepseek-flash', 'openai.gpt-6-luna'], 'OpenAI con timeouts');
  ```
- **Tableros:** `ai.provider_health_24h`, `ai.monthly_cost_by_model`, `ai.monthly_cost_by_user` y `ai.usage_monthly`.
- **Privacidad:** al LLM se envían solo la frase y los nombres de las categorías, cuentas y monedas del usuario; nunca saldos ni historial.

## Suscripciones

El plan de cada usuario sale de la vista `billing.user_plans`: sin suscripción con acceso, está en el plan gratuito.

| Estado | Acceso | Qué pasó |
|---|---|---|
| `trialing` | Plan de pago | Prueba gratis |
| `active` | Plan de pago | Pagada y vigente. Con `auto_renew = false` canceló, pero conserva el acceso hasta `current_period_end` |
| `grace_period` | Plan de pago | Falló el cobro; la tienda reintenta |
| `on_hold` | Gratuito | Falló el cobro y terminó la gracia; recupera el plan al pagar |
| `paused` | Gratuito | Pausada (Google Play) |
| `expired` | Gratuito | Terminó sin renovar; puede volver a suscribirse |
| `revoked` | Gratuito | Reembolsada o revocada |

- **Vuelta a gratuito:** ningún dato se borra. Si tiene más tarjetas o monedas que el límite gratuito, las conserva y las usa, pero no puede agregar más.
- **Historial:** cada cambio queda en `billing.subscription_changes`. Antes de escribir, el worker indica el origen con `set_config('app.change_source', 'store_webhook', true)`.
- **Pagos:** la clave `(provider, provider_transaction_id)` de `billing.payments` evita registrar dos veces el mismo cobro.

## Logs e incidentes

Se guardan en la base porque Cloud Run borra los archivos al reiniciar, porque se consultan con SQL y porque un incidente necesita estado y responsable. El detalle de cada petición y la depuración van a Cloud Logging.

```sql
SELECT ops.log(p_level => 'error', p_category => 'billing',
               p_event_code => 'billing.webhook.invalid_signature',
               p_message => 'Firma inválida en notificación de App Store',
               p_service => 'worker', p_request_id => :request_id,
               p_context => '{"provider": "app_store"}');
```

- `ops.logs` es de solo inserción: nadie puede editar ni borrar un log. La retención borra meses completos.
- `error` y `critical` abren un incidente o se suman al abierto con la misma huella. `critical` lo escala a `sev2`. Si uno resuelto vuelve a ocurrir, se abre otro enlazado al anterior.
- El equipo cambia el estado (`open → investigating → identified → monitoring → resolved → closed`) con un `UPDATE`; la línea de tiempo se escribe sola.
- Nunca guardar en `p_context` contraseñas, tokens ni datos de tarjetas.

## Jobs de Celery Beat

| Job | Frecuencia | Qué ejecuta |
|---|---|---|
| Suscripciones | Cada hora | `billing.process_due_subscriptions()` |
| Particiones | Mensual | `core.ensure_monthly_partitions(...)` para `core.audit_log`, `notify.notifications`, `ai.voice_entries`, `ai.calls` y `ops.logs`, 3 meses hacia adelante |
| Retención | Mensual | `core.drop_partitions_older_than(...)`: auditoría 24 meses, logs 12, notificaciones 12, llamadas a IA 12, voz 6 (valores a confirmar) |
| Recurrentes | Diaria | Recordatorios y `auto_post` de los recurrentes con `next_due_on` vencido; avanza `next_due_on` con `finance.next_occurrence()` |
| Money Story | Al cerrar cada semana y cada mes | Genera `reports.money_stories` y encola el aviso |
| Outbox | Continuo | Publica `core.outbox_events` pendientes |
| Conciliación | Nocturna | `finance.recalculate_account_balance(...)` por muestreo; si difiere, `ops.log('critical', ...)` |

Los jobs de particiones y retención crean y borran tablas: se ejecutan con el rol de migraciones, no con `moneymap_worker`.

## Pendiente para después de la V1

- **Equivalente en la moneda principal:** mostrar, como dato informativo, cuánto son los dólares en Bs ("980 USD ≈ 6.820 Bs"). Necesita un proveedor de tipo de cambio y una tabla de tasas que hoy no existen. No cambia saldos ni reportes.

## Valores provisionales

En esta semilla los planes de pago (`paid_1`, `paid_2`, `paid_3`) están inactivos y sin precios; las migraciones de Alembic dejan solo `paid_3` (Premium) a la venta desde la 0028. Los límites del plan gratuito (1 tarjeta, 1 moneda, metas sin límite desde la 0028, sin registro por voz desde la migración 0023, y 10 consultas de Can I Afford It? al mes) y los de los planes de pago (tarjetas y monedas sin límite) son provisionales y se cambian con un `UPDATE` en `billing.plan_features`, sin desplegar código.
