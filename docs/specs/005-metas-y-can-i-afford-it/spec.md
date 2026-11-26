# Spec 005 — Metas y Can I Afford It? (API)

## Contexto y objetivo
La API de dos funcionalidades que se apoyan en el motor de la spec 003. Las metas guardan un objetivo de ahorro, sus aportes y su proyección de logro. Can I Afford It? recibe el monto de una compra y devuelve su impacto sobre Safe to Spend, los pagos próximos y las metas, calculado en el momento y sin guardar nada. Ninguna de las dos convierte monedas ni suma monedas distintas. Corresponde a FTR-010, FTR-018 y FTR-019 y a las secciones 6.12 y 6.13 del PRD 1.5. Tablas: `goals.goals`, `goals.goal_contributions`, `iam.users`, `finance.accounts`.

## Usuarios / actores
- Usuario autenticado desde la app.
- La app MoneyMap como cliente de la API.
- Worker de Celery: calcula la proyección de metas para los avisos de la spec 006.

## Historias de usuario
- H1: Como usuario quiero crear y mantener mis metas desde la API.
- H2: Como usuario quiero registrar aportes y que el saldo de la meta lo mantenga la base.
- H3: Como usuario quiero que la API me diga cuándo voy a llegar a mi meta.
- H4: Como usuario quiero que la API evalúe una compra sin guardarla.
- H5: Como usuario quiero que mis metas no las vea nadie más.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `POST /v1/goals` con `name`, `target_amount`, `currency`, `target_date` y `priority`, EL SISTEMA crea la meta con `current_amount` en cero y responde 201.
- RF-2: SI `currency` no existe o está desactivada, ENTONCES EL SISTEMA responde 422 `currency_unavailable`.
- RF-3: SI `target_amount` es menor o igual a cero, o tiene más decimales que los de la moneda, ENTONCES EL SISTEMA responde 422 `invalid_amount`.
- RF-4: CUANDO llega `PATCH /v1/goals/{id}` con campos parciales, EL SISTEMA actualiza solo los enviados y responde 200 con la meta como quedó.
- RF-5: CUANDO llega `DELETE /v1/goals/{id}`, EL SISTEMA borra la meta y sus aportes y no toca los movimientos de ninguna cuenta; SI `current_amount` es mayor que cero, ENTONCES responde 409 `goal_has_saved` y no la borra: primero hay que retirar el saldo a una cuenta.
- RF-6: CUANDO llega `POST /v1/goals/{id}/contributions` con `amount` y `date`, EL SISTEMA crea el aporte y deja que el trigger actualice `current_amount`; la API nunca escribe el saldo de la meta.
- RF-7: SI un aporte deja `current_amount` igual a `target_amount`, ENTONCES EL SISTEMA lo acepta, marca la meta como cumplida y responde 201; SI lo pasa, ENTONCES responde 422 `contribution_exceeds_remaining` y no cambia nada (BUG-049). A una meta cumplida o archivada no se aporta: 422 `goal_closed`. SI un retiro o un objetivo más alto la deja por debajo, ENTONCES vuelve a `active` y `achieved_at` queda en `null`.
- RF-8: SI el aporte es negativo, ENTONCES EL SISTEMA responde 422 `invalid_amount`.
- RF-9: CUANDO llega `GET /v1/goals`, EL SISTEMA devuelve las metas del usuario, con `current_amount`, el porcentaje de avance y la fecha estimada de logro de cada una.
- RF-10: EL SISTEMA calcula la fecha estimada de logro como la diferencia por lograr dividida entre el aporte mensual promedio, y la devuelve en `null` cuando no haya al menos un aporte.
- RF-11: CUANDO llega `POST /v1/affordability-checks` con `amount`, `currency` y opcionalmente `category_id`, EL SISTEMA responde 200 con el veredicto, el dinero disponible, lo que queda después de la compra, el impacto informativo por meta y los supuestos usados.
- RF-12: SI el monto es menor o igual al dinero disponible, ENTONCES EL SISTEMA responde `"verdict": "affordable"` con `available_after`. El dinero disponible es el Safe to Spend más los ingresos recurrentes que faltan llegar en el periodo, menos el gasto variable que falta gastar.
- RF-13: SI el monto supera el dinero disponible, ENTONCES EL SISTEMA responde `"verdict": "not_yet"` con `available_after` negativo y `goal_impacts` informativos: cuánto saldría de cada meta y cuántos meses se atrasaría, sin usarlas para pagar.
- RF-14: SI el sobrante mensual es positivo y lo que falta se junta en 5 años o menos, ENTONCES EL SISTEMA responde `"estimated_on"` con el día en que el saldo simulado llega al precio y una serie `projection` con ese saldo, mes a mes desde hoy hasta esa fecha; si no, `estimated_on` es `null` y `projection` va vacía. La simulación arranca en el disponible y, después del fin del periodo, cuenta los recurrentes en sus fechas y resta el gasto variable promedio, los aportes a metas y el ahorro planificado por día. `monthly_surplus` (ingresos menos gastos recurrentes, promedio de 12 meses, menos gasto variable, metas y ahorro planificado) se informa, pero la fecha no sale de él.
- RF-15: EL SISTEMA no persiste nada de `affordability-checks`: no crea fila, no guarda escenario y no registra un movimiento.
- RF-16: EL SISTEMA calcula affordability solo con las cuentas, recurrentes y metas de la moneda pedida, y no convierte desde otra.
- RF-17: EL SISTEMA devuelve todos los montos como texto en JSON, nunca como número.
- RF-18: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`; la meta de otro usuario responde 404 y no 403.
- RF-19: MIENTRAS el usuario no tenga metas, EL SISTEMA responde el veredicto igual, con `goal_impacts` vacío y la fecha estimada por la simulación.
- RF-20: CUANDO llega `POST /v1/goals/{id}/withdrawals` con `amount` y `account_id`, EL SISTEMA baja la meta, sube el saldo de esa cuenta y responde 201; SI el monto supera lo acumulado, ENTONCES responde 422 `goal_insufficient`, también con dos retiros a la vez.
- RF-21: CUANDO un aporte trae `account_id`, EL SISTEMA baja el saldo de esa cuenta en la misma transacción y no lo vuelve a restar en Safe to Spend; SI la cuenta es de otra moneda, ENTONCES responde 422 `currency_mismatch`; SI está archivada, ENTONCES responde 404; SI el aporte pasa el saldo de la cuenta, ENTONCES responde 422 `account_insufficient`. Una cuenta con aportes no cambia de moneda (409 `account_currency_locked`).
- RF-22 (REQ-056): CUANDO llega `GET /v1/goals/movements`, EL SISTEMA responde los aportes y retiros del usuario, del más reciente al más viejo, con la meta, la cuenta, el monto positivo y si es aporte o retiro, filtrados por moneda, cuenta y fechas y paginados por cursor; también los de una meta borrada.
- RF-23: CUANDO una meta activa tiene `target_date` de hoy en adelante y le falta dinero, EL SISTEMA responde `suggested_contribution`: lo que falta dividido entre los periodos de ahorro completos del usuario hasta esa fecha (`period_type`), redondeado hacia arriba a la unidad y sin pasar de lo que falta; con menos de un periodo, todo lo que falta. Los periodos se cuentan por meses: Bs 1000 en 2 meses con periodo quincenal son 4 periodos y Bs 250. SI no hay fecha, ya pasó o la meta no está activa, ENTONCES es `null`.

## Requisitos no funcionales
- Exactitud: montos como `Decimal`, en `numeric(19,4)` y como texto en JSON. Los saldos de metas los mantienen los triggers.
- Rendimiento: p95 menor a 300 ms en los dos endpoints y en el análisis.
- Consistencia: `affordability-checks` es de solo lectura sobre el estado actual; dos llamadas seguidas con el mismo monto devuelven lo mismo si nada cambió.
- Seguridad: toda consulta con `app.user_id`; ninguna respuesta incluye datos de otro usuario.
- Contrato: los endpoints documentados en OpenAPI, con el caso del PRD §6.13.

## Casos límite
- Meta sin aportes: `estimated_completion` en `null` (RF-10).
- Meta cumplida al 100 %: deja de estimar fecha y se marca cumplida; si un retiro la deja por debajo del objetivo, vuelve a activa y vuelve a estimar.
- Meta con saldo: no se borra hasta retirar todo a una cuenta (`409 goal_has_saved`).
- Aportes irregulares: el promedio usa los meses con aporte.
- Aporte exactamente igual a lo que falta: la meta queda cumplida en cero.
- Aporte que supera lo que falta: 422 `contribution_exceeds_remaining`; antes se aceptaba y lo que sobraba salía de la cuenta sin ir a ningún lado (BUG-049, RF-7).
- Aporte a una meta cumplida: 422 `goal_closed`; el retiro sí se permite (RF-7).
- Meta con la misma moneda que el usuario y otra en moneda distinta: `GET /v1/goals` las devuelve todas, con su moneda, y no las suma.
- Compra exactamente igual al dinero disponible: `affordable` con `available_after` en cero.
- Compra en una moneda sin cuentas del usuario: se responde igual, con el disponible en cero de esa moneda.
- Sin metas: el `not_yet` igual trae `estimated_on` si se junta en 5 años.
- Sobrante mensual cero o negativo: `not_yet` sin fecha y con los supuestos que lo explican.
- `category_id` de una categoría de ingreso: 422 `validation_error`.
- Dos aportes simultáneos a la misma meta: los triggers suman los dos sin perder ninguno.

## Fuera de alcance
- Presupuestos por categoría y Spending Pace: fuera de la V1. La regla de comparación contra el presupuesto de la categoría no entra.
- Guardar escenarios, incluido What If?: la V1 calcula en el momento y no persiste.
- Financial Forecast a 30, 60 y 90 días.
- Tipos de cambio: una compra en otra moneda se calcula en esa moneda, nunca se convierte.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- Una meta de 5000 con 2500 aportados devuelve 50 % de avance (PRD §6.12).
- Con un aporte promedio de 500 al mes, la fecha estimada queda a 5 meses (PRD §6.12).
- Con un Safe to Spend de 1000 y sin ingresos ni gasto variable, un análisis de 800 responde `affordable` con 200 (PRD §6.13).
- Un sueldo recurrente que falta llegar en el periodo suma al disponible y puede convertir un `not_yet` en `affordable`.
- Una compra mayor que el disponible responde `not_yet` con el impacto en metas como información y, si se junta en 5 años, `estimated_on`.
- Sin metas y con sobrante positivo, `estimated_on` no es `null`.
- Un gasto anual cuenta en el sobrante (1/12 por mes) y corre la fecha si cae antes de juntar.
- Con sobrante cero o negativo, o a más de 5 años, `estimated_on` es `null`.
- Ningún análisis deja filas nuevas en la base.
- `openapi.json` regenerado; ningún esquema tiene campos de tipo de cambio.
- `db/tests/smoke_test.sql` en verde, con las pruebas de metas y de aportes.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-9 | MM-36 · FTR-018 Metas de ahorro | Hecho |
| RF-10 | MM-37 · FTR-019 Goal Forecast | Hecho |
| RF-11 a RF-19 | MM-35 · FTR-010 Can I Afford It? | Hecho |
| RF-20 y RF-21 | Bugs de QA: aportes y retiros con cuenta | Hecho |
| RF-5 y RF-7 | Bugs de QA 2026-10-30: reabrir al bajar y no borrar con saldo | Hecho |
| RF-7 (cambio) | BUG-049: el aporte no pasa lo que falta | Hecho: migración 0024 |

## Decisiones
- Bug de QA (BUG-030, migración 0021): dos metas vivas del usuario no se llaman igual, sin distinguir mayúsculas (`409 goal_name_taken`). Es un trigger y no un índice único, para no fallar con los repetidos que ya existen.
- `priority` es un entero de 1 (la más alta) a 5, como el CHECK de `goals.goals`. Por defecto 3.
- El aporte lleva `contributed_on` en vez de `date`, como `occurred_on` en los movimientos.
- `DELETE` es un borrado lógico: la meta y sus aportes dejan de contar en Safe to Spend y en los reportes.
- La base marca la meta como cumplida al llegar al objetivo, por un aporte o al bajar el objetivo (migración 0007). Desde la migración 0022, un retiro o un objetivo más alto que la deje por debajo la reabre como activa.
- Pedido de QA (2026-10-30): una meta con saldo no se borra; `DELETE` responde 409 `goal_has_saved` y la app ofrece retirar el saldo a una cuenta (migración 0022). El límite de metas activas no bloquea la reapertura: el retiro nunca se impide.
- El límite de metas activas del plan (`goals.active`) es un dato de `billing.plan_features`; la migración 0007 lo aplica: `409 plan_limit`. Desde la migración 0028 ningún plan lo tiene (pedido del 2026-11-05).
- `progress_percent` es un entero de 0 a 100, redondeado hacia abajo.
- `estimated_completion` (RF-10) es hoy en la zona del usuario más los meses que faltan, redondeados hacia arriba. El promedio usa los meses con aporte, como dicen los casos límite. Sin aportes, o si la meta no está activa, `null`.
- Can I Afford It? reusa el motor de Safe to Spend de finance y el Financial Forecast de planning: la fórmula de Safe to Spend sigue en un solo lugar y los ingresos, gastos y gasto variable salen del mismo lector.
- El dinero disponible para la compra es el Safe to Spend más los ingresos recurrentes que faltan llegar en el periodo, menos el gasto variable promedio prorrateado por los días que quedan. Los ingresos que vencen hoy cuentan; los vencimientos anteriores a hoy no, para no sumar dos veces un sueldo que ya se cobró sin marcar el recurrente.
- `goal_impacts` es información, no una forma de pagar: dice de dónde saldría lo que falta si se usaran los aportes del periodo y cuánto se atrasaría cada meta. Se informa de la menor prioridad a la mayor y cada una como máximo en lo aportado en el periodo.
- `delay_months` es la fecha estimada de RF-10 con lo informado sumado a lo que falta, menos la de hoy.
- El sobrante mensual es el promedio de ingresos menos gastos recurrentes de los próximos 12 meses, menos el gasto variable promedio, los aportes mensuales promedio a metas y el ahorro planificado. Antes eran los próximos 30 días y un gasto anual quedaba afuera (decisión del 2026-10-31: se maneja mensual, no por el periodo del usuario).
- `estimated_on` y `projection` (RF-14) salen de la misma simulación día a día: arranca en el disponible (que ya cuenta todo hasta el fin del periodo, así no se cuenta dos veces el sueldo del periodo), suma los recurrentes en sus fechas y resta variable, metas y ahorro planificado por día. La fecha es el día en que alcanza; la curva, un punto por mes y el último en esa fecha (reemplaza al punto mensual de su mes), siempre en el precio o más. Tope de 5 años (60 puntos). La app no recalcula nada.
- El ahorro planificado se prorratea a 30 días según el periodo del usuario (semanal, quincenal o mensual). Cierra la duda que quedaba abierta.
- Pedido de QA (2026-10-30): el veredicto deja de ser tres y pasa a ser "alcanza" o "todavía no"; las metas se muestran solo como información. Cambia el PRD §6.13.
- `category_id` se valida (tiene que ser de gasto) pero no cambia el cálculo: el presupuesto por categoría está fuera de la V1.
- Pedido de QA (2026-10-29): el aporte sale de una cuenta y el retiro vuelve a una. Se guarda `account_id` en el aporte y un trigger ajusta el saldo (migración 0018); no se crea un movimiento, porque ahorrar no es un gasto ni retirar un ingreso, y los reportes ya muestran las metas aparte. `account_id` es opcional en la API para los clientes viejos; la app siempre lo pide.

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿Se puede pausar o archivar una meta desde la API? Hoy `status` no se edita.
- [NECESITA ACLARACIÓN] ¿`priority` es un entero del 1 al 5, un orden manual o un enumerado de alta, media y baja?
- [NECESITA ACLARACIÓN] ¿`POST /v1/affordability-checks` debería registrar la consulta en `ops.log()` para medir uso, o se deja sin rastro por privacidad?
