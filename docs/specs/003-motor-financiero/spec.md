# Spec 003 — Motor financiero: Safe to Spend (API)

## Contexto y objetivo
Safe to Spend es el cálculo que dice cuánto dinero queda libre después de las obligaciones del periodo del usuario. Esta spec cubre la API de ese motor: el monto, su desglose y el ahorro planificado que el usuario define. No persiste ningún valor: se recalcula en cada consulta a partir de los saldos que mantienen los triggers, los recurrentes pendientes, el ahorro planificado y los aportes a metas del periodo. Es la pieza que reusan Can I Afford It? (spec 005) y Goal Forecast, y la que extiende el RF-16 y el RF-17 de la spec 002. Corresponde a FTR-009 y a la sección 6.10 del PRD 1.5. Tablas: `iam.users`, `finance.accounts`, `finance.transactions`, `finance.recurring_transactions`, `goals.goals`, `goals.goal_contributions`.

## Usuarios / actores
- Usuario autenticado desde la app.
- Worker de Celery: registra los recurrentes vencidos, que cambian los pendientes del próximo periodo.
- La app MoneyMap como cliente de la API.

## Historias de usuario
- H1: Como usuario quiero un endpoint que me diga cuánto puedo gastar en mi periodo, en una moneda concreta.
- H2: Como usuario quiero el desglose de ese número, concepto por concepto.
- H3: Como usuario quiero guardar cuánto quiero ahorrar por periodo.
- H4: Como usuario con Bs y USD quiero el cálculo por moneda, sin que se mezclen.
- H5: Como usuario quiero que mis datos no los vea nadie más.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `GET /v1/safe-to-spend?currency=XXX`, EL SISTEMA responde 200 con el monto total, los cuatro conceptos del desglose (`current_balance`, `pending_recurring`, `planned_savings`, `goal_contributions`), la moneda usada y el periodo calculado.
- RF-2: EL SISTEMA calcula Safe to Spend como `current_balance − pending_recurring − planned_savings − goal_contributions`.
- RF-3: SI no llega `currency`, ENTONCES EL SISTEMA usa la moneda principal del usuario.
- RF-4: SI `currency` no existe o está desactivada en el catálogo, ENTONCES EL SISTEMA responde 422 `currency_unavailable`.
- RF-5: EL SISTEMA calcula solo con las cuentas, los recurrentes y las metas de la moneda pedida (`finance.balance_totals`, `finance.recurring_transactions`, `goals.goals`).
- RF-6: EL SISTEMA resta `planned_savings` únicamente cuando la moneda pedida es la principal del usuario.
- RF-7: CUANDO llega `PUT /v1/me/settings` con `planned_savings` o con el periodo financiero (`period_type` y `period_start_day`), EL SISTEMA los guarda y responde 200 con la configuración resultante.
- RF-8: SI `planned_savings` es negativo, o tiene más decimales que los de la moneda, ENTONCES EL SISTEMA responde 422 `invalid_amount`.
- RF-9: SI `period_type` no es `weekly`, `semi_monthly` o `monthly`, o `period_start_day` queda fuera del rango de la base, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-10: EL SISTEMA resuelve el periodo vigente con `finance.current_period`, con el tipo, el día de inicio y la zona horaria del usuario.
- RF-11: EL SISTEMA cuenta como pendientes los recurrentes cuya próxima fecha cae dentro del periodo vigente y que todavía no se registraron. Un gasto recurrente que no se pagó (su próxima fecha quedó antes del periodo) cuenta cada vez que vence hasta el fin del periodo: lo atrasado más lo de este periodo (QA 2026-11-03). Lo atrasado cuenta desde el periodo en que se creó el recurrente, no desde su `start_date`. Las fechas siguen la fórmula de `finance.next_occurrence` (un fijo del 31 vuelve al 31 después de febrero). Los ingresos recurrentes cuentan una sola vez, la que vence en el periodo: es a propósito, para que lo que se puede gastar nunca salga de más.
- RF-12: EL SISTEMA suma como aportes a metas las `goals.goal_contributions` con fecha dentro del periodo vigente, de las metas en esa moneda.
- RF-13: EL SISTEMA devuelve todos los montos como texto en JSON ("1000.00"), nunca como número.
- RF-14: EL SISTEMA no devuelve tipos de cambio, equivalencias en otra moneda ni totales que sumen monedas distintas.
- RF-15: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`; los datos de otro usuario no aparecen nunca.
- RF-16: MIENTRAS el usuario no tenga cuentas en la moneda pedida, EL SISTEMA responde 200 con el desglose en cero y no un error.
- RF-17: CUANDO llega `POST /v1/recurring-rules/{id}/payments` (opcional `amount` y `occurred_on`), EL SISTEMA registra en la misma transacción un movimiento de ingreso o gasto según la categoría del recurrente, en su cuenta, con `source = recurring` y `recurring_rule_id`, con el monto del recurrente si no llega otro y con la fecha de hoy del usuario si no llega otra; avanza `next_due_on` al vencimiento siguiente (`finance.next_occurrence`) y responde 201 con el movimiento y el recurrente como quedó.
- RF-18: SI el recurrente no existe, está dado de baja o es de otro usuario, ENTONCES `POST /v1/recurring-rules/{id}/payments` responde 404 `not_found` y no registra nada. Acepta `Idempotency-Key`: un reintento no registra dos pagos.
- RF-19: SI el vencimiento siguiente pasa la `end_date` del recurrente, ENTONCES EL SISTEMA lo deja inactivo: deja de vencer y de contar como pendiente.
- RF-20: CUANDO corre el job diario, EL SISTEMA registra cada recurrente con `auto_post` cuyo `next_due_on` ya llegó en la zona horaria del usuario, con su monto y en la fecha en que vencía, y avanza `next_due_on`; si quedaron varios vencimientos atrasados, registra uno por cada uno.
- RF-21: CUANDO llega `POST /v1/recurring-rules` o `PATCH /v1/recurring-rules/{id}` con `auto_post`, EL SISTEMA lo guarda; por defecto es `false`.
- RF-22: CUANDO llega `POST /v1/recurring-rules/{id}/skip`, EL SISTEMA avanza `next_due_on` al vencimiento siguiente sin registrar un movimiento (se pagó por fuera de la app) y responde 200 con el recurrente como quedó; esa vez deja de contar como pendiente. Pasada la `end_date`, termina como en RF-19. El que no existe, está dado de baja o es de otro: 404 `not_found`.
- RF-23: CUANDO llega `GET /v1/recurring-rules`, EL SISTEMA devuelve en `pending_dates` las veces por pagar de cada recurrente, la más vieja primero: `next_due_on` y, en un gasto comprometido, las que cuenta RF-11 hasta el fin del periodo. Solo `next_due_on` se paga u omite (QA 2026-11-03).

## Requisitos no funcionales
- Exactitud: montos como `Decimal`, guardados en `numeric(19,4)` y enviados como texto.
- Rendimiento: p95 menor a 300 ms. El cálculo no se cachea en la V1: son cuatro agregaciones filtradas por `user_id` sobre 1 de 16 particiones.
- Consistencia: el cálculo se deriva de los saldos que mantienen los triggers; no escribe nada. Si la conciliación nocturna detecta una diferencia de saldo, escribe `ops.log('critical', …)`.
- Seguridad: el usuario de otro no devuelve 404 ni 403, simplemente no aparece en el cálculo.
- Contrato: el endpoint documentado en OpenAPI con un ejemplo con el caso del PRD §6.10.

## Casos límite
- Varios recurrentes con la misma próxima fecha: se suman todos.
- Un recurrente todavía no registrado al cerrar el periodo: deja de contar como pendiente.
- Meta cumplida o archivada: no aporta al desglose.
- Periodo mensual con día de inicio 31 en un mes de 30 días: se ajusta al último día del mes.
- Zona horaria del usuario distinta de UTC: el periodo se resuelve en su zona, no en UTC.
- Monedas sin decimales (CLP, PYG): `planned_savings` acepta enteros y rechaza `1000.5` (RF-8).
- Usuario sin cuentas: desglose en cero con la moneda principal.
- Moneda desactivada con cuentas existentes: el cálculo sigue funcionando.
- `planned_savings` en `null`: se cuenta como cero.

## Fuera de alcance
- Presupuestos y Spending Pace: no restan de Safe to Spend y su tabla no entra a la V1.
- Financial Forecast a 30, 60 y 90 días y What If?: fuera de la V1. No se guardan escenarios.
- Persistir el resultado de Safe to Spend en una tabla o cachearlo.
- Tipos de cambio y conversión de monedas.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- El caso del PRD §6.10 en verde: 2500 − 700 − 500 − 300 = 1000.
- Un usuario de otro no puede ver el cálculo ajeno.
- `openapi.json` regenerado; ningún esquema tiene campos de tipo de cambio.
- `db/tests/smoke_test.sql` en verde.

## Estado de implementación (2026-10-17)

Tests en `tests/integration/test_finance_safe_to_spend.py` y
`tests/integration/test_finance_period_settings.py`.

| RF | Estado | Nota |
|---|---|---|
| RF-1 a RF-3, RF-13 | Cumplido | `GET /v1/safe-to-spend`: `amount` y el desglose en `breakdown`, como texto. La fórmula está en `SafeToSpend.amount` (dominio). El caso del PRD (2500 − 700 − 500 − 300 = 1000) está en verde. |
| RF-4 | Cumplido | `catalog.assert_currency_active`, salvo que el usuario tenga cuentas en esa moneda (caso límite de la moneda desactivada). |
| RF-5, RF-6, RF-14 | Cumplido | Todo filtrado por moneda; el ahorro planificado solo en la principal. |
| RF-7 | Cumplido | `PUT /v1/me/settings` con `period_type`, `period_start_day` y `planned_savings`; se cambia solo lo enviado. |
| RF-8 | Cumplido | El negativo lo rechaza el CHECK de la tabla; los decimales, el trigger `user_settings_check_amount` (migración 0006). Los dos, `422 invalid_amount`. |
| RF-9 | Cumplido | El tipo lo valida el esquema; el día de inicio, el CHECK `user_settings_period_start_chk`. Los dos, `422 validation_error`. |
| RF-10 | Cumplido | `finance.current_period` con el "hoy" del usuario en su zona horaria. |
| RF-11 | Cumplido | Cuenta los gastos recurrentes comprometidos (`is_committed`) cada vez que vencen desde `next_due_on` hasta el fin del periodo, también los atrasados sin pagar desde el periodo en que se creó el recurrente. Los ingresos cuentan una vez, a propósito. Al registrarse (RF-17, RF-20) o al omitir una vez (RF-22), `next_due_on` avanza y esa vez deja de contar. |
| RF-12 | Cumplido | Aportes del periodo, menos retiros, de metas vivas en esa moneda. |
| RF-15 | Cumplido | Sesión por usuario con `app.user_id`. |
| RF-16 | Cumplido | Sin cuentas en la moneda, todo en cero. |
| RF-17 a RF-19, RF-21 | Cumplido | `POST /v1/recurring-rules/{id}/payments` y `auto_post` en el alta y la edición (`tests/integration/test_finance_recurring_payments.py`). |
| RF-22 | Cumplido | `POST /v1/recurring-rules/{id}/skip` (`tests/integration/test_finance_recurring_payments.py`). Revisión del #126: sin esto, lo pagado por fuera se sumaba cada periodo. |
| RF-23 | Cumplido | `pending_dates` en `GET /v1/recurring-rules`, con `finance.recurring_occurrences`, la misma función de RF-11 (`tests/integration/test_finance_recurring_rules.py`). |
| RF-20 | Cumplido | Job `finance.post_due_recurring_rules`, todos los días a las 05:00 UTC (`tests/integration/test_workers_recurring.py`). |

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-21 | MM-54 · api: motor Safe to Spend (y MM-34 · FTR-009 Safe to Spend) | Cumplido |

## Decisiones tomadas
- Bugs de QA (BUG-027 y BUG-028, migración 0021): un recurrente puede no tener cuenta (`account_id` en null, con su `currency`) y la cuenta se elige al pagar (`account_id` en el pago; sin ninguna, `422 account_required`). Pagar un gasto que pasa el saldo de esa cuenta es `422 account_insufficient`.

- 2026-10-17 · **Registrar un recurrente (RF-17, RF-20) es un solo SQL** que usan la API y el job: inserta el movimiento y avanza `next_due_on` en la misma transacción. La respuesta trae el movimiento sin saldos (como el historial) y el recurrente: los saldos los da `GET /v1/accounts`.
- 2026-10-17 · **El job recorre a las personas una por una**, cada una en su transacción con `app.user_id`, como el borrado de cuentas: `finance.recurring_rules` tiene RLS y así no hace falta el rol `moneymap_worker`. Si una falla, queda en `ops.log` y siguen las demás.
- 2026-10-17 · **El periodo quincenal es `semi_monthly`, no `biweekly`.** La base lo define así (`finance.period_type`): del día d al d + 14 y del d + 15 a fin de mes, que es el "quincenal" del PRD. `biweekly` (cada 14 días) es una frecuencia de los recurrentes, no un periodo. Se corrigió el RF-9.
- 2026-10-17 · **El resumen del onboarding usa este mismo cálculo** (`SqlSafeToSpendReader`): antes tenía su propia copia de la fórmula. Desde ahora las metas cumplidas o archivadas tampoco cuentan ahí.
- 2026-10-17 · **El desglose va en `breakdown`** y el total en `amount`, para que la app pinte el número grande sin buscarlo entre los conceptos.
- 2026-10-17 · **Sin moneda principal no hay cálculo:** `422 onboarding_incomplete`, el mismo error que el onboarding. Sin cuentas pero con moneda principal sí hay cálculo, en cero (RF-16).
- 2026-10-17 · **`pending_recurring` cuenta solo gastos comprometidos.** Los ingresos recurrentes no se restan, y un gasto con `is_committed = false` tampoco: así lo define la columna y así ya lo calculaba el onboarding.

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿Conviene exponer el Safe to Spend también en `GET /v1/balances` para que el Map lo traiga en una sola llamada? Propuesta: no, el Map hace las dos y la separación mantiene el cálculo testeable solo.
- [NECESITA ACLARACIÓN] Si el usuario cambia su moneda principal, el ahorro planificado queda en la moneda anterior: ¿se conserva el monto, se pone en cero o se le pregunta? Hoy se conserva tal cual; si la moneda nueva no tiene decimales (CLP, PYG) el monto viejo no se vuelve a validar.
- [NECESITA ACLARACIÓN] Un recurrente sin `auto_post` que la persona nunca marca como pagado se queda con `next_due_on` en el pasado: deja de contar como pendiente al cambiar de periodo, pero tampoco vuelve a contar en el siguiente. ¿Se avanza solo al cerrar el periodo (sin registrar nada), o se le avisa a la persona (spec 006)?
- [NECESITA ACLARACIÓN] ¿Hace falta "saltar" un vencimiento sin registrar el pago (por ejemplo, un mes que no se pagó el gimnasio)?
- [NECESITA ACLARACIÓN] Los aportes a metas: ¿se miden por las contribuciones del periodo o por el `planned_contribution` de cada meta?
- [NECESITA ACLARACIÓN] ¿Hace falta un índice en `recurring_transactions` por `user_id` y próxima fecha antes de la V1, o el volumen lo justifica recién en la V1.1?
