# Spec 009 — Presupuestos, Spending Pace y What If? (API)

## Contexto y objetivo
El usuario pone un límite mensual a una categoría de gasto y ve cuánto lleva, cuánto le queda y a qué ritmo va. Además puede simular un cambio antes de hacerlo (What If?) sin tocar sus datos. Corresponde a FTR-014, FTR-015 y FTR-011, y a las secciones 6.16, 6.17 y 6.19 del PRD 1.5, que las incluye en la V1. Tablas: `planning.budgets` (migración 0010). What If? no guarda nada.

## Usuarios / actores
- Usuario autenticado desde la app.
- Worker de Celery Beat: encola los avisos de presupuesto.

## Historias de usuario
- H1: Como usuario quiero ponerle un límite al mes a una categoría y ver cuánto llevo.
- H2: Como usuario quiero saber si voy gastando más rápido de lo que va el mes.
- H3: Como usuario quiero que me avisen al llegar al 80 % y al pasarme.
- H4: Como usuario quiero ver qué pasa con mi Safe to Spend y mis metas si cambia mi ingreso, sumo un gasto fijo o cambio lo que ahorro.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `POST /v1/budgets` con una categoría de gasto y un monto, EL SISTEMA crea el presupuesto en la moneda pedida o, sin ella, en la principal, y responde 201.
- RF-2: CUANDO llega `PATCH /v1/budgets/{id}` o `DELETE /v1/budgets/{id}`, EL SISTEMA corrige el monto o borra el presupuesto; el ajeno o borrado responde 404.
- RF-3: CUANDO llega `GET /v1/budgets`, EL SISTEMA responde cada presupuesto con lo gastado en el mes en curso, lo que queda y el porcentaje usado.
- RF-4: EL SISTEMA solo suma los gastos de la categoría en la moneda del presupuesto, sin conversión.
- RF-5: Al empezar un mes, lo gastado vuelve a cero con el mismo monto; lo no gastado no se acumula.
- RF-6: EL SISTEMA calcula el Spending Pace: ritmo = gastado ÷ presupuesto − días transcurridos ÷ días del mes; En ritmo si ritmo ≤ 0, Un poco rápido hasta 10 puntos, Muy rápido más de 10; y la proyección al cierre = gastado ÷ días transcurridos × días del mes.
- RF-7: MIENTRAS sean los primeros 3 días del mes, EL SISTEMA no da estado de ritmo.
- RF-8: SI el usuario ya tiene los presupuestos que permite su plan (3 en el gratuito, provisional), ENTONCES EL SISTEMA responde 409 `plan_limit`.
- RF-9: SI la categoría se borra, ENTONCES EL SISTEMA borra sus presupuestos; en una categoría borrada o ajena no se crea (404), y en una de ingreso responde 422.
- RF-10: CUANDO lo gastado llega al 80 % de un presupuesto, EL SISTEMA encola el aviso `budget.threshold`; al pasar el 100 %, `budget.exceeded`. Cada uno una sola vez por presupuesto y mes.
- RF-11: MIENTRAS el modo privado esté activo, los avisos de presupuesto no llevan montos ni nombres de categorías.
- RF-12: CUANDO llega `POST /v1/what-if` con uno o dos cambios, EL SISTEMA responde Safe to Spend, el Forecast a 30, 60 y 90 días (spec 010) y la fecha estimada de cada meta, antes y después, sin guardar ni cambiar nada.
- RF-13: Los cambios posibles son: ingreso mensual (sube o baja), gasto recurrente mensual (se agrega o se quita), aporte mensual a una meta y ahorro planificado del periodo.
- RF-14: SI después del cambio Safe to Spend queda negativo, ENTONCES EL SISTEMA saca lo que falta de los aportes a metas, primero de la de menor prioridad, y muestra cuántos meses se atrasa cada una.
- RF-15: EL SISTEMA devuelve los supuestos usados y nunca decide por el usuario.
- RF-16: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`.
- RF-17: CUANDO llega `GET /v1/budgets`, EL SISTEMA devuelve también el gasto de cada día del mes con gasto, y lo acumulado hasta ese día, para dibujar la línea real.
- RF-18: EL SISTEMA guarda por presupuesto si avisa al 80 % y si avisa al 100 %, los dos encendidos por defecto; SI uno está apagado, ENTONCES no encola ese aviso de ese presupuesto.
- RF-19: What If? acepta también "gasto en categoría": cuánto más o menos se gasta por mes en una categoría de gasto. Mueve Safe to Spend y el Forecast igual que un gasto fijo.
- RF-20: CUANDO llega `GET /v1/what-if/baseline`, EL SISTEMA usa el periodo del tipo pedido (`weekly`, `semi_monthly` o `monthly`) que contiene `on` o el hoy del usuario; sin tipo, el que configuró. Con su tipo, empieza en su día de inicio; con otro, el día 1 o el lunes.
- RF-21: EL SISTEMA responde lo que entró y salió por categoría en ese periodo y moneda, de mayor a menor, sin transferencias ni borrados; con `account_id`, solo esa cuenta (una ajena o de otra moneda: 404).
- RF-22: EL SISTEMA responde las metas activas de la moneda con su aporte mensual promedio y ese ritmo pasado al periodo, para simular qué pasa si se aporta más, menos o nada.
- RF-23: La base del simulador no guarda nada; los cambios de los sliders los calcula el cliente.

## Requisitos no funcionales
- Rendimiento: p95 menor a 300 ms en `GET /v1/budgets` y `POST /v1/what-if`.
- Privacidad: What If? no se guarda ni llega a un LLM.
- Costo: ninguna de las dos llama a IA.

## Casos límite
- Un gasto de 10 USD en Comida no suma al presupuesto de Comida en Bs (RF-4).
- Dos presupuestos para la misma categoría y moneda: 409 `budget_exists`.
- Un presupuesto en USD y otro en Bs para la misma categoría: se permiten.
- Pasarse del presupuesto: `remaining` negativo y `percent_used` mayor que 100.
- Un movimiento que cambia de categoría o se borra: el gasto se recalcula en la próxima consulta.
- What If? con una meta de otra moneda o ajena: 404.
- What If? con más de 2 cambios: 422.
- La base del simulador con una semana distinta a la configurada: empieza el lunes (RF-20).
- Una meta sin aportes: `monthly_contribution` en null y `period_contribution` en 0 (RF-22).

## Fuera de alcance
- Guardar escenarios de What If? (V1.1, PRD §11).
- Historial de montos de un presupuesto: corregirlo vale desde el mes en curso.

## Criterios de finalización
- Cada RF tiene al menos un test automático.
- `docs/api.md` y `openapi.json` al día; `db/DICCIONARIO_CAMPOS.md` y `smoke_test.sql` con la tabla nueva.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-9 | MM-59 · FTR-014 y MM-60 · FTR-015 | Hecho |
| RF-10 y RF-11 | MM-59 · FTR-014 (avisos, FTR-023) | Hecho: encolados cada hora; se envían cuando exista el envío por FCM y APNs (spec 006) |
| RF-12 a RF-16 | MM-61 · FTR-011 What If? | Hecho, con el Forecast de la spec 010 |
| RF-19 | MM-61 · FTR-011 What If? | Hecho |
| RF-17 y RF-18 | MM-59 · FTR-014 | Hecho |
| RF-20 a RF-23 | What If? con sliders (web) | Hecho: `GET /v1/what-if/baseline` |

## Dudas abiertas
- Decidido: el PRD 1.5 incluye presupuestos, Spending Pace y What If? en la V1. La constitución y los AGENTS.md los daban como fuera; se corrigieron.
- Decidido: el periodo del presupuesto es el mes calendario en la zona horaria del usuario, no el periodo de cobro de Safe to Spend.
- Decidido: de `db/future/110_budgets.sql` quedan fuera `starts_on`, `ends_on`, `rollover` y `alert_threshold`; el PRD fija la repetición mensual, sin acumular, y los umbrales en 80 y 100 %.
- Decidido: Spending Pace no tiene endpoint propio; va dentro de cada presupuesto en `GET /v1/budgets`.
- Decidido por ahora: 3 presupuestos en el plan gratuito (PRD §6.2). Es un dato en `billing.plan_features`: cambiarlo no necesita código.
- Decidido: What If? usa el Forecast de la spec 010. El ingreso y los gastos fijos cambian lo que entra a las cuentas; el ahorro planificado no cambia el saldo, solo Safe to Spend.
- [NECESITA ACLARACIÓN] El PRD §6.2 pone a Can I Afford It? y What If? bajo un mismo cupo de 10 consultas al mes en el gratuito, pero hoy Can I Afford It? no consume ese cupo. ¿Se empieza a cobrar a las dos?
- [NECESITA ACLARACIÓN] La base del simulador (RF-20) usa el día 1 o el lunes cuando el tipo pedido no es el configurado. ¿Debería tomar otro día de inicio, por ejemplo el del cobro?
