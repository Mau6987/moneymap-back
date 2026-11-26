# Spec 012 — Registro por voz con IA (API)

## Contexto y objetivo
El usuario dicta lo que gastó o recibió ("gasté 50 en comida con la Visa") o lo escribe, y la API le devuelve el movimiento prellenado para que lo confirme. Son dos pasos, cada uno con un modelo principal y uno de respaldo, todos propios (PRD 1.5.3, §6.7): voz a texto en el servicio `stt` (Parakeet y Whisper) y extracción del movimiento en Ollama (Qwen 3.5 4B y Gemma 3 4B), los dos en `docker-compose.ai.yml`. Corresponde a FTR-007 (MM-40, MM-56 y MM-57). Tablas: `ai.voice_entries`, `ai.calls`, `ai.routes`, `ai.models`, `billing.usage_counters`.

## Usuarios / actores
- Usuario autenticado desde la app.
- Worker de Celery: transcribe y extrae fuera de la petición.
- Servicios `stt` y `llm` (Ollama), solo en la red interna.

## Historias de usuario
- H1: Como usuario quiero dictar un gasto y verlo prellenado para confirmarlo con un toque.
- H2: Como usuario quiero escribir la frase en lugar de dictarla.
- H3: Como usuario quiero que, si la IA falla, no pierda el registro ni gaste mi cuota.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `POST /v1/voice-entries` con el audio en el cuerpo (`Content-Type: audio/*`, hasta 2 MB y 60 s), EL SISTEMA crea el dictado en `received`, encola su proceso y responde 202 con el `id`. SI la cola no lo acepta, ENTONCES deja el dictado en `failed`, devuelve la cuota y responde 503 `voice_queue_unavailable`.
- RF-2: CUANDO llega `POST /v1/voice-entries/text` con `{"text": "…"}` (1 a 500 caracteres), EL SISTEMA crea el dictado con `input_type = 'text'` y la frase como transcripción, encola solo la extracción y responde 202.
- RF-3: Cada dictado descuenta uno de la cuota mensual `ai.voice_entries` del plan (`billing.try_consume`); sin cuota, EL SISTEMA responde 409 `plan_limit` y no crea nada.
- RF-4: EL WORKER transcribe con los modelos de `ai.route('voice.transcribe')` en orden: si uno no responde a tiempo, devuelve error o texto vacío, reintenta según `max_retries` y pasa al siguiente. Cada intento queda en `ai.calls`.
- RF-5: EL WORKER extrae con `ai.route('voice.extract')` de la misma forma. Al LLM van solo la frase, la fecha de hoy del usuario y los nombres de sus categorías (separadas en gasto e ingreso), cuentas activas y monedas; nunca ids, saldos ni historial. El modelo responde con nombres y el worker los cambia por los ids.
- RF-6: La extracción trae `kind` (`income` o `expense`), `amount`, `currency`, `category_id`, `account_id`, `description`, `occurred_on` `missing` (los datos que la frase no dice o de los que el modelo no está seguro) y `multiple`. Si la frase tiene varios movimientos (hasta cinco), vienen todos en `movements`, cada uno con sus campos y su `missing`, y arriba el primero (decisión de producto del 2026-10-25: reemplaza "una frase, un movimiento" del PRD §6.7). Al modelo le van las fechas ya calculadas (hoy, ayer, anteayer y los últimos siete días por nombre) y el monto se lee como se escribe en Bolivia ("1.250,50" es 1250.50). Un id que no es del usuario se descarta y el campo pasa a `missing`. Una salida que no cumple el esquema cuenta como `invalid_output` y se prueba el siguiente modelo.
- RF-7: SI fallan todos los modelos de un paso, ENTONCES EL SISTEMA deja el dictado en `failed`, devuelve el uso de la cuota (`billing.release`) y escribe `ops.log`. SI el worker sufre un error inesperado, también lo deja en `failed` (`voice.unexpected`) y devuelve la cuota. Una tarea de limpieza cada 5 minutos cierra como `voice.stale` los dictados que llevan más de 15 minutos en `received` o `transcribed`.
- RF-8: CUANDO llega `GET /v1/voice-entries/{id}`, EL SISTEMA responde el estado (`received`, `transcribed`, `extracted`, `confirmed`, `discarded` o `failed`), la transcripción y la extracción.
- RF-9: CUANDO llega `POST /v1/voice-entries/{id}/confirm` con el `transaction_id` que la app creó con `POST /v1/transactions` (`source: "voice"`), EL SISTEMA lo enlaza y pasa el dictado a `confirmed`. `POST /v1/voice-entries/{id}/discard` lo pasa a `discarded`.
- RF-10: El audio no se guarda: la API lo deja en una carpeta en memoria (tmpfs) que comparte con el worker, y el worker lo borra al leerlo. No viaja en la cola de Redis, que se guarda en disco. Si el audio se pierde (reinicio), el dictado queda en `failed` y se devuelve la cuota.
- RF-11: Toda consulta de la API corre con `set_config('app.user_id', …)`; el dictado de otro usuario responde 404. El worker usa su propio usuario de base (`moneymap_worker_login`), el único con permiso para leer las rutas y escribir `ai.calls`.

## Requisitos no funcionales
- Latencia: de punta a punta, p95 menor a 10 s en el VPS con CPU.
- Los modelos y su orden se cambian con `ai.set_route_order`, sin desplegar.

## Criterios de finalización
- Cada RF tiene al menos un test automático (los servicios `stt` y `llm` se simulan).
- `docs/api.md` al día.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-11 | MM-40 · FTR-007 (MM-56, MM-57) | Hecho; falta medir con 50 frases reales |
| RF-1 y RF-7 (QA BUG-047) | Cola/worker robustos y limpieza de dictados viejos | Hecho |

## Decisiones
- Pedido del 2026-10-31: el plan gratuito ya no incluye el registro por voz (migración 0023: `ai.voice_entries` apagado en `free`, `409 plan_limit`). Los planes de pago siguen sin límite.
- BUG-047: `discard` acepta un dictado que todavía se procesa (la app lo cancela) y el worker ya no lo pisa. La cuota no se devuelve.

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿La frase escrita (RF-2) descuenta de la misma cuota que el dictado? Hoy sí.
- [NECESITA ACLARACIÓN] ¿Cuánto se guardan las transcripciones? El PRD pide retención limitada; propuesta: 90 días.
