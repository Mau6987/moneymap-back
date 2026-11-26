# Spec 002 — Cuentas y movimientos en una sola moneda (API)

## Contexto y objetivo
MoneyMap no convierte monedas: cada cuenta tiene una sola moneda, todo lo que pasa en ella queda en esa moneda y solo se transfiere entre cuentas de la misma moneda. Quien maneja bolivianos y dólares crea una cuenta para cada moneda y ve un total por moneda, nunca uno mezclado. Así se evitan tipos de cambio inventados o desactualizados y cada saldo coincide con el dinero real. Esta spec cubre la API de cuentas (efectivo y tarjeta, sin distinguir débito de crédito), movimientos, transferencias, moneda principal, Mis monedas y los totales por moneda que usan el Map, Safe to Spend, Money Flow, Can I Afford It? y el registro por voz. Corresponde a FTR-003, FTR-004, FTR-006, FTR-007 y FTR-012 y a las secciones 6.4, 6.5 y 6.7 del PRD 1.4.

## Usuarios / actores
- Usuario autenticado desde la app.
- Worker de Celery: recurrentes con registro automático, reportes mensuales y Money Story.
- Equipo de MoneyMap: activa o desactiva monedas del catálogo (dato, sin desplegar).

## Historias de usuario
- H1: Como usuario quiero elegir mi moneda principal en el onboarding para que la app me muestre primero mi dinero en esa moneda.
- H2: Como usuario quiero tener efectivo en Bs y en dólares como dos cuentas, cada una con su saldo.
- H3: Como usuario quiero registrar un gasto sin elegir la moneda, porque ya la define la cuenta.
- H4: Como usuario quiero pasar dinero entre mis cuentas de la misma moneda (retiro de cajero con la tarjeta, recargar la tarjeta desde el efectivo).
- H5: Como usuario quiero ver cuánto tengo, cuánto debo y mi neto en cada moneda, sin que la app sume bolivianos con dólares.
- H6: Como usuario quiero corregir la moneda de una cuenta que acabo de crear por error.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `PUT /v1/me/settings` con `main_currency` por primera vez (paso 1 del onboarding), EL SISTEMA ejecuta `finance.setup_user` (configuración, Mis monedas y categorías iniciales) y responde 200 con la configuración.
- RF-2: CUANDO llega `GET /v1/currencies`, EL SISTEMA devuelve primero Mis monedas del usuario y después las demás monedas activas, con código, nombre, símbolo y decimales.
- RF-3: CUANDO llega `POST /v1/accounts` con nombre, tipo (`cash` o `card`), moneda activa y saldo inicial (y, si es tarjeta, banco del catálogo `catalog.financial_institutions` y últimos 4 dígitos), EL SISTEMA crea la cuenta en esa moneda, la suma a Mis monedas y responde 201.
- RF-4: SI la moneda no existe o está desactivada, ENTONCES EL SISTEMA responde 422 `currency_unavailable`.
- RF-5: SI el usuario llegó al límite de tarjetas de su plan, ENTONCES EL SISTEMA responde 409 `plan_limit` con el límite y el uso actual.
- RF-6: CUANDO llega `POST /v1/transactions` sin `currency`, EL SISTEMA guarda el movimiento en la moneda de la cuenta y responde 201 con el movimiento y el saldo nuevo de la cuenta.
- RF-7: SI `currency` viene y es distinta de la moneda de la cuenta, ENTONCES EL SISTEMA responde 422 `currency_mismatch` ("La cuenta "Tarjeta BNB Bs" es en BOB: no se registran movimientos en USD en ella") y no guarda nada.
- RF-8: SI el monto tiene más decimales que los de la moneda (por ejemplo, 0 en CLP o PYG), ENTONCES EL SISTEMA responde 422 `invalid_amount`.
- RF-9: EL SISTEMA no recibe método de pago: "efectivo o tarjeta" sale del tipo de la cuenta (`catalog.account_types.is_card`). Si se crea una tarjeta o una cuenta en otra moneda por encima del límite del plan, ENTONCES responde 409 `plan_limit` (`finance.cards` o `finance.currencies`).
- RF-10: CUANDO llega una transferencia válida entre dos cuentas del usuario de la misma moneda, EL SISTEMA resta el monto de la cuenta de origen y suma el mismo monto a la de destino en la misma transacción de base de datos.
- RF-11: SI la cuenta de destino es de otra moneda, ENTONCES EL SISTEMA responde 422 `transfer_currency_mismatch` y no mueve saldos.
- RF-12: SI la cuenta de destino está archivada o es la misma de origen, ENTONCES EL SISTEMA responde 422 `invalid_transfer_target`.
- RF-13: SI `PATCH /v1/transactions/{id}` cambia la cuenta a una de otra moneda, ENTONCES EL SISTEMA responde 422 `currency_mismatch` y el movimiento queda como estaba.
- RF-14: SI `PATCH /v1/accounts/{id}` cambia la moneda de una cuenta con movimientos o recurrentes, ENTONCES EL SISTEMA responde 409 `account_currency_locked`; MIENTRAS la cuenta no se haya usado, EL SISTEMA acepta el cambio.
- RF-15: CUANDO llega `GET /v1/balances`, EL SISTEMA devuelve una fila por moneda (`finance.balance_totals`): el total, cuánto en efectivo, cuánto en tarjetas y si es la moneda principal, con la principal primero.
- RF-16: CUANDO llega `GET /v1/safe-to-spend?currency=XXX`, `GET /v1/reports/money-flow?period=AAAA-MM&currency=XXX` o `POST /v1/affordability-checks` con moneda, EL SISTEMA calcula solo con las cuentas, movimientos, recurrentes y metas de esa moneda; sin `currency`, usa la moneda principal.
- RF-17: EL SISTEMA descuenta el ahorro planificado (`planned_savings`, por periodo y en la moneda principal) solo del Safe to Spend de la moneda principal, calculado para el periodo del usuario (`finance.current_period`).
- RF-18: CUANDO el LLM devuelve un `currency_hint` en un dictado, EL SISTEMA propone una cuenta del usuario en esa moneda (la última usada); SI no tiene ninguna, ENTONCES responde `needs_account` con la moneda pedida y sus cuentas, sin cambiar el monto ni convertirlo.
- RF-19: SI llega `DELETE /v1/me/currencies/{code}` para la moneda principal o para una moneda con cuentas activas, ENTONCES EL SISTEMA responde 409 `currency_in_use`.
- RF-20: MIENTRAS una moneda está desactivada en el catálogo, EL SISTEMA no la ofrece para cuentas, metas, Mis monedas ni moneda principal nuevas, y las cuentas que ya existen en esa moneda siguen registrando movimientos.
- RF-21: CUANDO se crea o edita un gasto recurrente, EL SISTEMA usa la moneda de su cuenta; SI se envía otra, ENTONCES responde 422 `currency_mismatch`. Las metas tienen su propia moneda y no se vinculan a una cuenta.
- RF-22: EL SISTEMA no expone tipos de cambio, conversiones ni totales que sumen monedas distintas en ningún endpoint, reporte ni notificación.
- RF-23: CUANDO llega `GET /v1/accounts`, EL SISTEMA devuelve las cuentas activas del usuario (sin las borradas ni las archivadas), la de por defecto primero, cada una con su moneda, su saldo y, si es tarjeta, su `institution_code` y sus `last4`.
- RF-24: SI `POST /v1/accounts` o `PATCH /v1/accounts/{id}` llevan un nombre que ya tiene otra cuenta del usuario, sin distinguir mayúsculas, ENTONCES EL SISTEMA responde 409 `account_name_taken` y no guarda nada.
- RF-25: SI una tarjeta llega con un `institution_code` que no está en `catalog.financial_institutions`, ENTONCES EL SISTEMA responde 422 `validation_error` y no crea la cuenta.
- RF-26: CUANDO llega `GET /v1/transactions` (opcional `account_id`, `cursor` y `limit` de 1 a 100, 50 por defecto), EL SISTEMA devuelve los movimientos no borrados del usuario, del más reciente al más viejo por `occurred_on` y después por `id`, y un `next_cursor` opaco mientras haya más; con `account_id`, solo los de esa cuenta, incluidas las transferencias que llegan a ella. SI el cursor no es uno que dio la API, ENTONCES responde 422 `invalid_cursor`.
- RF-27: CUANDO llega `DELETE /v1/transactions/{id}`, EL SISTEMA marca el movimiento como borrado (`deleted_at`), la base devuelve el monto al saldo de sus cuentas y responde 204; SI no existe, ya se borró o es de otro usuario, ENTONCES responde 404 `not_found`.
- RF-28: CUANDO llega `PUT /v1/me/currencies/{code}` con una moneda activa, EL SISTEMA la suma a Mis monedas sin crear ninguna cuenta y responde 200 con la moneda como queda en el selector; repetirlo no cambia nada. SI la moneda no existe o está desactivada, ENTONCES responde 422 `currency_unavailable`.
- RF-29: CUANDO llega `GET /v1/recurring-rules`, EL SISTEMA devuelve los recurrentes vigentes del usuario, cada uno en la moneda de su cuenta, ordenados por `next_due_on`.
- RF-30: CUANDO llega `PATCH /v1/recurring-rules/{id}`, EL SISTEMA corrige solo lo enviado (`account_id`, `category_id`, `amount`, `description`, `frequency`); SI el recurrente, la cuenta o la categoría nuevas no son del usuario, ENTONCES responde 404 `not_found`.
- RF-31: CUANDO llega `DELETE /v1/recurring-rules/{id}`, EL SISTEMA lo da de baja (`deleted_at`): deja de vencer y los movimientos que ya registró se quedan. Responde 204, o 404 si no existe.
- RF-32: CUANDO `GET /v1/transactions` llega con `category_id`, `from`, `to` o `q`, EL SISTEMA devuelve solo los movimientos de esa categoría, entre esas fechas (incluidas) y con ese texto en la descripción sin distinguir mayúsculas, combinados con la cuenta y con la paginación por cursor; SI `from` es posterior a `to`, ENTONCES responde 422 `validation_error`.

