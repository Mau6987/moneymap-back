# Spec 011 — Planes y plan propio (API)

## Contexto y objetivo
La pantalla "Planes" muestra el plan gratuito y el Premium con sus precios y límites, y cuánto lleva usado el usuario de su plan. Sección 6.2 del PRD 1.5. Sin cobros todavía: toda cuenta empieza en el gratuito y elige su plan con `PUT /v1/me/plan` (MM-186). La compra en App Store y Play Store llega con su propia spec.

El precio y los límites del plan de pago **están por definir**. La migración 0011 cargó datos de ejemplo para que la pantalla tenga qué mostrar; cambiarlos es un UPDATE en `billing.plans`, `billing.plan_prices` y `billing.plan_features`.

## Usuarios / actores
- Usuario autenticado desde la app.

## Historias de usuario
- H1: Como usuario quiero comparar los planes para elegir uno.
- H2: Como usuario quiero saber cuánto me queda de mi plan antes de chocar con un límite.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `GET /v1/plans`, EL SISTEMA responde los planes públicos y activos, del gratuito al más alto, cada uno con sus precios mensual y anual por moneda y el valor de cada funcionalidad.
- RF-2: CUANDO llega `GET /v1/me/plan`, EL SISTEMA responde el plan efectivo del usuario (el gratuito si no tiene suscripción vigente), el estado de la suscripción y, por funcionalidad, el límite y cuánto lleva usado.
- RF-3: Un precio sin producto en App Store ni en Play Store se responde con `purchasable: false`.
- RF-4: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`.
- RF-5 (MM-186): CUANDO llega `PUT /v1/me/plan` con un plan público y activo, EL SISTEMA deja al usuario en ese plan al instante y sin cobro (suscripción `internal`; el gratuito termina la suscripción). Al bajar, lo que ya existe queda y los límites impiden crear más. Un plan que no existe responde 404; una suscripción de tienda, 409 `plan_managed_by_store`.
- RF-6 (MM-186): Mis monedas respeta `finance.currencies` y cada consulta de Can I Afford It? cuenta contra `planning.affordability_checks`; al pasarse, 409 `plan_limit` con la `feature`.

## Requisitos no funcionales
- Rendimiento: p95 menor a 300 ms.

## Criterios de finalización
- Cada RF tiene al menos un test automático.
- `docs/api.md` al día.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-4 | Planes SaaS (PRD §6.2, sin ID) | Hecho, con datos provisionales |
| RF-5, RF-6 | MM-186 | Hecho |

## Decisiones
- Pedido del 2026-10-31: el registro por voz sale del plan gratuito (migración 0023). El administrador puede volver a prenderlo desde el panel.
- Pedido del 2026-11-05 (migración 0028): solo quedan Gratuito y Premium (`paid_3`), y las metas activas no tienen límite en el gratuito. Plus (`paid_1`) y Pro (`paid_2`) quedan inactivos, sin borrarse, y sus suscripciones vigentes pasan a Premium. `tier` no se renumera: Premium sigue en 3.

## Dudas abiertas
- [NECESITA ACLARACIÓN] Precio y límites reales del plan de pago. Provisional: Premium (Bs 79 al mes y Bs 790 al año; sin límites).
- [NECESITA ACLARACIÓN] ¿Se cobra en bolivianos, en dólares o en los dos? Las tiendas cobran en la moneda local del usuario.
