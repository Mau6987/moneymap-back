# Spec 006 — Money Story y notificaciones (API)

## Contexto y objetivo
La API genera el resumen de cierre de mes y reparte los avisos push de la V1. La Money Story se arma al cerrar el mes con los totales y la comparación contra el mes anterior, con textos de plantillas almacenadas como dato y sin IA. Los avisos salen hacia los dispositivos registrados y respetan lo que el usuario haya apagado. Corresponde a FTR-022 y FTR-023 y a las secciones 6.14 y 6.15 del PRD 1.5. Tablas: `reports.money_story`, `notify.devices`, `notify.notification_settings`, `notify.outbox`.

## Usuarios / actores
- Usuario autenticado desde la app.
- Worker de Celery Beat: cierra el mes, arma la Money Story y encola los avisos.
- Worker de Celery: envía los avisos por FCM.
- FCM como proveedor de notificaciones push de iOS y Android.

## Historias de usuario
- H1: Como usuario quiero que la API me entregue el resumen de mi mes.
- H2: Como usuario quiero que la API compare mi mes con el anterior.
- H3: Como usuario quiero registrar mis dispositivos para recibir avisos.
- H4: Como usuario quiero apagar los avisos que no quiero y que respete esa decisión.
- H5: Como usuario quiero que mis avisos no muestren montos si tengo el modo privado activo.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO el trabajador cierra un mes, EL SISTEMA crea la fila de `reports.money_story` de ese periodo y moneda con los totales: ingresos, gastos, ahorro y tasa de ahorro.
- RF-2: CUANDO existe el mes anterior del usuario con datos, EL SISTEMA guarda en la misma fila la comparación: ingresos, mayor categoría de gasto, ahorro y avance de metas.
- RF-3: MIENTRAS el mes cerrado sea el primero del usuario, EL SISTEMA guarda `comparison` en `null` con la marca de primer mes.
- RF-4: EL SISTEMA arma los textos con plantillas almacenadas como dato y reglas, sin llamar a ningún modelo de IA.
- RF-5: CUANDO llega `GET /v1/money-story?period=AAAA-MM&currency=XXX`, EL SISTEMA responde 200 con los totales, la comparación y los textos del periodo pedido.
- RF-6: SI no llega `period`, ENTONCES EL SISTEMA usa el último mes cerrado del usuario.
- RF-7: EL SISTEMA guarda y devuelve una Money Story por moneda con movimientos, y nunca una que sume monedas distintas.
- RF-8: CUANDO llega `POST /v1/me/devices` con el token push y la plataforma, EL SISTEMA registra o reactiva el dispositivo y responde 201.
- RF-9: SI el token push ya existía para otro usuario, ENTONCES EL SISTEMA lo reasigna al usuario actual y desactiva la fila anterior.
- RF-10: CUANDO llega `DELETE /v1/me/devices/{id}`, EL SISTEMA desactiva el dispositivo y deja de enviarle avisos.
- RF-11: CUANDO llega `GET /v1/me/notification-settings` o `PUT /v1/me/notification-settings`, EL SISTEMA lee o actualiza los tipos de aviso activos del usuario.
- RF-12: SI un tipo de aviso no existe, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-13: EL SISTEMA guarda en la cola de salida un aviso por cada dispositivo activo del usuario cuyos ajustes permitan ese tipo de aviso.
- RF-14: MIENTRAS el usuario tenga el modo privado activo, EL SISTEMA arma el texto del aviso sin montos ni nombres de categorías.
- RF-15: EL SISTEMA envía el aviso del día anterior al próximo pago de un gasto recurrente, y agrupa en uno solo los que caen el mismo día.
- RF-16: EL SISTEMA envía un aviso por cada hito de avance de una meta, y no repite el mismo hito para la misma meta.
- RF-17: EL SISTEMA envía el aviso de Money Story cuando la fila del mes queda lista.
- RF-18: SI FCM rechaza un token por inválido o desinstalado, ENTONCES EL SISTEMA desactiva ese dispositivo y escribe `ops.log('warning', 'notify', …)`.
- RF-19: SI un envío falla, ENTONCES EL SISTEMA reintenta con espera creciente y descarta el aviso tras el máximo de intentos, sin bloquear la cola.
- RF-20: EL SISTEMA no genera avisos de resumen semanal: no es de la V1. Los de presupuestos son de la spec 009 (RF-10 y RF-11).
- RF-21: Toda consulta corre en una transacción que empieza con `SELECT set_config('app.user_id', :uid, true)`; el dispositivo de otro usuario responde 404 y no 403.
- RF-22: CUANDO llega `GET /v1/me/notifications`, EL SISTEMA responde los avisos guardados del usuario, del más nuevo al más viejo y por páginas, con cuántos no leyó.
- RF-23: CUANDO llega `POST /v1/me/notifications/read`, EL SISTEMA marca como leídos todos los avisos sin leer del usuario.