## Requisitos no funcionales
- Exactitud: montos como `Decimal`, guardados en `numeric(19,4)` y enviados como texto en JSON; redondeo de visualización según `decimals` de la moneda.
- Idempotencia: `POST /v1/transactions` acepta el encabezado `Idempotency-Key`; un reintento con la misma clave devuelve el mismo movimiento sin duplicarlo.
- Rendimiento: p95 menor a 300 ms en `POST /v1/transactions` y `GET /v1/balances`; las consultas filtran por `user_id` y tocan 1 de 16 particiones.
- Consistencia: los saldos los mantiene la base de datos; la conciliación nocturna (`finance.recalculate_account_balance`) escribe `ops.log('critical', …)` si alguno difiere.
- Seguridad: toda consulta con `app.user_id`; la cuenta de otro usuario devuelve 404, nunca 403, para no revelar que existe.

## Casos límite
- Dos gastos simultáneos en la misma cuenta: los triggers ajustan el saldo sin perder ninguno.
- Usuario con cuentas en 4 monedas: `GET /v1/balances` devuelve 4 filas.
- Una moneda de Mis monedas sin cuentas: no aparece en los totales.
- Netflix cobrado en dólares a una tarjeta en Bs: se registra lo que cobró el banco, en Bs; la API no ofrece "convertir".
- Una tarjeta puede quedar con saldo negativo: el total de la moneda lo refleja; no hay cupo ni deuda aparte.
- Cambiar la moneda principal: los reportes muestran otra moneda primero, ningún monto cambia y el ahorro planificado queda en la moneda principal nueva (ver dudas).
- Monedas sin decimales (CLP, PYG): "1000" pasa y "1000.5" no.
- Un dictado dice "20 dólares" y el usuario solo tiene cuentas en Bs: `needs_account`, no se guarda nada hasta que elija.

