# Spec 004 — Map y Money Flow (API)

## Contexto y objetivo
La API entrega los dos reportes que sostienen la pantalla principal de la app: la posición financiera del mes (saldo disponible, ingresos, gastos y ahorrado) y el recorrido del dinero por grupo de categoría. Los dos se calculan por moneda y ninguno suma monedas distintas. Esta spec extiende los RF-15 y RF-16 de la spec 002, que ya fijan que los totales van por moneda con la principal primero. Corresponde a FTR-012 y FTR-013 y a las secciones 6.9 y 6.11 del PRD 1.5. Tablas: `finance.transactions`, `finance.balance_totals`, `finance.categories`, `finance.money_flow_groups`.

## Usuarios / actores
- Usuario autenticado desde la app.
- La app MoneyMap como cliente de la API.
- Equipo de MoneyMap: mantiene la lista fija de grupos del Money Flow como dato, sin desplegar código.

## Historias de usuario
- H1: Como usuario quiero un endpoint con los totales del mes en una moneda concreta.
- H2: Como usuario quiero un endpoint con el recorrido de mi dinero por grupo y por categoría.
- H3: Como usuario quiero que los dos reportes usen la misma moneda y no mezclen.
- H4: Como usuario quiero que una transferencia entre mis cuentas no cuente como ingreso ni como gasto.
- H5: Como usuario quiero que mis reportes no los vea nadie más.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `GET /v1/reports/position?period=AAAA-MM&currency=XXX`, EL SISTEMA responde 200 con el saldo disponible, los ingresos, los gastos y lo ahorrado de esa moneda en ese mes.
- RF-2: SI no llega `period`, ENTONCES EL SISTEMA usa el periodo vigente del usuario (`finance.current_period`).
- RF-3: SI no llega `currency`, ENTONCES EL SISTEMA usa la moneda principal del usuario.
- RF-4: SI `currency` no existe o está desactivada, ENTONCES EL SISTEMA responde 422 `currency_unavailable`.
- RF-5: SI `period` no tiene el formato `AAAA-MM`, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-6: CUANDO llega `GET /v1/reports/money-flow?period=AAAA-MM&currency=XXX`, EL SISTEMA responde 200 con los nodos `income`, `needs`, `lifestyle`, `goals` y `available`, cada uno con su monto.
- RF-7: EL SISTEMA devuelve el nodo `available` como ingresos menos Necesidades, menos Estilo de vida y menos Metas, de modo que la suma de los cuatro grupos iguale los ingresos.
- RF-8: CUANDO el usuario pide el detalle de un grupo, EL SISTEMA devuelve sus categorías con sus montos, de mayor a menor, con `GET /v1/reports/money-flow/categories?period=AAAA-MM&currency=XXX&group=needs`.
- RF-9: EL SISTEMA excluye del cálculo de ingresos y de gastos las transferencias entre cuentas del usuario.
- RF-10: EL SISTEMA agrupa los gastos de una categoría borrada bajo `sin_categoria`, y sus montos siguen sumando.
- RF-11: EL SISTEMA calcula cada reporte solo con las cuentas, los movimientos y las metas de la moneda pedida.
- RF-12: EL SISTEMA devuelve todos los montos como texto en JSON, nunca como número.
- RF-13: EL SISTEMA no devuelve tipos de cambio, equivalencias en otra moneda ni totales que sumen monedas distintas.
- RF-14: EL SISTEMA devuelve una fila por moneda con cuentas cuando la app pide el Map completo con `GET /v1/balances` (spec 002 RF-15), con la principal primero.
- RF-15: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`; los datos de otro usuario no aparecen nunca.
- RF-16: MIENTRAS el mes pedido no tenga movimientos, EL SISTEMA responde 200 con todos los montos en cero y no un error.
- RF-17: CUANDO llega `on=AAAA-MM-DD` en vez de `period`, EL SISTEMA calcula el reporte del periodo financiero del usuario (semanal, quincenal o mensual) que contiene ese día; con los dos, responde 422 `validation_error`.

## Requisitos no funcionales
- Exactitud: montos como `Decimal`, guardados en `numeric(19,4)` y enviados como texto.
- Rendimiento: p95 menor a 300 ms. Los reportes agregan sobre `finance.transactions` filtrando por `user_id` y por rango de fechas, sobre 1 de las 16 particiones.
- Consistencia: los reportes se derivan de los movimientos y de los saldos que mantienen los triggers; no escriben nada.
- Contrato: los tres endpoints documentados en OpenAPI con el caso del PRD §6.11.
- Seguridad: el reporte de otro usuario no existe para el usuario actual.

## Casos límite
- Mes sin movimientos: todos los montos en cero.
- Ingreso sin categoría: suma a `income` y no a un grupo de gasto.
- Transferencia entre cuentas de la misma moneda: excluida de ingresos y gastos (RF-9).
- Gasto mayor que el ingreso del mes: `available` negativo, y la suma de RF-7 se mantiene.
- Categoría borrada: sus movimientos van a `sin_categoria`.
- Moneda del usuario sin cuentas: totales en cero, no un error.
- Moneda desactivada con cuentas existentes: los reportes siguen funcionando.
- Un movimiento con fecha en el límite del periodo, en la zona horaria del usuario: entra al periodo que corresponde a su zona, no a UTC.
- Los cuatro grupos suman los ingresos incluso con un ingreso registrado en una categoría de gasto por error: el grupo sale del tipo de la categoría.

## Fuera de alcance
- Presupuestos, Spending Pace y Financial Forecast: fuera de la V1, no entran en ningún nodo.
- Financial Insights y Financial Leaks: fuera de la V1.
- Comparar meses, proyectar a futuro o guardar un reporte.
- Tipos de cambio y equivalencias en la moneda principal.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- Necesidades, Estilo de vida, Metas y Disponible suman los ingresos del mes (PRD §6.11).
- Con cuentas en Bs y USD, `GET /v1/reports/position` devuelve un total por moneda y ninguno mezclado.
- Una transferencia entre cuentas propias no altera los ingresos ni los gastos.
- `openapi.json` regenerado; ningún esquema tiene campos de tipo de cambio.
- `db/tests/smoke_test.sql` en verde, con las pruebas de reportes por moneda.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-5, RF-14 | MM-27 · FTR-012 Financial Position (Map) | Hecho (RF-14 ya estaba en la spec 002) |
| RF-6 a RF-13, RF-15 a RF-17 | MM-23 · FTR-013 Money Flow | Hecho |

## Decisiones
- `period=AAAA-MM` es el mes calendario (del 1 al último día); sin `period`, el periodo vigente del usuario, que puede empezar otro día (spec 003, RF-7).
- "Lo ahorrado" (`saved`) son los aportes a metas del rango, menos los retiros: lo mismo que el nodo `goals`. El ahorro planificado no entra, porque es una intención y no dinero que se movió.
- Un recurrente sin registrar no cuenta como gasto: los reportes salen solo de los movimientos.
- El detalle por categoría va en un endpoint aparte (RF-8), con `group` en `needs`, `lifestyle` o `income`.
- Sin categoría (RF-10) sale como `category_id` y `name` en null; la app pone el texto.

## Dudas abiertas
- [NECESITA ACLARACIÓN] Con un periodo que no empieza el día 1, ¿`period=AAAA-MM` debería ser el periodo del usuario que empieza en ese mes, en vez del mes calendario? Hoy es el mes calendario (ver Decisiones).
- [NECESITA ACLARACIÓN] `available_balance` es el saldo de hoy aunque se pida un mes pasado. ¿Hace falta el saldo al cierre de ese mes?
- [NECESITA ACLARACIÓN] Lo ahorrado y si un recurrente sin registrar cuenta como gasto quedaron resueltos con la opción más simple (ver Decisiones); confirmar con producto.
