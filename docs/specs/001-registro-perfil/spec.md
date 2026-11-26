# Spec 001 — Registro, perfil y personalización (API)

## Contexto y objetivo
Antes de registrar un gasto, una persona necesita una cuenta propia con sus datos básicos. Esta spec cubre la API que registra con correo y contraseña, Google o Apple; que guarda su perfil (nombre, apellido y datos opcionales) y su personalización (tema, color de acento, modo privado e inicio de semana) en el servidor, para que se mantenga en cualquier dispositivo. Corresponde a FTR-001, FTR-024 y FTR-025 y a la sección 6.1 del PRD 1.4. Tablas: `iam.users`, `iam.user_preferences`, `iam.auth_identities`, `iam.sessions`, `iam.email_verifications`.

## Usuarios / actores
- Persona nueva, desde la app (iOS o Android).
- Usuario registrado que edita su perfil o su personalización.
- Google y Apple como proveedores de identidad.
- La app MoneyMap como cliente de la API.

## Historias de usuario
- H1: Como persona nueva quiero registrarme con mi correo, una contraseña, mi nombre y mi apellido para empezar a usar MoneyMap.
- H1b: Como persona nueva quiero confirmar que el correo es mío con un link antes de escribir mis datos, para no crear una cuenta con un correo mal escrito.
- H2: Como persona nueva quiero registrarme con Google o Apple sin volver a escribir mi nombre ni mi correo.
- H3: Como usuario quiero que la app me llame como yo prefiera y completar mi perfil (foto, teléfono, país, ciudad, ocupación) cuando quiera.
- H4: Como usuario quiero elegir tema, color de acento, modo privado y día de inicio de semana, y encontrarlos igual al entrar desde otro dispositivo.
- H5: Como usuario quiero que nadie más pueda ver ni cambiar mi perfil o mi personalización.