## Fuera de alcance
- Tipos de cambio, conversión de monedas, cambio de divisas como movimiento y cuentas con varias monedas.
- Cuentas bancarias, billeteras y pagos con QR.
- Presupuestos y Spending Pace (V1.1; su tabla ya prevé una moneda por presupuesto).
- Importar movimientos desde bancos o archivos.

## Estado de implementación (2026-10-15)

Primer corte con la arquitectura del ADR-001 (`router → application → domain`,
infraestructura por puertos). Tests en `tests/integration/test_finance_accounts.py`
y `test_finance_currencies.py`, y unitarios en `tests/unit/test_money.py`.

| RF | Estado | Nota |
|---|---|---|
| RF-1 | Cumplido | `PUT /v1/me/settings` deja la moneda principal y siembra las categorías iniciales. Idempotente. |
| RF-2 | Cumplido | `GET /v1/currencies`: Mis monedas primero y después las demás activas. |
| RF-3 | Cumplido | `POST /v1/accounts` con efectivo y tarjeta; el banco y los últimos 4 dígitos van a `finance.cards`. |
| RF-4 | Cumplido | La moneda inexistente o desactivada la rechaza `catalog.assert_currency_active`. |
| RF-5 | Cumplido | Límite de tarjetas del plan (`finance.cards`). |
| RF-6 a RF-8 | Cumplido | `POST /v1/transactions` sin moneda: la toma de la cuenta (RF-7 avisa con 422 si no coincide) y los decimales del monto los valida la base (RF-8). Acepta `Idempotency-Key`. |
| RF-9 | Cumplido | Límite de monedas del plan (`finance.currencies`). |
| RF-10 a RF-12 | Cumplido | La transferencia es el mismo `POST /v1/transactions` con `kind: "transfer"`. Los dos saldos los mueve el trigger en la misma transacción. |
| RF-13 | Cumplido | `PATCH /v1/transactions/{id}`: la moneda no se cambia y la base avisa si la cuenta nueva es de otra. |
| RF-14 | Cumplido | `PATCH /v1/accounts/{id}`: nombre y moneda, esta última mientras la cuenta no se haya usado. |
| RF-15 | Cumplido | `GET /v1/balances` lee `finance.balance_totals` y devuelve el saldo con los decimales de su moneda. |
| RF-16 | En parte | `GET /v1/safe-to-spend?currency=` ya filtra por moneda (spec 003); faltan Money Flow y Can I Afford It?. |
| RF-17 | Cumplido | El ahorro planificado se resta solo del Safe to Spend de la moneda principal (spec 003, RF-6). |
| RF-18 | Por hacer | El dictado por voz. |
| RF-19 | Cumplido | `DELETE /v1/me/currencies/{code}`. La base impide quitar la principal o una con cuentas. |
| RF-20 | Cumplido | Una moneda retirada del catálogo no se ofrece para datos nuevos; la que el usuario ya usa sigue saliendo, marcada `is_active: false`. |
| RF-21 | Cumplido | `POST /v1/recurring-rules`: el gasto o el ingreso recurrente. La moneda la pone la cuenta y los decimales del monto los valida la base (migración 0003). |
| RF-22 | Cumplido | Ningún endpoint expone tipos de cambio ni suma monedas distintas: los totales van por moneda y las pruebas lo comprueban con dos monedas a la vez. |
| RF-23 | Cumplido | `GET /v1/accounts`, con el banco y los últimos 4 dígitos de las tarjetas (`tests/integration/test_finance_account_list.py`). |
| RF-24 y RF-25 | Cumplido | `core/errors.py` traduce `accounts_name_uq` y `cards_institution_code_fkey`, que antes salían como 500. |
| RF-26 | Cumplido | `GET /v1/transactions` pagina por cursor sobre `transactions_feed_idx` (`tests/integration/test_finance_transaction_history.py`). |
| RF-27 | Cumplido | `DELETE /v1/transactions/{id}`: borrado lógico; el saldo lo devuelve el trigger. |
| RF-32 | Cumplido | Filtros `category_id`, `from`, `to` y búsqueda `q` sobre el mismo cursor; la búsqueda usa `transactions_search_idx` (trigramas) y escapa `%` y `_` (`tests/integration/test_finance_transaction_filters.py`). |
| RF-28 | Cumplido | `PUT /v1/me/currencies/{code}` con `finance.remember_currency` (`tests/integration/test_finance_my_currencies.py`). |
| RF-29 a RF-31 | Cumplido | Listar, corregir y dar de baja recurrentes (`tests/integration/test_finance_recurring_rules.py`). Registrarlos solos al vencer (`auto_post`) va con el worker de la spec 003. |
| Autenticación | Cumplido | La identidad sale del JWT de la spec 001 (RF-19 de esa spec). |

