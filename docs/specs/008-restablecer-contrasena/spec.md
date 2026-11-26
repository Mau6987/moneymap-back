# Spec 008 — Restablecer la contraseña (API)

## Contexto y objetivo
Una persona que no se acuerda de su contraseña tiene que poder volver a entrar sin perder nada de lo que registró. Esta spec cubre la API de ese camino: pedir el código, confirmarlo con una contraseña nueva y cerrar las sesiones que quedaron abiertas. Corresponde a FTR-001 y a la sección 6.1 del PRD 1.5; la spec 001 dejó esto afuera con la nota de que va en su propia spec. Tablas: `iam.users`, `iam.auth_identities`, `iam.verification_tokens`, `iam.sessions`.

## Usuarios / actores
- **Persona registrada con correo y contraseña** que no se acuerda de su contraseña.
- **Persona que entró siempre con Google**: no tiene contraseña que restablecer.
- La app MoneyMap como cliente de la API.
- El correo saliente (SMTP, ver `docs/credenciales.md`).

## Historias de usuario
- H1: Como persona que se olvidó la contraseña quiero pedir un código a mi correo para poder entrar de nuevo.
- H2: Como persona quiero poner una contraseña nueva sin que nadie más pueda hacerlo.
- H3: Como persona quiero que, al cambiarla, se cierren las sesiones abiertas en otros dispositivos.
- H4: Como persona quiero que nadie pueda averiguar si tengo cuenta pidiendo restablecimientos.
- H5: Como persona que usa Google quiero que me digan que entre por Google, en vez de dejarme poner una contraseña que no voy a usar.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `POST /v1/auth/password-reset` con `email`, EL SISTEMA responde **202** siempre, tenga o no cuenta ese correo, y no dice nada más.
- RF-2: SI el correo tiene una cuenta con contraseña y activa, ENTONCES EL SISTEMA guarda un código nuevo y lo manda por correo; SI no la tiene, ENTONCES no manda nada.
- RF-3: EL SISTEMA guarda en `iam.verification_tokens` (purpose `password_reset`) **solo el hash** del código, con vencimiento a los **30 minutos** y `used_at` vacío.
- RF-4: SI el usuario ya tenía un código sin usar, ENTONCES EL SISTEMA lo invalida: el código nuevo reemplaza al anterior.
- RF-5: CUANDO llega `POST /v1/auth/password-reset/confirm` con `email`, `code` y `new_password`, y el código es válido, no venció y no se usó, EL SISTEMA guarda la contraseña nueva con argon2id y responde **204**.
- RF-6: SI el código no existe, venció o ya se usó, ENTONCES EL SISTEMA responde **401 `invalid_reset_code`** y no cambia nada.
- RF-7: SI la contraseña nueva no cumple la política (de 8 a 128 caracteres), ENTONCES EL SISTEMA responde **422 `validation_error`** y no cambia nada.
- RF-8: CUANDO la contraseña cambia, EL SISTEMA marca el código como usado y **revoca todas las sesiones de esa persona**, en todos sus dispositivos.
- RF-9: MIENTRAS se pasen **5 intentos fallidos por correo cada 15 minutos**, EL SISTEMA responde **429 `too_many_requests`** con `Retry-After` y no comprueba el código.
- RF-10: SI la cuenta entró siempre con Google y **no tiene contraseña**, ENTONCES EL SISTEMA responde 202 igual, manda un correo que dice que esa cuenta entra con Google y **no** permite ponerle contraseña.
- RF-11: MIENTRAS la cuenta esté `suspended` o `pending_deletion`, EL SISTEMA responde 202 sin mandar nada y sin cambiar nada.
- RF-12: EL SISTEMA no revela en ninguna respuesta, ni en el `detail`, si el correo existe ni si la cuenta usa contraseña o Google.
- RF-13: CUANDO la contraseña cambia, EL SISTEMA escribe `ops.log('info', 'security', 'auth.password.reset', …)` con el usuario, sin el código ni la contraseña.
- RF-14: EL SISTEMA no permite cambiar el correo con este flujo: solo la contraseña de la cuenta de ese correo.
- RF-15: CUANDO llega `POST /v1/auth/password-reset/verify` con `email` y `code`, EL SISTEMA responde **204** si el código es el vigente de esa cuenta y **401 `invalid_reset_code`** si no, **sin gastarlo ni cambiar nada**; cuenta en los mismos 5 intentos de RF-9. Así la app comprueba el código antes de pedir la contraseña nueva.

## Requisitos no funcionales
- **Seguridad:** el código tiene 6 dígitos, es de un solo uso y vive 30 minutos. De la base solo se lee su hash, así que tener acceso de lectura a `iam.verification_tokens` no alcanza para usarlo. Los intentos están limitados por RF-9, que es lo que hace inviable adivinarlo.
- **Privacidad:** el correo del pedido y el código no aparecen en `ops.log()`, ni en Cloud Logging, ni en Sentry (constitución §5).
- **Rendimiento:** p95 menor a 300 ms en las dos rutas; argon2id es lento a propósito y corre una sola vez.
- **Contrato:** las dos rutas documentadas en OpenAPI, y `docs/api.md` actualizado en el mismo PR.
- **Correo:** el código sale por el adaptador que elija `EMAIL_BACKEND`; en dev se escribe en el log de la API.

