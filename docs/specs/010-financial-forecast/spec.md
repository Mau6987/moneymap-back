# Spec 010 — Financial Forecast a 30, 60 y 90 días (API)

## Contexto y objetivo
Proyecta el saldo del usuario en una moneda a 30, 60 y 90 días con el motor financiero, como una estimación y nunca como una recomendación. Corresponde a FTR-020 y a la sección 6.18 del PRD 1.5. What If? (spec 009) lo usa para mostrar el antes y el después. No guarda nada ni agrega tablas.

## Usuarios / actores
- Usuario autenticado desde la app.

## Historias de usuario
- H1: Como usuario quiero saber cómo va a estar mi saldo en uno, dos y tres meses.
- H2: Como usuario quiero saber si en algún momento me quedaría en negativo y cuándo.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `GET /v1/forecast?currency=`, EL SISTEMA responde el saldo proyectado a 30, 60 y 90 días en la moneda pedida o, sin ella, en la principal.
- RF-2: EL SISTEMA calcula saldo proyectado = saldo actual + ingresos recurrentes esperados − gastos recurrentes esperados − aportes a metas − gasto variable promedio. Los recurrentes cuentan en su fecha; uno vencido y pendiente cuenta hoy.
- RF-3: El gasto variable promedio sale de los gastos que no vienen de un recurrente, en los últimos 3 meses completos con movimientos, o de los que existan.
- RF-4: SI el saldo proyectado baja de 0 dentro de los 90 días, ENTONCES EL SISTEMA responde la fecha aproximada en `goes_negative_on`.
- RF-8: Cada punto de 30, 60 y 90 días trae lo acumulado desde hoy hasta ese día: ingresos recurrentes, gastos recurrentes, aportes a metas y gasto variable.
- RF-5: EL SISTEMA devuelve los supuestos del cálculo: ingresos y gastos recurrentes de los próximos 30 días, aportes a metas por mes, gasto variable por mes y meses de historial usados.
- RF-6: MIENTRAS el usuario tenga menos de un mes completo de datos, EL SISTEMA responde `limited_history: true` y usa lo que va del mes, llevado a 30 días.
- RF-7: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`.

## Requisitos no funcionales
- Rendimiento: p95 menor a 300 ms.
- Costo: no llama a IA.

## Casos límite
- Una meta deja de restar cuando llega a su objetivo.
- Un recurrente con `end_date` deja de contar después de esa fecha.
- Sin cuentas en esa moneda: saldo 0 y proyección con los recurrentes y el gasto variable de esa moneda.

## Criterios de finalización
- Cada RF tiene al menos un test automático, incluido el criterio del PRD §6.18: saldo 2.500, ingreso de 3.000, recurrentes de 700, aportes de 300 y gasto variable de 1.500 dan 3.000 a 30 días.
- `docs/api.md` al día.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-8 | FTR-020 Financial Forecast (sin ticket propio en Jira) | Hecho |

## Decisiones
- Pedido de QA (2026-10-30): un ingreso recurrente vencido que no se marcó recibido no suma en la proyección; sumarlo como si llegara hoy la inflaba. Un gasto vencido sí cuenta hoy. Los pagos de gastos fijos no entran en el gasto variable promedio, porque ya están en los recurrentes.

## Dudas abiertas
- Decidido: los meses son de 30 días y el gasto variable y los aportes se reparten por día; así 30 días son un mes del PRD.
- Decidido: el saldo actual es la suma de las cuentas, como en Safe to Spend; los aportes a metas restan porque el dinero se aparta.
- Decidido: el ahorro planificado no resta: no sale de las cuentas.
- [NECESITA ACLARACIÓN] FTR-020 no tiene ficha en Jira. ¿Se crea, o se registra dentro de MM-61 (What If?)?