- 2026-10-15 · **Las transferencias van en `POST /v1/transactions`** con `kind: "transfer"` y `transfer_account_id`. Es la misma tabla y los mismos triggers que mueven los dos saldos en la misma transacción de base; inventar un `/v1/transfers` aparte habría duplicado el caso de uso. Queda pendiente de RF el historial (`GET /v1/transactions`).
- 2026-10-15 · **La idempotencia se guarda en Redis**, 24 h y por usuario: `finance` no tiene tabla para eso y no se quiso agregar una migración. Si Redis no responde se deja pasar, como en el límite de intentos: se prefiere arriesgar un movimiento duplicado a dejar sin registrar.
- 2026-10-15 · `POST /v1/transactions` acepta `source` con la lista de la base (`manual`, `quick_add`, `voice`, `scan`, `recurring`, `onboarding`, `adjustment`), aunque ningún RF lo define: la columna existe y la app necesita marcar Quick Add.
- 2026-10-15 · **Las pruebas que necesitan dos monedas suben el límite de `finance.currencies` del plan gratuito** mientras corren. Lo gratuito permite una sola, y los límites son datos (`billing.plan_features`), no código.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- `db/tests/smoke_test.sql` en verde (las pruebas 6 a 20, 27, 63 a 65 y 67 cubren moneda de la cuenta, transferencias, recurrentes, metas, reportes, totales, Mis monedas y monedas desactivadas).
- `openapi.json` regenerado; ningún esquema tiene campos de tipo de cambio.
- Demostración manual: cuentas en Bs y USD, un gasto en cada una, una transferencia en Bs, un intento de transferir de USD a Bs rechazado y el Map con un total por moneda.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 | MM-30 · FTR-002 Onboarding guiado (API en MM-74) | Cumplido |
| RF-2 a RF-14, RF-20 a RF-22 | MM-26 · FTR-003 Gestión multicuenta (API en MM-50 y MM-51) | Cumplido |
| RF-15 | MM-27 · FTR-012 Financial Position (Map) | Por hacer |
| RF-16 | MM-23 · Money Flow, MM-34 · Safe to Spend y MM-35 · Can I Afford It? (los tres reusan el filtro por moneda) | Por hacer |
| RF-17 | MM-34 · FTR-009 Safe to Spend (API en MM-54) | Cumplido |
| RF-18 | MM-40 · FTR-007 Registro por voz con agente IA | Por hacer |
| RF-19 | MM-33 · FTR-024 Ajustes de cuenta, moneda y preferencias | Cumplido (MM-50) |
| RF-23 a RF-31 | MM-26 · FTR-003 Gestión multicuenta | Cumplido |
| RF-32 | MM-29 · FTR-006 Historial, filtros y búsqueda | Cumplido |