## Casos límite
- Correo que no existe: 202, sin correo y sin fila.
- Dos pedidos seguidos: el segundo código invalida el primero (RF-4).
- Código correcto pero vencido (más de 30 minutos): 401.
- Código correcto ya usado: 401.
- Código de otro usuario: 401 (el hash incluye el usuario, no son intercambiables).
- Contraseña nueva igual a la anterior: se acepta; no hay historial de contraseñas en la V1.
- Cuenta con Google y con contraseña (se vinculó): se restablece la contraseña y sigue entrando por los dos caminos.
- Persona con sesiones abiertas en tres dispositivos: al cambiar la contraseña, las tres quedan revocadas y tiene que volver a entrar.
- Correo con mayúsculas o espacios: se normaliza, como en el resto de la identidad.
- Sexto intento en 15 minutos: 429, incluso si el código era el correcto.
- La persona cambió la contraseña mientras otra sesión intentaba rotar su refresh token: la rotación falla porque la sesión quedó revocada (RF-18 de la spec 001).

## Fuera de alcance
- Cambiar el correo de la cuenta (va con su propio requisito, hoy sin spec).
- Preguntas de seguridad, segundo factor y códigos de respaldo.
- Historial de contraseñas y su reutilización.
- Avisar por otros canales (SMS, notificaciones dentro de la app).
- Borrar la cuenta: es otro camino, y las tiendas lo piden; queda pendiente.

## Estado de implementación (2026-10-16)

Tests en `tests/integration/test_iam_password_reset.py`.

| RF | Estado | Nota |
|---|---|---|
| RF-1 a RF-4 | Cumplido | 202 sin cuerpo siempre; el código se guarda con argon2id en `iam.verification_tokens` y el nuevo deja sin efecto al anterior. |
| RF-5 a RF-8 | Cumplido | `confirm` cambia la contraseña, quema el código, revoca **todas** las sesiones y deja la traza en `ops.log`. |
| RF-9 | Cumplido | 5 pedidos por correo por hora y 5 intentos de código cada 15 minutos. |
| RF-10 | Cumplido | Una cuenta solo de Google recibe el aviso, no un código. |
| RF-11 | Cumplido | Una cuenta suspendida o a medio borrar se trata como si no existiera. |
| RF-12 y RF-14 | Cumplido | Mismo estado y mismo `detail` para un correo que existe y para uno que no. |
| RF-13 | Cumplido | `ops.log('info', 'security', 'auth.password.reset', …)`, sin el código ni la contraseña. |
| RF-15 | Cumplido | `verify` usa la misma comprobación que `confirm` (`valid_code_owner`) y el mismo límite de intentos; no gasta el código. |

No hizo falta ninguna migración: `iam.verification_tokens` ya existía con su `purpose = 'password_reset'`.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- Pedir el restablecimiento de un correo que no existe responde **exactamente lo mismo** que uno que sí existe, y no manda correo.
- Tras confirmar, `iam.sessions` no tiene ninguna fila activa de esa persona y el token queda usado.
- El `detail` de ningún error permite deducir si el correo existe.
- `openapi.json` regenerado y `docs/api.md` con las tres rutas.
- Prueba manual: pedir el código, cambiarlo y volver a entrar con la contraseña nueva.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-14 | MM-89 · feat(iam): restablecer la contraseña con código de 6 dígitos | Cumplido |
| RF-15 | MM-99 · fix(iam): valida el código antes de pedir la contraseña nueva | Cumplido |

## Decisiones tomadas

- 2026-10-16 · **El flujo va con un código de 6 dígitos que se escribe en la app**, no con un link: la app no necesita enlaces profundos ni una página web en la API, y funciona si el correo se abre en otro dispositivo.
- 2026-10-16 · **El código se guarda con argon2id**, no con un hash rápido: con 6 dígitos, un `sha256` se rompe en un segundo. Cada intento cuesta lo mismo que verificar una contraseña.
- 2026-10-16 · El pedido y la confirmación llevan el `email`: la app lo guarda entre las dos pantallas.
- 2026-10-16 · **Al buscar la cuenta se exige `status = 'active'`**: una cuenta suspendida o a medio borrar no recibe código, y tampoco entra con Google por la identidad ya vinculada. Fue un hueco que apareció escribiendo las pruebas.
- 2026-10-16 · **Se agrega `verify` (RF-15).** Sin él, la app solo podía comprobar el código junto con la contraseña nueva: dejaba pasar cualquier código de 6 dígitos a la pantalla de la contraseña y recién avisaba al guardar. `verify` no gasta el código y comparte los 5 intentos con `confirm`, así que no sirve para adivinarlo.
- 2026-10-16 · El código **no se reenvía solo**: pedir otro genera uno nuevo y deja sin efecto el anterior (RF-4).

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿Cuánto debería durar el código? Se propone 30 minutos; más tiempo es más cómodo y menos seguro.
- [NECESITA ACLARACIÓN] Después de cambiar la contraseña, ¿la app la loguea sola con la contraseña nueva o le pide entrar? Esta spec la deja entrar de nuevo a mano (RF-8 revoca todo), que es lo más simple y lo más claro.
- [NECESITA ACLARACIÓN] ¿Hay que avisar por correo que la contraseña cambió (sin código, solo el aviso)? Es lo que hace la mayoría y ayuda si alguien la cambió sin permiso.
