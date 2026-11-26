# Spec 014 — Foto del comprobante de un gasto (API)

## Contexto y objetivo
El usuario puede adjuntar la foto del comprobante (ticket, factura o recibo) a un gasto y verla después, desde la app o la web. Es lo que pidió producto en las observaciones del 2026-11-05 ("en gastos subir una foto del comprobante"). Solo guarda la imagen: leerla con IA es FTR-030 (escaneo de facturas), que queda aparte. Tablas: `finance.transaction_receipts`; las imágenes, en el S3 propio (servicio `receipts` del docker-compose, con SeaweedFS).

## Usuarios / actores
- Usuario autenticado desde la app o la web.

## Historias de usuario
- H1: Como usuario quiero sacarle una foto al ticket o elegirla de la galería y dejarla con el gasto.
- H2: Como usuario quiero ver la foto cuando reviso el gasto, cambiarla o quitarla.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `PUT /v1/transactions/{id}/receipt` con la imagen en el cuerpo, EL SISTEMA la guarda para ese gasto y responde 204. Una por gasto: otra reemplaza la anterior. SI el movimiento no es un gasto, está borrado, no existe o es de otro usuario, ENTONCES responde 404 `not_found` y no guarda nada.
- RF-2: EL SISTEMA acepta solo JPEG, PNG o WebP de 1 byte a 5 MB, y reconoce el tipo por los primeros bytes, no por el `Content-Type`. SI no cumple, ENTONCES responde 422 `invalid_receipt`.
- RF-3: CUANDO llega `GET /v1/transactions/{id}/receipt`, EL SISTEMA responde 200 con la imagen, su tipo y `Cache-Control: private, no-store`. Sin foto o con el gasto borrado: 404 `not_found`.
- RF-4: CUANDO llega `DELETE /v1/transactions/{id}/receipt`, EL SISTEMA borra la fila y la imagen y responde 204. Sin foto: 404 `not_found`.
- RF-5: `GET /v1/transactions` trae `has_receipt` en cada movimiento.
- RF-6: Toda consulta corre con `app.user_id` (RLS): la foto de otro usuario responde 404, nunca 403.

## Requisitos no funcionales
- Seguridad: el S3 solo está en la red interna del compose; la API sube y sirve cada foto con el token del usuario. En dev se publica en `127.0.0.1:9000`. Fuera de dev, ni la API ni `migrate` arrancan con la clave de desarrollo.
- Privacidad: las fotos no van a logs, analítica ni proveedores externos.
- Respaldo: el volumen `receipts` se respalda junto con `pgdata`.

## Criterios de finalización
- RF-1 a RF-6 con pruebas en `tests/integration/test_finance_receipts.py` (el S3 se cambia por uno en memoria).
- Probado a mano contra el servicio `receipts` real: subir, leer, borrar y clave incorrecta rechazada.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-6 | Observaciones de producto 2026-11-05 (punto 2) | Hecho |

## Decisiones
- 2026-11-05: el equipo eligió un S3 propio en el docker-compose. MinIO ya no publica imágenes de Docker, así que se usa SeaweedFS 4.50, que habla el mismo S3; la API usa el cliente `minio`, que sirve para cualquier S3.
- La foto pasa por la API (no URLs firmadas como dice el PRD §9 para Cloud Storage): así el S3 no sale a internet.
- Solo gastos, como lo pidió producto. Un borrado lógico deja la imagen; se va con el borrado definitivo del usuario.

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿Límite de fotos por plan? Hoy no cuenta en `billing`.
- [NECESITA ACLARACIÓN] Las imágenes de gastos borrados se quedan en el S3 hasta que se borre el usuario. ¿Hace falta una limpieza periódica?