## Requisitos funcionales (criterios de aceptación en EARS)
- RF-1: CUANDO llega `POST /v1/auth/register` con `verification_id` (un correo ya verificado, RF-26), `password`, `first_name`, `last_name` y `terms_version`, EL SISTEMA crea el usuario (`iam.users`), su identidad `password` con la contraseña en argon2id y sus preferencias por defecto, y responde 201 con el perfil, un token de acceso y un refresh token.
- RF-2: **Sin efecto desde el 2026-10-16.** El registro ya no pide la fecha de nacimiento, así que no hay control de edad. El número no se reusa.
- RF-3: SI falta `first_name`, `last_name` o `terms_version`, o el nombre o el apellido quedan vacíos al quitar espacios, ENTONCES EL SISTEMA responde 422 `validation_error` indicando el campo.
- RF-4: SI el correo ya pertenece a un usuario no borrado, sin distinguir mayúsculas, ENTONCES EL SISTEMA responde 409 `email_taken`.
- RF-5: SI `terms_version` no es la versión vigente de los términos, ENTONCES EL SISTEMA responde 422 `terms_outdated` con la versión vigente.
- RF-6: CUANDO llega `POST /v1/auth/oauth/{provider}` (`google` o `apple`) con un token válido de una persona ya registrada, EL SISTEMA inicia sesión y responde 200 con los tokens.
- RF-7: CUANDO llega `POST /v1/auth/oauth/{provider}` con un token válido de una persona no registrada, EL SISTEMA responde 200 con `registration_required`, el nombre, el apellido y el correo que dio el proveedor y un `registration_token` válido por 15 minutos, sin crear el usuario.
- RF-8: CUANDO llega `POST /v1/auth/oauth/complete` con un `registration_token` vigente, `first_name`, `last_name`, `terms_version` y, si el proveedor no lo dio, `email`, EL SISTEMA crea el usuario como en RF-1, con la identidad del proveedor en lugar de la contraseña, y aplica RF-2 a RF-5.
- RF-9: CUANDO un usuario autenticado pide `GET /v1/me`, EL SISTEMA devuelve su perfil: nombre, apellido, `display_name`, correo, foto, teléfono, país, ciudad, ocupación, idioma y zona horaria.
- RF-10: CUANDO un usuario autenticado envía `PATCH /v1/me`, EL SISTEMA actualiza solo los campos enviados (`first_name`, `last_name`, `display_name`, `country_code`, `city`, `occupation`, `avatar_object_key`, `locale`, `timezone`) y devuelve el perfil como quedó guardado (espacios limpios, país en mayúsculas).
- RF-11: SI `display_name` se envía vacío o nulo, ENTONCES EL SISTEMA guarda el nombre como `display_name`.
- RF-12: SI el teléfono no queda en formato E.164 al quitar espacios, guiones y paréntesis, o la ocupación no es una de las siete permitidas, ENTONCES EL SISTEMA responde 422 `validation_error`.
- RF-13: CUANDO un usuario pide `POST /v1/me/avatar-upload-url` con el tipo de imagen, EL SISTEMA devuelve una URL firmada de Cloud Storage para subir una imagen JPEG, PNG o WebP de hasta 5 MB, válida por 10 minutos, bajo el prefijo de ese usuario.
- RF-14: SI `avatar_object_key` no está bajo el prefijo del usuario, ENTONCES EL SISTEMA responde 422 y no lo guarda.
- RF-15: CUANDO un usuario pide `GET /v1/me/preferences` o envía `PATCH /v1/me/preferences`, EL SISTEMA lee o actualiza solo sus preferencias: `theme` (`system`, `light`, `dark`), `accent_color` (#RRGGBB o nulo), `hide_amounts` y `week_starts_on` (0 domingo a 6 sábado).
- RF-16: SI el tema, el color o el día de inicio de semana no son válidos, ENTONCES EL SISTEMA responde 422 `validation_error` y no cambia nada.
- RF-17: MIENTRAS el refresh token no haya expirado ni se haya revocado, EL SISTEMA entrega un par de tokens nuevo en `POST /v1/auth/refresh` y revoca el anterior (rotación).
- RF-18: SI llega un refresh token ya usado, ENTONCES EL SISTEMA revoca toda la cadena de sesiones de ese dispositivo, responde 401 y escribe `ops.log('warning', 'security', 'auth.refresh.reused', …)`.
- RF-19: EL SISTEMA atiende cada petición autenticada con `app.user_id` del token, de modo que ningún usuario lee ni modifica el perfil ni las preferencias de otro.
- RF-20: CUANDO llega `POST /v1/auth/login` con `email` y `password` de una persona registrada, EL SISTEMA verifica la contraseña y responde 200 con un par de tokens nuevo; SI el correo no existe o la contraseña no coincide, ENTONCES responde 401 `invalid_credentials` sin decir cuál de los dos falló y tardando lo mismo en los dos casos.
- RF-21: MIENTRAS una persona o una IP supere los intentos permitidos (100 registros por IP por hora, 10 inicios de sesión por minuto por correo, 5 links de verificación por correo y 100 por IP por hora), EL SISTEMA responde 429 `too_many_requests` con `Retry-After`.
- RF-22: CUANDO llega `POST /v1/auth/email-verifications` con un `email` sin cuenta, EL SISTEMA guarda la verificación con el hash de un token de un solo uso, envía al correo un link que vence a los 5 minutos y responde 201 con `id`, `email`, `status` `pending`, `expires_at` y `resend_available_at`; SI el correo ya tiene cuenta, ENTONCES responde 409 `email_taken` sin enviar nada ni dar datos de esa cuenta.
- RF-23: CUANDO llega `GET /v1/auth/email-verifications/{id}`, EL SISTEMA responde su estado: `pending`, `verified` o `expired`; SI no existe o ya se usó, ENTONCES 404 `not_found`.
- RF-24: CUANDO se abre el link (`GET /v1/auth/verify-email?token=`) antes de que venza, EL SISTEMA marca el correo como verificado y responde una página HTML que pide volver a la app; SI venció, ENTONCES responde 410 con "El link expiró"; SI el token no existe, fue reemplazado o ya se usó, ENTONCES 404 con "Este link no sirve".
- RF-25: CUANDO llega `POST /v1/auth/email-verifications/{id}/resend` y pasó al menos un minuto desde el último envío, EL SISTEMA envía un link nuevo que vence a los 5 minutos y el anterior deja de servir; SI no pasó el minuto, ENTONCES responde 429 `too_many_requests` con `Retry-After`.
- RF-26: SI el registro llega con una verificación `pending`, ENTONCES EL SISTEMA responde 409 `email_not_verified`; SI llega vencida (el link no se abrió a tiempo, o pasaron 30 minutos desde que se verificó), ENTONCES 410 `verification_expired`; SI no existe o ya se usó, ENTONCES 404 `not_found`. Con una verificación `verified`, crea el usuario con ese correo y `email_verified_at`, y la marca usada en la misma transacción.
- RF-27: SI la cuenta existe y la contraseña coincide pero `email_verified_at` está vacío, ENTONCES `POST /v1/auth/login` responde 409 `email_not_verified` sin abrir sesión; SI la contraseña no coincide, ENTONCES responde 401 `invalid_credentials` como siempre, para no delatar la cuenta.
- RF-28: CUANDO un usuario autenticado envía `POST /v1/me/deletion` con su `password`, o con `provider` (`google` o `apple`) y un `id_token` recién pedido de una identidad vinculada a su cuenta, EL SISTEMA deja la cuenta en `pending_deletion` con la fecha del pedido, cierra todas sus sesiones, escribe `ops.log('info', 'security', 'account.deletion.requested', …)` y responde 202 con `deletion_scheduled_at` (30 días después). SI la prueba no coincide, ENTONCES responde 403 `reauthentication_failed` y no cambia nada.
- RF-29: CUANDO pasaron 30 días desde el pedido, EL SISTEMA borra la cuenta y, en cascada, todos sus datos (un job diario de Celery).
- RF-30: SI una cuenta en `pending_deletion` entra con su contraseña, con Google o con Apple antes de los 30 días, ENTONCES EL SISTEMA cancela el borrado: la cuenta vuelve a `active`.
- RF-31: MIENTRAS una cuenta está en `pending_deletion`, su correo sigue tomado: no se puede registrar otra cuenta con él (`email_taken`).
- RF-32: CUANDO llega `POST /v1/auth/logout` con un `refresh_token`, EL SISTEMA revoca la sesión de ese dispositivo y lo que la reemplazó, deja vivas las de los otros dispositivos y responde 204; SI el token no existe, ya se revocó o venció, ENTONCES responde 204 igual, sin decir cuál de los casos fue.

## Requisitos no funcionales
- Seguridad: del link de verificación, igual que del refresh token, la base guarda solo el hash. argon2id para contraseñas; token de acceso de 15 minutos y refresh de 30 días con rotación (valores propuestos); verificación de los tokens de Google y Apple en el servidor.
- Límite de intentos: 100 registros por IP por hora y 10 inicios de sesión por minuto por correo, con 429 `too_many_requests`. Por IP solo frena el abuso en masa: la web registra desde su servidor (una sola IP) y las operadoras móviles comparten IPs entre muchos clientes (2026-11-05).
- Rendimiento: p95 menor a 800 ms en registro e inicio de sesión (argon2id es lento a propósito) y menor a 300 ms en `/v1/me` y `/v1/me/preferences`.
- Privacidad: ni la contraseña ni los tokens aparecen en logs ni en Sentry.
- Idioma: `detail` de los errores en español; `code` estable en inglés.
- Contrato: todos los endpoints documentados en OpenAPI con ejemplos.

## Casos límite
- El mismo correo con otras mayúsculas o con espacios alrededor: se normaliza al pedir el link y choca con RF-22.
- Dos verificaciones del mismo correo terminan en dos registros: el índice único deja pasar uno; el otro recibe 409 `email_taken` (RF-4).
- La persona abre el link dos veces: sigue verificado, no es un error.
- Reenvía el link y abre el correo viejo: el link viejo ya no sirve (RF-25).
- Dos registros simultáneos con el mismo correo: el índice único deja pasar uno; el otro recibe 409.
- Nombres compuestos, con tildes, ñ o apóstrofo ("María José", "O'Connor"); 60 caracteres pasan, 61 no.
- Apple puede no entregar el correo, o entregar uno de reenvío privado (`@privaterelay.appleid.com`): `registration_required` llega sin correo y RF-8 lo exige.
- El usuario cancela el registro social a mitad: el `registration_token` vence y no queda nada creado.
- Un usuario creado antes de existir `iam.user_preferences` no tiene fila: `GET` la crea con valores por defecto.
- `PATCH /v1/me` sin campos: 200 sin cambios.

## Fuera de alcance
- Verificación del teléfono y segundo factor.
- Iniciar sesión con Meta: se descartó el 2026-10-15. Quedan contraseña, Google y Apple.
- Temas personalizados (FTR-027).
- Elegir la moneda principal: es el primer paso del onboarding (spec 002).
- Cambiar el correo o recuperar la contraseña: van en su propia spec.

## Estado de implementación (2026-10-15)

Primer corte con la arquitectura del ADR-001. Tests en `tests/integration/test_iam_auth.py`,
`tests/integration/test_iam_email_verification.py`, `tests/unit/test_security.py` y
`tests/unit/test_config.py`.

| RF | Estado | Nota |
|---|---|---|
| RF-22 a RF-26 | Cumplido | Verificación del correo con link antes de crear la cuenta (MM-32; la API en MM-69 a MM-73). El correo sale por SMTP (MM-83); en dev, con `EMAIL_BACKEND=log`, el link va al log. |

| RF | Estado | Nota |
|---|---|---|
| RF-1, RF-3 a RF-5 | Cumplido | Registro con correo y contraseña; los términos y el correo repetido los aplica la base y `core/errors.py` los traduce. |
| RF-9 | Cumplido | `GET /v1/me` con el token de acceso. |
| RF-17 y RF-18 | Cumplido | Rotación del refresh token y corte de la cadena al reusarlo, con la traza en `ops.log`. |
| RF-19 | Cumplido | La identidad sale del JWT: de ahí sale `app.user_id` y la RLS aplica. |
| RF-20 | Cumplido | `POST /v1/auth/login`, con la misma respuesta y el mismo tiempo para el correo inexistente y la contraseña mala. |
| RF-27 | Cumplido | El login exige `email_verified_at`; se comprueba después de la contraseña (MM-88). |
| RF-21 | Cumplido | 100 registros por IP por hora, 10 logins por minuto por correo y 5 links por correo (100 por IP) por hora, con Redis y `Retry-After`. |
| RF-6 y RF-7 | Cumplido | `POST /v1/auth/oauth/{provider}` con `google` o `apple`: si el correo ya tiene cuenta se **vincula** y entra; si no, responde `registration_required` con un `registration_token` firmado de 15 minutos. |
| RF-8 | Cumplido | `POST /v1/auth/oauth/complete`: crea la cuenta con la identidad del proveedor. Nace con el correo verificado. |
| RF-10 a RF-12 | Cumplido | `PATCH /v1/me`: un campo opcional en `null` se borra; la base normaliza el teléfono, el país y los espacios, y vuelve al nombre si `display_name` queda vacío (`tests/integration/test_iam_profile.py`, 14). `avatar_object_key` queda para RF-13 y RF-14. |
| RF-13 y RF-14 | Por hacer | Avatar. |
| RF-15 y RF-16 | Cumplido | `GET` y `PATCH /v1/me/preferences`: solo lo enviado; `accent_color` en `null` vuelve al color de la marca; los valores los valida el esquema y también los CHECK de `iam.user_preferences` (`tests/integration/test_iam_preferences.py`, 11). El color acepta cualquier `#RRGGBB` hasta que se responda la duda de la paleta. |
| RF-32 | Cumplido | `POST /v1/auth/logout` revoca la cadena de ese refresh token con `revoke_chain` (`tests/integration/test_iam_auth.py`). |
| RF-28 a RF-31 | Cumplido | `POST /v1/me/deletion`, la migración 0005 (`deletion_requested_at`) y el job `identity.purge_deleted_accounts` a las 04:30 UTC (`tests/integration/test_iam_account_deletion.py` y `test_workers_account_deletion.py`). |

Con esto `get_current_user_id` dejó de responder 501: los módulos ya autenticados
—`finance` incluido— usan el token de verdad.

## Criterios de finalización
- Cada RF tiene al menos un test de integración en verde contra PostgreSQL 16 con todas las migraciones.
- `db/tests/smoke_test.sql` en verde (incluye las pruebas de perfil y de preferencias con RLS).
- `openapi.json` regenerado y revisado con la app.
- Demostración manual: registro con correo y con Google, edición del perfil y cambio de tema reflejado en un segundo dispositivo.

## Tickets

| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-8, RF-17 a RF-26 | MM-32 · FTR-001 Autenticación y plataforma SaaS | En curso (RF-1 a RF-8, RF-17 a RF-27 cumplidos; Google en MM-93, Apple en MM-106; falta la plataforma SaaS) |
| RF-9 a RF-16 | MM-33 · FTR-024 Ajustes de cuenta, moneda y preferencias | Por hacer (RF-9 a RF-12, RF-15 y RF-16 listos; falta el avatar) |
| RF-27 | MM-88 · feat(iam): bloqueo del login hasta verificar el correo | Cumplido |
| RF-28 a RF-31 | MM-33 · FTR-024 Ajustes de cuenta, moneda y preferencias | Cumplido |
| RF-32 | MM-143 · Cerrar sesión e ícono de la app | Cumplido |

## Decisiones tomadas
- Bug de QA (BUG-053, 2026-10-31): un refresh token rotado hace menos de 60 s cuyo par nuevo nunca se usó no se trata como reuso: la respuesta se perdió en la red (timeout, mala señal) y la app reintentó. Se rota desde ese par sin usar y se entrega otro. Fuera del margen, o si el par nuevo ya se usó, sigue RF-18.

- 2026-10-17 · **Borrar la cuenta tiene 30 días de gracia** (RF-28 a RF-31): se pide con la contraseña o con un `id_token` fresco del proveedor —así no la borra cualquiera con el teléfono desbloqueado—, se cierran todas las sesiones y entrar antes de los 30 días lo cancela. La fecha va en su propia columna (`deletion_requested_at`, migración 0005): `deleted_at` liberaría el correo antes de tiempo. El job borra cada cuenta en su propia transacción con `app.user_id`, así que no necesita el rol del worker.
- 2026-10-17 · **Se agrega Apple**, verificado igual que Google: JWKS público de Apple, sin `.p8` ni `client_secret`. La audiencia se acepta de una lista (`APPLE_CLIENT_IDS`) porque el token de la app iOS la firma con el **bundle ID** (`com.moneymap.moneymapApp`) y el de la web, con el **Service ID**. `email_verified` viene como texto (`"true"`), y el correo **solo viene la primera vez**: la cuenta se encuentra por el `sub`.

- 2026-10-16 · **El ingreso con Google vincula por correo.** Si el correo del token ya tiene una cuenta (con contraseña o como sea), se le agrega la identidad de Google y la persona entra, sin pedirle nada más. Es seguro porque el verificador **exige `email_verified`**: sin eso, cualquiera podría crear una cuenta de Google con el correo de otra persona y quedarse con su cuenta de MoneyMap.
- 2026-10-16 · El `registration_token` del registro social es un **JWT firmado** de 15 minutos, no una fila: no hace falta guardarlo ni limpiarlo, y la app no puede cambiarlo.
- 2026-10-16 · Se verifican los tokens con **`joserfc`**, no con `authlib`: authlib 1.9 marcó su módulo de JOSE como deprecado y manda a esa misma librería.

- 2026-10-16 · **Se quita la fecha de nacimiento:** el registro ya no pide la edad. La columna y el `CHECK` de mayores de 18 los quita la migración 0004, el RF-2 queda sin efecto y la constitución §5 se actualizó en los tres repos. El perfil (`GET /v1/me`) tampoco la devuelve.

- 2026-10-15 · La contraseña exige **8 caracteres como mínimo y 128 como máximo**.
- 2026-10-15 · El límite de intentos cuenta por la **última IP de `X-Forwarded-For`** (la que agrega el balanceador y nadie puede falsificar), con caída a la del socket si el encabezado no llega.
- 2026-10-15 · Si Redis no responde, el límite **deja pasar**. Es preferible a dejar sin registro ni login a todo el mundo. La caída se ve en las métricas de Redis, **no** en `/health`: un health check que dependa de Redis haría que Cloud Run reinicie instancias sanas.
- 2026-10-15 · Los proveedores de identidad son **contraseña, Google y Apple**. Meta queda fuera.
- 2026-10-15 · **El correo se verifica antes de crear la cuenta**, con un link que vence a los 5 minutos (mockups 02 a 04). La cuenta se crea después, con los datos de "Tus datos". Cierra la duda de si verificar antes o después.
- 2026-10-15 · La verificación vive en su propia tabla, `iam.email_verifications` (migración 0002): `iam.verification_tokens` exige un usuario y aquí todavía no hay.
- 2026-10-15 · El link lo abre el navegador y responde HTML; la app pregunta el estado con «Ya verifiqué · Continuar». Así no hacen falta App Links ni Universal Links para el registro.
- 2026-10-15 · El correo verificado sirve **30 minutos** para terminar el registro (propuesto). Pasado eso, `verification_expired` y se pide otro link.
- 2026-10-15 · `email_taken` al pedir el link no da el nombre de la cuenta: el mockup "Correo ya registrado" lo mostraba ("¿Eres tú, Ana?"), pero eso le diría a cualquiera de quién es un correo.
- 2026-10-15 · El proveedor de correo queda por elegir. En dev, `EMAIL_BACKEND=log` escribe el link en el log de la API; fuera de dev la API no arranca con él.
- 2026-10-15 · Todo el SQL va con `text()` y parámetros de enlace; ningún dato se concatena. Lo verifica ruff (`S608`) y lo comprueban las pruebas de `tests/integration/test_sql_injection.py`.

## Dudas abiertas
- [NECESITA ACLARACIÓN] Hoy no se puede crear una cuenta con el correo sin verificar: el registro lo exige, así que el bloqueo de RF-27 es defensivo. Si alguna vez existe una cuenta así, no tiene cómo pedir otro link (`POST /v1/auth/email-verifications` responde `409 email_taken`). ¿Hace falta abrir ese reenvío para cuentas sin verificar?
- [NECESITA ACLARACIÓN] Queda pendiente si el `provider IN ('password','google','meta','apple')` de `iam.auth_identities` se ajusta en una migración para dar de baja `meta`.
- [NECESITA ACLARACIÓN] Los 401 usan `unauthorized` (sin token o token vencido), `invalid_credentials` (login) y `invalid_refresh_token` / `refresh_token_reused` (refresh). La spec solo dice "401". ¿Se confirman esos `code` para el cliente?
- [NECESITA ACLARACIÓN] `iam.sessions` tiene `ip` y `user_agent` y hoy quedan en `NULL`: la spec no los pide, pero son la única forma de saber desde dónde se abrió una sesión robada. ¿Se completan?
- [NECESITA ACLARACIÓN] ¿Qué proveedor envía los correos (Resend, SES, SMTP) y desde qué dominio? Hasta entonces el link solo existe en dev.
- [NECESITA ACLARACIÓN] Las filas de `iam.email_verifications` vencidas o usadas no se borran solas. ¿Un job de limpieza diario, y cuánto se guardan?
- [NECESITA ACLARACIÓN] Al entrar con el borrado pendiente, el login responde igual que siempre: la app no se entera de que se canceló. ¿Hace falta avisarle a la persona ("Cancelamos el borrado de tu cuenta")? Haría falta un campo en la respuesta del login o un correo.
- [NECESITA ACLARACIÓN] El token de acceso dura 15 minutos y no se revoca: después de pedir el borrado, ese token sigue sirviendo hasta que vence. ¿Alcanza, o la API tiene que rechazar los tokens de una cuenta en `pending_deletion`?
- [NECESITA ACLARACIÓN] Cuando existan las suscripciones de App Store y Google Play, borrar la cuenta no cancela la suscripción de la tienda: ¿se avisa en la pantalla de borrado, como piden las tiendas?
- [NECESITA ACLARACIÓN] ¿El color de acento es cualquier hexadecimal o una paleta cerrada de la marca?
- [NECESITA ACLARACIÓN] RF-13 pide una URL firmada de Cloud Storage, pero la API ya no corre en Google Cloud sino en nuestro servidor con Dokploy. ¿Dónde se guardan las fotos: un bucket compatible con S3 (MinIO en el mismo servidor, Cloudflare R2, Backblaze) o Cloud Storage igual?