## Requisitos no funcionales
- Idempotencia: el cierre de mes es idempotente por usuario, periodo y moneda; volver a correrlo no duplica la historia.
- Entrega: los avisos salen dentro de los 5 minutos siguientes al evento que los dispara.
- Privacidad: ningún aviso lleva montos, saldos ni nombres de categorías si el modo privado está activo. Esto resuelve la duda abierta de la spec 001.
- Rendimiento: p95 menor a 300 ms en `GET /v1/money-story`; el envío de avisos no bloquea ninguna petición de usuario.
- Seguridad: los tokens push se guardan en su propia tabla y no aparecen en logs.
- Costo: el cierre de mes no llama a ningún modelo de IA, así que no consume presupuesto de IA.

## Casos límite
- Primer mes del usuario: `comparison` en `null` (RF-3).
- Mes sin movimientos: no se genera historia ni aviso.
- Dos dispositivos del mismo usuario con un tipo de aviso apagado: no llega a ninguno.
- El mismo token push en dos cuentas: queda en la última que lo registró (RF-9).
- Varios recurrentes con la próxima fecha el mismo día: un solo aviso agrupado (RF-15).
- Hito de meta ya avisado: no se repite (RF-16).
- Modo privado activo: los textos van sin montos (RF-14).
- El usuario apaga todos los tipos de aviso: la historia se sigue generando y se puede pedir por la API.
- El mes cierra en la zona horaria del usuario, no en UTC.
- Una moneda se desactiva en el catálogo entre el cierre y la consulta: la historia guardada se sigue devolviendo.
- El worker se cae a mitad del cierre: al reintentar no duplica la historia (idempotencia).

## Fuera de alcance
- Weekly Money Check-in (FTR-021) y su aviso.
- Alertas de presupuesto y de Spending Pace (FTR-014, FTR-015).
- Textos generados con IA.
- Correo electrónico, SMS o notificaciones dentro de la app.
- Financial Insights y Financial Leaks.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- El cierre de mes genera la historia con los totales y, desde el segundo mes, la comparación.
- Un tipo de aviso apagado no genera filas en la cola de salida para ese usuario.
- Un token inválido de FCM desactiva el dispositivo y queda en `ops.log()`.
- Con el modo privado activo, ningún texto de aviso contiene montos.
- `openapi.json` regenerado; los esquemas de notificaciones no exponen tokens push.
- `db/tests/smoke_test.sql` en verde, con las pruebas de Money Story y de ajustes de aviso.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-7 | MM-38 · FTR-022 Monthly Money Story | Hecho |
| RF-8 a RF-23 | MM-39 · FTR-023 Notificaciones orientadas a acción | En curso: RF-8 a RF-17 y RF-20 a RF-23 hechos. Falta el envío por FCM y APNs (RF-18, RF-19) |

## Dudas abiertas
- Decidido: una Money Story por moneda con movimientos en el mes (RF-7), la principal primero.
- Decidido: el mes es el calendario, no el periodo de cobro de Safe to Spend. El cierre corre todos los días a las 05:30 UTC y cierra el mes de cada persona cuando ya pasó en su zona horaria; un movimiento del mes cerrado que se registra después del cierre no cambia la historia.
- Las tablas reales son `iam.devices` (sin RLS: la API filtra por `user_id`), `notify.preferences` y `notify.notifications`, no las que nombra el contexto.
- Decidido: la cola guarda un aviso por persona, no por dispositivo (RF-13): quien envía lo reparte entre los dispositivos activos al momento de enviar. Solo se encola si el tipo está encendido. Desde 2026-10-22 también se guarda sin dispositivo, como `skipped`, para que la pantalla Avisos lo muestre (RF-22); el envío solo toma los `queued`.
- Decidido: el aviso de recurrentes respeta `remind_days_before` de cada recurrente (por defecto 1, el "día anterior" de RF-15), solo para gastos, y sale a las 13:00 UTC (09:00 en Bolivia). Con el modo privado tampoco lleva las descripciones.
- Pedido del 2026-10-30: también avisa el mismo día que vence ("Tienes un pago recurrente hoy"), con su propia `dedupe_key` (`recurring:<fecha>:today`), para que el aviso del día anterior no lo frene.
- Decidido: el envío habla directo con FCM (Android) y APNs (iOS), sin intermediarios. Queda pendiente hasta tener las credenciales.
- Decidido: `comparison` es `null` si el mes anterior no tuvo movimientos en esa moneda, aunque el usuario tenga meses más viejos (RF-3).
- Decidido (propuesta, a confirmar): los hitos de RF-16 son el 25, 50 y 75 % del objetivo (`goal.milestone`) y la meta cumplida (`goal.achieved`). Corre cada hora; si un aporte salta varios hitos, avisa solo el más alto. Una meta cumplida avisa si se cumplió en la última semana. Con el modo privado no lleva el nombre de la meta.
- [NECESITA ACLARACIÓN] ¿El aviso de cierre de mes se envía al pasar la medianoche del último día o en la corrida nocturna del día 1?
- [NECESITA ACLARACIÓN] ¿Hace falta guardar el historial de avisos enviados para el soporte, o alcanza con la cola de salida mientras están pendientes?