## Decisiones tomadas
- Bugs de QA (BUG-029, migración 0021): una transferencia no saca de la cuenta de origen más de lo que tiene (`422 account_insufficient`). Desde la migración 0025 (BUG-024, decisión del 2026-10-31) un gasto común tampoco: un gasto que pasa el saldo de su cuenta, al crearlo o al editarlo para que saque más, es `422 account_insufficient`. Un ingreso no tiene límite, y una corrección que no saca más pasa aunque la cuenta ya esté en negativo.

- 2026-10-15 · **RF-20** se resuelve así: `GET /v1/currencies` lista las monedas del usuario aunque el catálogo las haya retirado (sus cuentas siguen existiendo y tienen que seguir registrando), y solo las activas para las que no son suyas. El intento de crear una cuenta en una moneda retirada lo rechaza la base con 422 `currency_unavailable`.
- 2026-10-15 · `GET /v1/currencies` devuelve además `is_active`, `is_mine` e `is_main_currency`. La spec pedía código, nombre, símbolo y decimales, pero sin esos tres la app no puede desactivar en pantalla una moneda retirada (RF-20) ni separar Mis monedas.
- 2026-10-15 · `DELETE /v1/me/currencies/{code}` de una moneda que no está entre las del usuario responde 404 `not_found`. La spec no lo definía.
- 2026-10-17 · **Listar cuentas (RF-23)** y los dos errores que salían como 500 (RF-24, RF-25) se agregan a la spec: el nombre repetido es 409 `account_name_taken`, como `email_taken`; el banco inexistente es un error de forma, 422 `validation_error`.
- 2026-10-17 · **El historial (RF-26) pagina por cursor, no por número de página.** Un OFFSET se vuelve lento con historiales largos y repite o pierde movimientos si se registra uno mientras la persona baja por la lista. El cursor es opaco (base64 de la fecha y el `id`) para poder cambiarlo sin romper la app. Al principio solo filtraba por cuenta; los filtros por fecha, categoría y texto llegaron con RF-32 sobre el mismo cursor.
- 2026-10-17 · **Borrar un movimiento (RF-27) es lógico**, como el resto de la base: queda la fila con `deleted_at` y deja de contar en saldos, historial y reportes.
- 2026-10-17 · **Sumar una moneda (RF-28) es `PUT /v1/me/currencies/{code}`**, no un POST: es idempotente y hace par con el `DELETE` de la misma ruta. No choca con el límite del plan, que cuenta las monedas de las cuentas activas (`billing.resource_usage`), no las de Mis monedas.
- 2026-10-17 · **Corregir un recurrente (RF-30) no toca `next_due_on`.** Cambiar la frecuencia cambia los vencimientos que siguen al próximo, no el próximo. Mover el próximo vencimiento queda para cuando lo pida una pantalla.
- 2026-10-15 · `PATCH /v1/accounts/{id}` acepta solo `name` y `currency`.
- 2026-10-22 · `PATCH /v1/accounts/{id}` acepta también `archived`, y `GET /v1/accounts?archived=true` lista las archivadas (mockup "Cuentas", "Archivadas (1)"). Las reglas son las de la base: archivar libera el cupo y desarchivar lo vuelve a ocupar. La moneda queda en Mis monedas.
- 2026-10-15 · El periodo financiero y el ahorro planificado se guardan en la misma fila que la moneda principal, pero llegan con la spec 003: `PUT /v1/me/settings` hoy solo acepta `main_currency`.

