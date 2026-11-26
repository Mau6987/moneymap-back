# Spec 007 — Onboarding y categorías (API)

## Contexto y objetivo
La API sostiene el onboarding en cuatro pasos y entrega las categorías iniciales con las que el usuario empieza a registrar movimientos. El paso 1 fija la moneda principal y siembra las categorías de gasto e ingreso; los pasos 2 a 4 usan los endpoints de cuentas y de recurrentes que ya existen en la spec 002; el cierre del onboarding devuelve el resumen con Ingresos, Comprometido y Safe to Spend. La sugerencia de categoría por descripción es por reglas, sin IA, y se resuelve con el historial del propio usuario. Corresponde a FTR-002, FTR-005 y FTR-031 y a las secciones 6.3 y 6.6 del PRD 1.5. Tablas: `iam.users`, `finance.categories`, `finance.money_flow_groups`, `catalog.income_categories`.

## Usuarios / actores
- Persona nueva que acaba de registrarse, desde la app.
- Usuario que administra sus categorías.
- Equipo de MoneyMap: mantiene el catálogo de categorías iniciales y los grupos del Money Flow como dato, sin desplegar código.

## Historias de usuario
- H1: Como persona nueva quiero que la API guarde cada paso de mi onboarding sin perder lo anterior.
- H2: Como persona nueva quiero recibir mis categorías iniciales listas para usar.
- H3: Como usuario quiero crear, editar y borrar mis categorías.
- H4: Como usuario quiero que la API me sugiera la categoría según lo que escribí antes.
- H5: Como usuario quiero que mis categorías no las vea nadie más.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `PUT /v1/me/settings` con `main_currency` por primera vez, EL SISTEMA ejecuta `finance.setup_user` y responde 200 con la configuración (spec 002 RF-1).
- RF-2: CUANDO `finance.setup_user` corre por primera vez, EL SISTEMA siembra las categorías iniciales de gasto e ingreso del usuario desde `catalog` y las suma a Mis monedas, y no repite la siembra si el usuario ya las tiene.
- RF-3: MIENTRAS falte `onboarding_completed_at`, EL SISTEMA acepta los pasos en cualquier orden y no marca el onboarding como terminado.
- RF-4: CUANDO llega `POST /v1/onboarding/complete`, EL SISTEMA marca `onboarding_completed_at`, responde 201 con Ingresos, Comprometido y Safe to Spend del periodo vigente, y es idempotente si ya estaba marcado.
- RF-5: SI el usuario todavía no tiene ninguna cuenta, ENTONCES EL SISTEMA responde 422 `onboarding_incomplete` con el paso que falta.
- RF-6: CUANDO llega `GET /v1/categories?type=expense`, EL SISTEMA devuelve las categorías del usuario con su grupo del Money Flow, su ícono y su color.
- RF-7: CUANDO llega `POST /v1/categories` con `name`, `type` (`income` o `expense`) y, si es gasto, `money_flow_group`, EL SISTEMA la crea para ese usuario y responde 201.
- RF-8: SI `type` es `income` y llega `money_flow_group`, o al contrario un gasto sin grupo, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-9: SI el nombre queda vacío al quitar espacios, o pasa los 60 caracteres, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-10: CUANDO llega `PATCH /v1/categories/{id}`, EL SISTEMA actualiza solo los campos enviados y responde 200 con la categoría.
- RF-11: SI el cambio de `type` dejaría movimientos de ingreso en una categoría de gasto, ENTONCES EL SISTEMA responde 409 `category_type_in_use` y no cambia nada.
- RF-12: CUANDO llega `DELETE /v1/categories/{id}`, EL SISTEMA acepta el borrado y los movimientos que la usaban quedan sin categoría, agrupados bajo `sin_categoria` en los reportes.
- RF-13: CUANDO llega `GET /v1/transactions/category-suggestion?description=Netflix&type=expense`, EL SISTEMA responde con la categoría del último movimiento del usuario con esa descripción, sin distinguir mayúsculas ni tildes; SI no hay coincidencia, ENTONCES responde 204.
- RF-14: EL SISTEMA no llama a ningún modelo de IA para sugerir la categoría: es una consulta sobre el historial del propio usuario.
- RF-15: EL SISTEMA no ofrece subcategorías ni jerarquías: `finance.categories` no tiene padre.
- RF-16: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`; la categoría de otro usuario responde 404 y no 403.
- RF-17: EL SISTEMA devuelve las categorías de ingreso con su tipo distinguiendo al menos salario, trabajo independiente o emprendimiento, y mesada familiar.
- RF-18: SI el usuario intenta leer o modificar una categoría del catálogo que no se le sembró, ENTONCES no la ve: el catálogo es dato de referencia, no una categoría suya.
- RF-19: EL SISTEMA responde los montos del resumen del onboarding como texto en JSON, nunca como número.

## Requisitos no funcionales
- Idempotencia: `finance.setup_user` y `POST /v1/onboarding/complete` pueden repetirse sin duplicar categorías, cuentas ni Mis monedas.
- Consistencia: la siembra de categorías corre en la misma transacción que el paso 1; si falla, no queda a medias.
- Rendimiento: p95 menor a 300 ms en los endpoints de categorías y de sugerencia.
- Seguridad: el usuario solo ve sus categorías; las del catálogo son de referencia y se copian al sembrarlas, no se comparten.
- Contrato: los endpoints documentados en OpenAPI con un ejemplo del paso 1 y del cierre.

## Casos límite
- El usuario repite el paso 1 con la misma moneda: no se duplican categorías ni Mis monedas.
- El usuario cambia la moneda principal después del registro: las categorías ya sembradas se conservan.
- Dos categorías con el mismo nombre y el mismo tipo: se aceptan, porque no hay índice único por nombre.
- Descripción con tildes o mayúsculas distintas: la sugerencia no distingue y responde igual.
- Categoría sin movimientos: se borra sin dejar rastro en los reportes.
- Categoría con movimientos: se borra y sus movimientos caen en `sin_categoria` (RF-12).
- Categoría de ingreso con movimientos que se quiere pasar a gasto: 409 (RF-11).
- Un usuario creado antes de existir las categorías iniciales: el primer paso del onboarding las siembra.
- Cierre del onboarding sin cuentas: 422 `onboarding_incomplete` (RF-5).
- Moneda sin decimales: los montos del resumen respetan los decimales de la moneda.

## Fuera de alcance
- El paso "¿Qué quieres lograr?" y la creación de la primera meta dentro del onboarding.
- Presupuestos, ahorro planificado y Spending Pace durante el onboarding.
- Aprendizaje automático de categorías y cualquier llamada a un modelo de IA.
- Subcategorías y jerarquías de categorías.
- Categorías compartidas entre usuarios.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- Un usuario nuevo recibe sus categorías iniciales de gasto e ingreso con ícono y color (PRD §6.6).
- La sugerencia por descripción devuelve la misma categoría que la vez anterior (PRD §6.6).
- No existe ninguna columna de categoría padre en el esquema.
- `finance.setup_user` corrido dos veces no duplica categorías ni Mis monedas.
- `openapi.json` regenerado.
- `db/tests/smoke_test.sql` en verde, con las pruebas de categorías, de siembra y de borrado con movimientos.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-6, RF-15 a RF-19 | MM-30 · FTR-002 Onboarding guiado (API en MM-74) | Cumplido |
| RF-2, RF-7 a RF-14 | Sin ticket propio en el tablero (CRUD de categorías y sugerencia por descripción); los ingresos van en MM-28 · FTR-031 | Cumplido |

## Estado (MM-74)

| RF | Estado | Dónde |
|---|---|---|
| RF-1, RF-2 | Cumplido | `PUT /v1/me/settings` ya corría `finance.setup_user` (spec 002). |
| RF-3 | Cumplido | `GET /v1/onboarding`: si terminó, la moneda principal y cuántas cuentas, ingresos y gastos recurrentes tiene, para que la app retome. |
| RF-4, RF-5, RF-19 | Cumplido | `POST /v1/onboarding/complete`: idempotente, montos como texto, `422 onboarding_incomplete` con `missing_step`. |
| RF-6, RF-17 | Cumplido | `GET /v1/categories?type=` con `money_flow_group`, ícono, color y `template_key`. |
| RF-15, RF-18 | Cumplido | El esquema no tiene categoría padre; el catálogo no se expone como categoría del usuario. |
| RF-16 | Cumplido | Sesión por usuario con RLS; una cuenta o categoría ajena responde 404. |
| RF-7 a RF-9 | Cumplido | `POST /v1/categories`: un gasto sin grupo o un ingreso con grupo, el nombre vacío o de más de 60 caracteres: `422 validation_error`. |
| RF-10, RF-11 | Cumplido | `PATCH /v1/categories/{id}`: pasar a ingreso quita el grupo; con movimientos o recurrentes, `409 category_type_in_use`. |
| RF-12 | Cumplido | `DELETE /v1/categories/{id}`: borrado lógico; los reportes ya juntaban las borradas como `sin_categoria`. Con recurrentes sin borrar, `409 category_in_use`; en una borrada no entran movimientos ni recurrentes nuevos (`404`). Migración `0008`. |
| RF-13, RF-14 | Cumplido | `GET /v1/transactions/category-suggestion`: SQL sobre el historial propio, sin IA; sin coincidencia, `204`. |

Agregados que no estaban en la spec y la app necesita:

- `GET /v1/countries` y `GET /v1/institutions?country=`: el país sugiere la moneda y los bancos (mockup 05a).
- `POST /v1/recurring-rules`: los pasos 3 y 4. Sin `account_id` va a la cuenta por defecto, así la app retoma sin conocer los ids de las cuentas.
- Migración `0003`: el saldo inicial de una cuenta y el monto de un recurrente respetan los decimales de la moneda (`invalid_amount`), como ya lo hacían los movimientos.
- Montos con tope de 19 dígitos y descripción que no queda vacía al quitar espacios (`validation_error`), para que no lleguen a la base como un 500.

Pruebas: `tests/integration/test_finance_onboarding.py` (25), `tests/integration/test_finance_categories.py` (16) y `tests/integration/test_finance_category_suggestion.py` (5).

Decisiones de RF-7 a RF-14:

- **El nombre repetido en el mismo tipo responde `409 category_name_taken`.** Los casos límite dicen que se acepta, pero la base tiene `categories_name_uq` (usuario, tipo y nombre sin mayúsculas): manda la base. Con otro tipo sí se acepta.
- **RF-11 también cuenta los recurrentes**: un recurrente toma de su categoría si es ingreso o gasto, así que cambiarle el tipo daría vuelta el recurrente. Y cuenta los movimientos borrados, porque la FK de `finance.transactions` los sigue apuntando.
- 2026-10-20 · **Una categoría con recurrentes sin borrar no se borra (`409 category_in_use`).** Desactivarlos solos cambiaría el Safe to Spend sin que el usuario lo sepa; dejarlos haría que el worker registre en una categoría borrada. Lo aplica la base (migración `0008`), igual que `currency_in_use`.
- 2026-10-20 · **En una categoría borrada no entran movimientos ni recurrentes nuevos** (`404`, como una cuenta que no existe). Solo al crearlos o al cambiarles la categoría: los viejos se siguen editando y borrando.
- **RF-13 saltea las categorías borradas**: si el último movimiento con esa descripción está en una categoría borrada, sugiere la del anterior. Las tildes se quitan con `translate` (sin la extensión `unaccent`), y `type` es obligatorio: la sugerencia tiene que servir para el movimiento que se está escribiendo.

## Dudas abiertas
- Decidido en MM-23 (a confirmar): el ingreso mensual del paso 3 se guarda como un recurrente de ingreso mensual (`finance.recurring_rules` con una categoría de ingreso), igual que los gastos del paso 4.
- Decidido en MM-23 (a confirmar): el cierre se marca en el servidor (`POST /v1/onboarding/complete`), así es el mismo en todos los dispositivos.
- [NECESITA ACLARACIÓN] Ingresos y Comprometido del resumen cuentan los recurrentes que **vencen en el periodo vigente** (spec 003, RF-11). Un sueldo que ya se cobró este mes no entra hasta el próximo periodo. ¿Es lo esperado, o el resumen del onboarding debe mostrar el monto mensual?
- [NECESITA ACLARACIÓN] Al borrar una categoría inicial, ¿hace falta poder restaurarla desde el servidor, o el usuario simplemente crea una nueva?
- [NECESITA ACLARACIÓN] ¿El catálogo de categorías iniciales y los grupos del Money Flow viven en `catalog` con su propio seed, o se agregan a `950_seed.sql`?