## Dudas abiertas
- [NECESITA ACLARACIÓN] **Al archivar una cuenta, ¿qué pasa con su moneda en Mis monedas?** La base la libera del límite del plan, pero no dice si sale del selector.
- [NECESITA ACLARACIÓN] Si el usuario cambia dólares por bolivianos fuera de la app, ¿cómo lo refleja? Hoy no se registra; una opción es un "ajuste de saldo" en cada cuenta que no cuente como gasto ni como ingreso en los reportes.
- [NECESITA ACLARACIÓN] El ahorro planificado está solo en la moneda principal. Si el usuario cambia su moneda principal, ¿se conserva el monto, se pone en 0 o se le pregunta?
- [NECESITA ACLARACIÓN] Money Story: la base guarda una por moneda con movimientos. ¿La app muestra solo la de la moneda principal o todas?
- [NECESITA ACLARACIÓN] ¿`opening_balance` es obligatorio al crear una cuenta? Hoy es opcional y vale 0 por defecto, como en la base.
- [NECESITA ACLARACIÓN] La respuesta de `GET /v1/balances`: ¿lista desnuda o `{"balances": [...]}`? ¿Se expone `accounts` (cuántas cuentas hay por moneda), que la vista calcula?
- [NECESITA ACLARACIÓN] Después de la principal, ¿con qué se ordenan las demás monedas: por código o por `finance.user_currencies.sort_order` (el orden de Mis monedas)?
- [NECESITA ACLARACIÓN] Con el plan gratuito (1 moneda) no se puede tener cuentas en dos monedas. En las pruebas se sube el límite a mano, pero para probarlo de verdad en la app haría falta que los planes de pago tengan precio y queden activos. ¿Cuándo?
