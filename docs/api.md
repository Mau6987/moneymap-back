# Contrato de la API

Qué puede consumir la app: los endpoints que ya están, los que vienen y los
errores que devuelven. Es el documento que se mira para programar el cliente y
para saber qué falta.

La fuente de verdad del código es [`openapi.json`](#el-contrato-de-máquina), que
se genera de los esquemas. Cada endpoint sale de un requisito funcional de una
spec en [`docs/specs/`](specs): acá se dice cuál, y la spec manda si hay
diferencias.

## El contrato de máquina

```bash
uv run python -m app.scripts.export_openapi > openapi.json
```

`openapi.json` está en `.gitignore`: se regenera, no se versiona. En local, la
documentación interactiva está en `http://localhost:8000/docs`.

**Cuando cambia un endpoint o un esquema hay que regenerarlo y avisarle a la
app en el mismo PR** (`docs/engineering.md` §6.5): la app regenera su cliente y
sin eso queda desincronizada.

## Convenciones

- Todo bajo `/v1`; lo de la persona autenticada, bajo `/v1/me`.
- Sustantivos en plural: `/v1/accounts`, `/v1/transactions`.
- **Los montos viajan como texto** (`"2500.00"`), nunca como número, y con los
  decimales de su moneda (CLP y PYG no llevan). Un monto con más decimales que
  los de la moneda se rechaza.
- **Nada suma monedas distintas.** Los totales van por moneda, con la principal
  primero. No hay tipos de cambio ni equivalente en otra moneda.
- Las fechas y horas son `timestamptz` en UTC; el día y el mes de la persona se
  calculan con su `timezone`.
- Los errores son `application/problem+json` (RFC 9457) con `code` estable en
  inglés y `detail` en español. Ver el [catálogo](#catálogo-de-errores).
- Los POST que registran dinero aceptan `Idempotency-Key`: un reintento con la
  misma clave devuelve la misma respuesta sin crear un segundo dato. La clave
  vale 24 h y es por usuario.

## Autenticación

```http
Authorization: Bearer <access_token>
```

| Cosa | Cómo funciona |
|---|---|
| Token de acceso | JWT, **15 minutos**. Va en cada petición autenticada. |
| Refresh token | Opaco, **30 días**. Sirve solo para pedir un par nuevo. |
| Rotación | Cada `POST /v1/auth/refresh` devuelve un par nuevo y revoca el anterior. |
| Reuso | Un refresh ya rotado corta **toda la cadena** de ese dispositivo: la app tiene que volver a pedir la contraseña. |
| Sin token | 401 `unauthorized`. |

El refresh token es de un solo uso: la app tiene que guardar el que le devolvió
la última respuesta, no el del registro.

## Endpoints disponibles hoy

| Método | Ruta | Qué hace | Spec |
|---|---|---|---|
| GET | `/health` | La API responde y llega a la base. Para el monitoreo. | — |
| POST | `/v1/auth/email-verifications` | Envía el link para verificar el correo: el primer paso del registro. | 001 · RF-22 |
| GET | `/v1/auth/email-verifications/{id}` | `pending`, `verified` o `expired`. | 001 · RF-23 |
| POST | `/v1/auth/email-verifications/{id}/resend` | Un link nuevo, no antes de un minuto. | 001 · RF-25 |
| GET | `/v1/auth/verify-email?token=` | El link del correo. Lo abre el navegador y responde HTML. | 001 · RF-24 |
| POST | `/v1/auth/register` | Registra a una persona con el correo que verificó. | 001 · RF-1, RF-3 a RF-5, RF-26 |
| POST | `/v1/auth/login` | Correo y contraseña a cambio de tokens. | 001 · RF-20 |
| POST | `/v1/auth/oauth/{provider}` | Ingresa con Google o Apple; si el correo ya tiene cuenta, la vincula. | 001 · RF-6, RF-7 |
| POST | `/v1/auth/oauth/complete` | Completa el registro con el proveedor. | 001 · RF-8 |
| POST | `/v1/auth/password-reset` | Pide el código para restablecer la contraseña. Responde 202 siempre. | 008 · RF-1 a RF-4 |
| POST | `/v1/auth/password-reset/verify` | Comprueba el código sin gastarlo, antes de pedir la contraseña nueva. | 008 · RF-15 |
| POST | `/v1/auth/password-reset/confirm` | Cambia la contraseña y cierra todas las sesiones. | 008 · RF-5 a RF-8 |
| POST | `/v1/auth/refresh` | Rota el refresh token. | 001 · RF-17, RF-18 |
| POST | `/v1/auth/logout` | Cierra la sesión de este dispositivo. | 001 · RF-32 |
| GET | `/v1/me` | El perfil propio. | 001 · RF-9 |
| PATCH | `/v1/me` | Corrige el perfil propio. | 001 · RF-10 a RF-12 |
| GET, PATCH | `/v1/me/preferences` | Tema, color de acento, modo privado e inicio de semana. | 001 · RF-15, RF-16 |
| POST | `/v1/me/deletion` | Pide borrar la cuenta: se borra en 30 días y entrar antes lo cancela. | 001 · RF-28 a RF-31 |
| GET | `/v1/me/settings` | La configuración financiera: moneda principal, periodo y ahorro planificado. | 002 · RF-1; 003 · RF-7 |
| PUT | `/v1/me/settings` | La moneda principal (paso 1 del onboarding), el periodo financiero y el ahorro planificado. | 002 · RF-1; 003 · RF-7 a RF-9 |
| GET | `/v1/safe-to-spend?currency=` | Cuánto queda libre en el periodo, con su desglose. | 003 · RF-1 a RF-6, RF-10 a RF-16 |
| GET | `/v1/reports/position?period=&on=&currency=` | Saldo, ingresos, gastos y ahorrado del mes (Map). | 004 · RF-1 a RF-5, RF-16 |
| GET | `/v1/reports/money-flow?period=&on=&currency=` | Los nodos del Money Flow: suman los ingresos. | 004 · RF-6, RF-7, RF-9, RF-11 |
| GET | `/v1/reports/money-flow/categories?group=&period=&on=&currency=` | Las categorías de un grupo, de mayor a menor. | 004 · RF-8, RF-10 |
| GET | `/v1/money-story?period=&currency=` | La Money Story del mes cerrado, una por moneda, con la comparación. | 006 · RF-1 a RF-7 |
| POST | `/v1/me/devices` | Registra o reactiva el dispositivo para recibir avisos. | 006 · RF-8, RF-9 |
| DELETE | `/v1/me/devices/{id}` | Da de baja el dispositivo: deja de recibir avisos. | 006 · RF-10 |
| GET, PUT | `/v1/me/notification-settings` | Qué avisos recibe y cuáles apagó. | 006 · RF-11, RF-12 |
| GET | `/v1/me/notifications?before=&limit=` | Los avisos recibidos, del más nuevo al más viejo, con cuántos sin leer. | 006 · RF-22 |
| POST | `/v1/me/notifications/read` | Marca todos los avisos como leídos. | 006 · RF-23 |
| GET | `/v1/accounts?archived=` | Las cuentas activas, la de por defecto primero; con `archived=true`, las archivadas. | 002 · RF-23 |
| POST | `/v1/accounts` | Crea una cuenta de efectivo o tarjeta. | 002 · RF-3 a RF-5, RF-9, RF-24, RF-25 |
| PATCH | `/v1/accounts/{id}` | Corrige el nombre o la moneda de una cuenta, o la archiva y la desarchiva. | 002 · RF-14, RF-24 |
| POST | `/v1/transactions` | Registra un gasto, un ingreso o una transferencia. | 002 · RF-6 a RF-8, RF-10 a RF-12 |
| PATCH | `/v1/transactions/{id}` | Corrige un movimiento. | 002 · RF-13 |
| GET | `/v1/transactions` | El historial, del más reciente al más viejo, por páginas; con filtros por cuenta, moneda, categoría, fechas y texto. | 002 · RF-26, RF-32 |
| DELETE | `/v1/transactions/{id}` | Borra un movimiento y devuelve el saldo a sus cuentas. | 002 · RF-27 |
| GET | `/v1/balances` | Totales por moneda para el Map. | 002 · RF-15 |
| GET | `/v1/currencies` | Mis monedas primero y después las demás activas. | 002 · RF-2, RF-20 |
| PUT | `/v1/me/currencies/{code}` | Suma una moneda a Mis monedas, sin crear cuentas. | 002 · RF-28 |
| DELETE | `/v1/me/currencies/{code}` | Quita una moneda de Mis monedas. | 002 · RF-19 |
| GET | `/v1/countries` | Países activos con su moneda local. | 007 |
| GET | `/v1/institutions?country=` | Bancos y billeteras de un país. | 002 · RF-3 |
| GET | `/v1/categories?type=` | Las categorías del usuario, con grupo, ícono y color. | 007 · RF-6, RF-17 |
| POST | `/v1/categories` | Crea una categoría. | 007 · RF-7 a RF-9 |
| PATCH | `/v1/categories/{id}` | Corrige una categoría; el tipo, solo si no tiene movimientos. | 007 · RF-10, RF-11 |
| DELETE | `/v1/categories/{id}` | Borra una categoría; sus movimientos quedan sin categoría. | 007 · RF-12 |
| GET | `/v1/transactions/category-suggestion?description=&type=` | La categoría de la última vez con esa descripción. | 007 · RF-13, RF-14 |
| POST | `/v1/recurring-rules` | Crea un ingreso o gasto recurrente (pasos 3 y 4 del onboarding). | 002 · RF-21; 007 |
| GET | `/v1/recurring-rules` | Los recurrentes vigentes, el que vence primero arriba. | 002 · RF-29 |
| PATCH | `/v1/recurring-rules/{id}` | Corrige un recurrente. | 002 · RF-21, RF-30 |
| DELETE | `/v1/recurring-rules/{id}` | Da de baja un recurrente. | 002 · RF-31 |
| POST | `/v1/recurring-rules/{id}/payments` | Marca un recurrente como pagado: registra el movimiento y pasa al vencimiento siguiente. | 003 · RF-17 a RF-19 |
| POST | `/v1/recurring-rules/{id}/skip` | Omite una vez: pasa al vencimiento siguiente sin registrar un movimiento. | 003 · RF-22 |
| GET | `/v1/onboarding` | Hasta dónde llegó el onboarding, para retomarlo. | 007 · RF-3 |
| POST | `/v1/goals` | Crea una meta de ahorro en una moneda. | 005 · RF-1 a RF-3 |
| GET | `/v1/goals` | Las metas con lo ahorrado, el avance y la fecha estimada. | 005 · RF-9, RF-10 |
| PATCH | `/v1/goals/{id}` | Corrige el nombre, el objetivo, la fecha o la prioridad. | 005 · RF-4 |
| DELETE | `/v1/goals/{id}` | Borra una meta y sus aportes. | 005 · RF-5 |
| POST | `/v1/goals/{id}/contributions` | Aporta a una meta desde una cuenta; al llegar al objetivo queda cumplida. | 005 · RF-6 a RF-8, RF-21 |
| POST | `/v1/goals/{id}/withdrawals` | Saca dinero de una meta a una cuenta. | 005 · RF-20 |
| GET | `/v1/goals/movements` | Los aportes y retiros de las metas, para el filtro "Metas" de Movimientos. | REQ-056 |
| POST | `/v1/affordability-checks` | ¿Me alcanza? Evalúa una compra sin guardarla. | 005 · RF-11 a RF-19 |
| GET | `/v1/plans` | Los planes con sus precios y límites, para la pantalla Planes. | 011 · RF-1, RF-3 |
| GET | `/v1/me/plan` | El plan propio, el estado de la suscripción y cuánto lleva usado. | 011 · RF-2 |
| PUT | `/v1/me/plan` | Elige otro plan, al instante y sin cobro (todavía no hay pagos). | 011 · RF-5 (MM-186) |
| GET | `/v1/admin/plans` | Panel: los cuatro planes con precios, funcionalidades y suscriptores. Solo el administrador. | 013 · RF-2 (MM-189) |
| PATCH | `/v1/admin/plans/{code}` | Panel: nombre, descripción y si se muestra. | 013 · RF-3 |
| PUT | `/v1/admin/plans/{code}/features/{key}` | Panel: si el plan tiene la funcionalidad y con qué límite. | 013 · RF-4 |
| PUT | `/v1/admin/plans/{code}/prices/{period}/{currency}` | Panel: el precio mensual o anual en una moneda. | 013 · RF-5 |
| GET | `/v1/admin/plan-changes` | Panel: historial de cambios a los planes. | 013 · RF-6 |
| POST | `/v1/budgets` | Crea un presupuesto mensual para una categoría de gasto. | 009 · RF-1, RF-8, RF-9 |
| GET | `/v1/budgets` | Los presupuestos del mes: gastado, restante y Spending Pace. | 009 · RF-3 a RF-7 |
| PATCH | `/v1/budgets/{id}` | Corrige el monto de un presupuesto. | 009 · RF-2 |
| DELETE | `/v1/budgets/{id}` | Borra un presupuesto. | 009 · RF-2 |
| POST | `/v1/what-if` | ¿Qué pasa si…? Simula uno o dos cambios sin guardarlos. | 009 · RF-12 a RF-16 |
| GET | `/v1/forecast?currency=` | El saldo proyectado a 30, 60 y 90 días. | 010 · RF-1 a RF-7 |
| POST | `/v1/onboarding/complete` | Cierra el onboarding con Ingresos, Comprometido y Safe to Spend. | 007 · RF-4, RF-5, RF-19 |

### `POST /v1/auth/email-verifications`

El registro empieza por el correo: la API envía un link y la app espera a que la
persona lo abra.

```json
{ "email": "ana@example.com" }
```

`201`:

```json
{
  "id": "6f1c2b8e-4c1a-4d5e-9a63-0b7f6f1a2c3d",
  "email": "ana@example.com",
  "status": "pending",
  "expires_at": "2026-10-15T12:05:00Z",
  "resend_available_at": "2026-10-15T12:01:00Z"
}
```

- El link vence a los **5 minutos**. `id` es lo que la app guarda para preguntar
  y para registrarse; no se adivina.
- `409 email_taken` si el correo ya tiene cuenta: la app ofrece entrar. No dice
  nada más de esa cuenta.
- 10 links por IP por hora, contando los reenvíos (`429 too_many_requests`).
- En dev el correo no sale: el link se escribe en el log de la API
  (`EMAIL_BACKEND=log`). La base del link es `PUBLIC_BASE_URL`.

### `GET /v1/auth/email-verifications/{id}`

`200` con el mismo cuerpo. `status`:

| `status` | Qué muestra la app |
|---|---|
| `pending` | Todavía no abrió el link: "Aún no lo vemos". |
| `verified` | Lo abrió: "Correo verificado" y sigue a "Tus datos". |
| `expired` | El link venció sin abrirse, o pasaron 30 minutos desde que se verificó sin registrarse: "El link expiró", con reenviar. |

`404 not_found` si no existe o ya se usó para crear la cuenta.

### `POST /v1/auth/email-verifications/{id}/resend`

Sin cuerpo. `200` con el estado y un `expires_at` nuevo: el link anterior deja de
servir. `429 too_many_requests` con `Retry-After` si no pasó un minuto desde el
último envío (`resend_available_at`). Si el correo ya está verificado no envía
nada y devuelve `verified`.

### `GET /v1/auth/verify-email?token=…`

El link que llega por correo. Lo abre el navegador del teléfono, no la app, así
que responde **HTML** y no problem+json: `200` "Correo verificado", `410` "El link
expiró" o `404` "Este link no sirve" (inventado, reemplazado por un reenvío o ya
usado). Abrirlo dos veces no es un error.

### `POST /v1/auth/register`

```json
{
  "verification_id": "6f1c2b8e-4c1a-4d5e-9a63-0b7f6f1a2c3d",
  "password": "clave-larga-123",
  "first_name": "Ana",
  "last_name": "Quispe",
  "terms_version": "2026-10"
}
```

`201` — el perfil ya viene en la respuesta, no hace falta pedirlo:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "JXtrvd3K1C9zfR8AqasFccp3gPAhH3DdqBfcrggWtvA",
  "token_type": "bearer",
  "expires_in": 900,
  "profile": {
    "id": "01a14033-6bac-7a3a-bc52-1b537943e4e5",
    "email": "ana@example.com",
    "first_name": "Ana",
    "last_name": "Quispe",
    "display_name": "Ana",
    "avatar_object_key": null,
    "country_code": null,
    "city": null,
    "occupation": null,
    "locale": "es-BO",
    "timezone": "America/La_Paz",
    "is_admin": false
  }
}
```

El correo es el de la verificación, que tiene que estar en `verified`:
`409 email_not_verified` si todavía no se abrió el link, `410
verification_expired` si venció y `404 not_found` si no existe o ya se usó (una
verificación crea una sola cuenta). El nombre se limpia. La contraseña pide
entre 8 y 128 caracteres. `terms_version` tiene que ser la
vigente: se pregunta con `422 terms_outdated`, que trae cuál es.

### `POST /v1/auth/login`

```json
{ "email": "ana@example.com", "password": "clave-larga-123" }
```

`200` con `access_token`, `refresh_token`, `token_type` y `expires_in` — el
mismo cuerpo que `/v1/auth/refresh`, sin el perfil.

`409 email_not_verified` si la cuenta existe y la contraseña coincide, pero el
correo no está confirmado: la app manda a la pantalla de verificación. Se mira
**después** de la contraseña, así que con una clave mala la respuesta sigue
siendo `401` y no delata la cuenta.

### `POST /v1/auth/oauth/{provider}`

El ingreso con **Google o Apple**. `{provider}` es `google` o `apple`. La app hace el
flujo con el proveedor y manda el **token de identidad** que le devuelve:

```json
{ "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6..." }
```

`200` — cambia según si el correo ya tiene cuenta:

Si ya la tiene, responde los mismos tokens que el login. **Si el correo tiene una
cuenta con contraseña, se vincula y entra**: Google ya comprobó que el correo es de
esa persona, así que no se le pide nada más.

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "JXtrvd3K1C9zfR8AqasFccp3gPAhH3DdqBfcrggWtvA",
  "token_type": "bearer",
  "expires_in": 900
}
```

Si no la tiene, pide completar el registro (RF-7). El nombre y el correo pueden
venir vacíos si el proveedor no los dio:

```json
{
  "registration_required": true,
  "registration_token": "eyJhbGciOiJIUzI1NiJ9...",
  "email": "ana@example.com",
  "first_name": "Ana",
  "last_name": "Quispe"
}
```

El `registration_token` vale **15 minutos** y no hace falta guardarlo de este lado:
viaja firmado.

**Con Apple** el token de la app iOS viene con la audiencia del **bundle ID**
(`com.moneymap.moneymapApp`) y el de la web, con el **Service ID**; la API acepta las
que estén en `APPLE_CLIENT_IDS`. Apple manda el correo **solo la primera vez** que se
autoriza la app: la cuenta se encuentra por el `sub`, y si es nueva y falta el correo,
se pide al completar el registro.

### `POST /v1/auth/oauth/complete`

Cierra el registro con lo que la app juntó (RF-8). `email` solo hace falta si el
proveedor no lo dio:

```json
{
  "registration_token": "eyJhbGciOiJIUzI1NiJ9...",
  "first_name": "Ana",
  "last_name": "Quispe",
  "terms_version": "2026-10"
}
```

`201` con el perfil y los tokens, igual que el registro normal. La cuenta nace con
el correo **ya verificado**, porque lo verificó el proveedor.

### `POST /v1/auth/password-reset`

Pide el código que llega por correo.

```json
{ "email": "ana@example.com" }
```

`202` **siempre, exista o no la cuenta**, y sin cuerpo: es lo único que impide
averiguar quién tiene cuenta. Si el correo tiene cuenta con contraseña, manda un
**código de 6 dígitos** que vence en 30 minutos y deja sin efecto el anterior. Si la
cuenta entra con Google, manda un aviso en vez de un código.

### `POST /v1/auth/password-reset/verify`

Comprueba el código antes de pedir la contraseña nueva. **No lo gasta ni cambia
nada**: después hay que mandarlo otra vez en `/confirm`.

```json
{ "email": "ana@example.com", "code": "123456" }
```

`204` si es el código vigente de esa cuenta. `401 invalid_reset_code` si no
existe, venció, ya se usó o el correo no tiene cuenta: el mismo `detail` en todos
los casos. Cuenta en los mismos **cinco intentos cada 15 minutos** que `/confirm`
(después, `429`), así que no sirve para adivinar el código.

### `POST /v1/auth/password-reset/confirm`

```json
{
  "email": "ana@example.com",
  "code": "123456",
  "new_password": "clave-nueva-456"
}
```

`204` con la contraseña cambiada. **Cierra todas las sesiones de esa persona**, en
todos sus dispositivos, así que hay que volver a entrar. El código sirve una sola
vez. Cinco intentos fallidos por correo cada 15 minutos, y después `429`.

### `POST /v1/auth/refresh`

```json
{ "refresh_token": "JXtrvd3K1C9zfR8AqasFccp3gPAhH3DdqBfcrggWtvA" }
```

`200` con el par nuevo. El anterior queda revocado.

### `POST /v1/auth/logout`

Cierra la sesión **de este dispositivo**: se manda el `refresh_token` que la
app tiene guardado, el último que le devolvió la API.

```json
{ "refresh_token": "JXtrvd3K1C9zfR8AqasFccp3gPAhH3DdqBfcrggWtvA" }
```

`204` sin cuerpo. Ese refresh token y los que lo reemplazaron dejan de servir;
las sesiones de los otros dispositivos siguen. El token de acceso que ya se
entregó vale hasta que vence (15 minutos): la app lo borra junto con el refresh.

- Un token que no existe, ya se revocó o venció también responde `204`: la
  sesión ya no sirve, que es lo que se pide, y la respuesta no delata qué
  tokens existieron.
- No pide `Authorization`: con el token de acceso vencido también se puede
  cerrar la sesión.
- Sin `refresh_token` o vacío: `422 validation_error`.

### `GET /v1/me`

`200` con el perfil, igual al `profile` del registro.

### `PATCH /v1/me`

Se corrige solo lo que se envía, y responde `200` con el perfil **como quedó
guardado** (la misma forma que `GET /v1/me`): la app muestra eso, no lo que
mandó.

```json
{ "display_name": "Anita", "country_code": "bo", "occupation": "self_employed" }
```

| Campo | Qué acepta | Cómo se guarda |
|---|---|---|
| `first_name`, `last_name` | 1 a 60 caracteres. No se pueden borrar. | Sin espacios de sobra. |
| `display_name` | Hasta 120 caracteres. | Vacío o `null`: el nombre (`first_name`). |
| `country_code` | Dos letras de un país del catálogo (`GET /v1/countries`). | En mayúsculas. |
| `city` | Hasta 80 caracteres. | Sin espacios en los bordes. |
| `occupation` | `student`, `employee`, `self_employed`, `entrepreneur`, `unemployed`, `retired` u `other`. | Igual. |
| `locale` | `es-BO`, `es`. No se puede borrar. | Igual. |
| `timezone` | Una zona IANA: `America/La_Paz`. No se puede borrar. | Igual. Con ella se calculan los días y los periodos. |

`country_code`, `city` y `occupation` se borran enviándolos en `null`. Lo que
no sirve responde `422 validation_error` y no cambia nada: un país que no está, una ocupación inventada, un
nombre vacío, una zona que no existe. La foto (`avatar_object_key`) todavía no
se cambia acá: va con la subida de la imagen (RF-13 y RF-14).

### `GET /v1/me/preferences` y `PATCH /v1/me/preferences`

Las preferencias de la app, iguales en todos los dispositivos de la persona.
Las dos responden `200` con:

```json
{ "theme": "system", "accent_color": null, "hide_amounts": false, "week_starts_on": 1, "agenda_view": "list", "agenda_reminder_minutes": 15 }
```

| Campo | Qué acepta | Por defecto |
|---|---|---|
| `theme` | `system`, `light` o `dark`. | `system` |
| `accent_color` | `#RRGGBB`, o `null` para el color de la marca. | `null` |
| `hide_amounts` | `true` o `false`: el modo privado, que oculta los montos. | `false` |
| `week_starts_on` | 0 (domingo) a 6 (sábado). | 1 (lunes) |
| `agenda_view` | `list` o `calendar`. | `list` |
| `agenda_reminder_minutes` | 1 a 1440 (minutos de antelación para avisos de agenda). | 15 |

El `PATCH` cambia solo lo que se envía. Solo `accent_color` acepta `null`. Un
tema, color o día que no sirve responde `422 validation_error` y no cambia nada.

### `POST /v1/me/deletion`

Pide borrar la cuenta. Lo exigen App Store y Google Play. Se confirma que es la
persona con **una** de dos pruebas:

```json
{ "password": "clave-larga-123" }
```

```json
{ "provider": "google", "id_token": "eyJhbGciOiJSUzI1NiIs..." }
```

Con Google o Apple, el `id_token` tiene que ser **recién pedido** al proveedor y
de una cuenta vinculada a esta.

`202`:

```json
{ "deletion_scheduled_at": "2026-11-16T14:03:22.511Z" }
```

- Todas las sesiones se cierran en el momento: el refresh token deja de servir.
  La app cierra la sesión y vuelve al inicio.
- La cuenta y todos sus datos se borran el `deletion_scheduled_at`. **Entrar
  antes con la contraseña, Google o Apple cancela el borrado.**
- Mientras espera, el correo sigue tomado: registrarse con él da `409 email_taken`.
- Si la prueba no coincide: `403 reauthentication_failed`. Es 403 y no 401: la
  sesión sigue siendo válida y la app **no** tiene que cerrarla. Un `id_token`
  que el proveedor rechaza da `401 invalid_provider_token`, como en el ingreso.
- Las dos pruebas a la vez, o ninguna: `422 validation_error`.

### `POST /v1/accounts`

```json
{
  "name": "Efectivo Bs",
  "type": "cash",
  "currency": "BOB",
  "opening_balance": "2500.00"
}
```

Si es `"type": "card"` se agrega `last4` (cuatro dígitos, obligatorio) y,
si la entidad está en el catálogo, `institution_code` (por ejemplo `bo.bnb`).
Una tarjeta personalizada puede no llevar `institution_code`, pero nunca
puede quedar sin `last4`: `422 validation_error`.

`201`:

```json
{
  "id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
  "name": "Efectivo Bs",
  "type": "cash",
  "currency": "BOB",
  "current_balance": "2500.00",
  "is_default": true,
  "created_at": "2026-10-15T12:04:31.412Z"
}
```

El saldo lo calcula la base. La primera cuenta queda como la predeterminada.

Errores propios: `409 account_name_taken` si otra cuenta ya tiene ese nombre (sin
distinguir mayúsculas), y `422 validation_error` si `institution_code` no está en
`GET /v1/institutions`.

### `GET /v1/accounts?archived=`

`200` — las cuentas activas, la de por defecto primero. Es la misma cuenta que
devuelve `POST /v1/accounts`, más el banco y los últimos 4 dígitos (`null` en
efectivo). Con `archived=true`, solo las archivadas: su largo es el número de
"Archivadas (1)".

```json
[
  {
    "id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
    "name": "Efectivo Bs",
    "type": "cash",
    "currency": "BOB",
    "current_balance": "2500.00",
    "is_default": true,
    "created_at": "2026-10-15T12:04:31.412Z",
    "archived_at": null,
    "institution_code": null,
    "last4": null
  },
  {
    "id": "01a14035-0b7e-7c42-9a1d-61c2e5f4b0a2",
    "name": "Tarjeta BNB",
    "type": "card",
    "currency": "BOB",
    "current_balance": "-180.50",
    "is_default": false,
    "created_at": "2026-10-15T12:06:02.118Z",
    "archived_at": null,
    "institution_code": "bo.bnb",
    "last4": "1234"
  }
]
```

### `GET /v1/balances`

`200` — una fila por moneda, la principal primero:

```json
[
  {
    "currency": "BOB",
    "is_main_currency": true,
    "total": "2500.00",
    "cash_total": "2500.00",
    "card_total": "0.00",
    "accounts": 2
  }
]
```

### `GET /v1/me/settings`

`200` — la configuración, con la misma forma que responde `PUT`. Con
`period_type` y `period_start_day` la app sabe si el periodo de Safe to Spend es
semanal, quincenal o mensual. Sin moneda principal todavía, `422
onboarding_incomplete`.

### `PUT /v1/me/settings`

Se cambia solo lo que se envía, y al menos un campo:

| Campo | Qué es |
|---|---|
| `main_currency` | La moneda que la app muestra primero. **La primera vez es obligatoria** (paso 1 del onboarding): crea la configuración y siembra las categorías. Cambiarla **no convierte ningún monto**. |
| `period_type` | `weekly`, `semi_monthly` (quincenal) o `monthly`. |
| `period_start_day` | Semanal: 0 (domingo) a 6. Quincenal: 1 a 13; la segunda quincena empieza el día + 15. Mensual: 1 a 28, por ejemplo el día de cobro. |
| `planned_savings` | Cuánto quiere ahorrar **por periodo**, en la moneda principal, como texto. |

```json
{ "main_currency": "BOB" }
```

```json
{ "period_type": "monthly", "period_start_day": 25, "planned_savings": "500.00" }
```

`200` — la configuración como quedó. Repetirla no duplica categorías ni Mis
monedas.

```json
{
  "main_currency": "BOB",
  "period_type": "monthly",
  "period_start_day": 1,
  "planned_savings": "0.00"
}
```

Errores propios:

- `422 invalid_amount`: `planned_savings` negativo o con más decimales que la
  moneda principal.
- `422 validation_error`: un `period_type` que no existe o un día de inicio que no
  sirve para ese periodo.
- `422 onboarding_incomplete`: se mandó el periodo o el ahorro sin haber elegido
  nunca la moneda principal.

### `GET /v1/safe-to-spend?currency=`

Cuánto queda libre en el periodo vigente del usuario, en **una** moneda. Sin
`currency`, la principal.

`200`:

```json
{
  "currency": "BOB",
  "period_starts_on": "2026-10-01",
  "period_ends_on": "2026-10-31",
  "amount": "1000.00",
  "breakdown": {
    "current_balance": "2500.00",
    "pending_recurring": "700.00",
    "planned_savings": "500.00",
    "goal_contributions": "300.00"
  }
}
```

`amount = current_balance − pending_recurring − planned_savings − goal_contributions`.
Es una **estimación**, no un consejo financiero (constitución §8). Puede ser
negativo si las obligaciones pasan el saldo.

| Concepto | De dónde sale |
|---|---|
| `current_balance` | El total de las cuentas en esa moneda (el mismo de `GET /v1/balances`). |
| `pending_recurring` | Los gastos recurrentes comprometidos sin pagar hasta el fin del periodo: los atrasados de periodos anteriores más los que vencen en este (un fijo mensual impago de octubre cuenta dos veces en noviembre). Lo atrasado cuenta desde el periodo en que se creó el fijo. Los ingresos no se restan. |
| `planned_savings` | El ahorro planificado. **Solo en la moneda principal**; en las demás es `0`. |
| `goal_contributions` | Los aportes del periodo a metas en esa moneda, menos los retiros, que no salieron de una cuenta (esos ya bajaron `current_balance`). Las metas cumplidas o archivadas no cuentan. |

- Sin cuentas en esa moneda: `200` con todo en cero, no un error.
- Una moneda que no existe o está desactivada (y sin cuentas tuyas en ella):
  `422 currency_unavailable`.
- Sin moneda principal todavía: `422 onboarding_incomplete`.
- No se guarda nada: se recalcula en cada llamada.
- Es el mismo cálculo que devuelve `POST /v1/onboarding/complete`.

### Reportes: `period`, `on` y `currency`

Los tres reportes de abajo aceptan los mismos parámetros:

- `period=AAAA-MM`: ese mes calendario, del 1 al último día. Otra forma, como
  `2026-13`: `422 validation_error`.
- `on=AAAA-MM-DD`: el periodo financiero del usuario (semanal, quincenal o
  mensual, según `GET /v1/me/settings`) que contiene ese día. Sirve para ir a
  la semana o la quincena anterior: `on` = el día antes de `period_starts_on`.
- Sin `period` ni `on`, el periodo vigente del usuario (el mismo de
  `GET /v1/safe-to-spend`). `period` y `on` juntos: `422 validation_error`.
- `currency`: sin ella, la principal. Una que no existe o está desactivada (y
  sin cuentas tuyas en ella): `422 currency_unavailable`.

La respuesta trae `period_starts_on` y `period_ends_on` para que la app muestre
el rango que se calculó. Nunca se suman monedas distintas: para ver dólares, se
pide con `currency=USD`. Un mes sin movimientos da `200` con todo en cero. Sin
moneda principal todavía: `422 onboarding_incomplete`.

### `GET /v1/reports/position?period=&on=&currency=`

La posición del Map en una moneda. `200`:

```json
{
  "currency": "BOB",
  "period_starts_on": "2026-03-01",
  "period_ends_on": "2026-03-31",
  "available_balance": "4200.00",
  "income": "6000.00",
  "expenses": "2800.00",
  "saved": "1000.00"
}
```

| Campo | De dónde sale |
|---|---|
| `available_balance` | El saldo de hoy de las cuentas en esa moneda (el de `GET /v1/balances`), no el del final del mes. |
| `income`, `expenses` | Los ingresos y los gastos del rango. Las transferencias entre tus cuentas no cuentan. |
| `saved` | Los aportes a metas del rango en esa moneda, menos los retiros. |

### `GET /v1/reports/money-flow?period=&on=&currency=`

`200`:

```json
{
  "currency": "BOB",
  "period_starts_on": "2026-03-01",
  "period_ends_on": "2026-03-31",
  "nodes": {
    "income": "6000.00",
    "needs": "2000.00",
    "lifestyle": "800.00",
    "goals": "1000.00",
    "available": "2200.00"
  }
}
```

- `needs` y `lifestyle` son los gastos según el grupo de su categoría
  (`money_flow_group` en `GET /v1/categories`).
- `goals` es lo mismo que `saved` en `position`.
- `available = income − needs − lifestyle − goals`, así los cuatro suman los
  ingresos. Puede ser negativo si se gastó más de lo que entró.

### `GET /v1/reports/money-flow/categories?group=&period=&on=&currency=`

El detalle de un grupo. `group` es obligatorio: `needs`, `lifestyle` o `income`.
`200`:

```json
{
  "currency": "BOB",
  "period_starts_on": "2026-03-01",
  "period_ends_on": "2026-03-31",
  "group": "needs",
  "items": [
    { "category_id": "01a14030-77aa-7b51-8c0e-1f2a3b4c5d6e", "name": "Vivienda", "amount": "1500.00" },
    { "category_id": null, "name": null, "amount": "500.00" }
  ]
}
```

- De mayor a menor monto. Solo salen las categorías con movimientos en el rango.
- `category_id` y `name` en `null` es **Sin categoría**: los movimientos de las
  categorías borradas, juntos en una fila. Siguen sumando en el grupo.
- Las metas no tienen detalle acá: llegan con la spec 005.

### `GET /v1/money-story?period=&currency=`

El resumen de un mes cerrado. Lo arma el worker el día que el mes cierra en la
zona horaria del usuario (corre todos los días a las 05:30 UTC), así que el mes
en curso nunca tiene historia. `period` es `AAAA-MM`; sin él, el último mes con
historia. `currency` filtra una moneda. `200`:

```json
{
  "period": "2026-09",
  "items": [
    {
      "currency": "BOB",
      "period_starts_on": "2026-09-01",
      "period_ends_on": "2026-09-30",
      "income_total": "5000.00",
      "expense_total": "1500.00",
      "savings_total": "3500.00",
      "savings_rate": "0.7000",
      "is_first_month": false,
      "comparison": {
        "period": "2026-08",
        "income_total": "4000.00",
        "expense_total": "1000.00",
        "savings_total": "3000.00",
        "goals_contributed": "0.00",
        "top_expense_category": { "name": "Supermercado", "total": "1000.00" }
      },
      "highlights": [
        { "key": "saved", "params": { "savings": "3500.00", "rate": "70" },
          "text": "Ahorraste Bs 3500.00: el 70 % de lo que entró." }
      ],
      "generated_at": "2026-10-01T05:30:12Z"
    }
  ]
}
```

- Una historia por moneda con movimientos en el mes, la principal primero. Nunca
  se suman monedas.
- `comparison` es el mes anterior en la misma moneda. Es `null` e
  `is_first_month` es `true` si ese mes no tuvo movimientos en la moneda.
- `savings_rate` es ahorro ÷ ingresos (`"0.7000"` = 70 %); `null` sin ingresos.
- `highlights` trae las frases en orden. `text` ya está armado; `key` y
  `params` sirven si la app quiere mostrarlas distinto. Las claves son
  `summary`, `saved`, `overspent`, `balanced`, `top_expense_category`,
  `goals_contributed`, `income_up`, `income_down`, `income_same`,
  `savings_up`, `savings_down`, `savings_same` y `first_month`.
- Sin historias para ese mes: `items` vacío. Si todavía no hay ninguna,
  `period` es `null`.

### `POST /v1/me/devices`

La app lo llama al abrir sesión y cada vez que el sistema le da un token push
nuevo:

```json
{ "platform": "android", "push_token": "<token de FCM o APNs>", "app_version": "1.0.3", "os_version": "14" }
```

`201`, sin el token (nunca sale de la API):

```json
{
  "id": "01a15c3e-0f5e-7a4b-9c1d-2e3f4a5b6c7d",
  "platform": "android",
  "app_version": "1.0.3",
  "os_version": "14",
  "created_at": "2026-10-21T14:03:00Z",
  "last_seen_at": "2026-10-21T14:03:00Z"
}
```

- `platform` es `ios` o `android`. `app_version` y `os_version` son opcionales.
- El mismo token otra vez devuelve el mismo `id` y actualiza las versiones.
- Si el token estaba en otra cuenta (se cambió de usuario en el mismo
  teléfono), pasa a esta y la otra deja de recibir avisos en ese teléfono.

### `DELETE /v1/me/devices/{id}`

`204`. Lo llama la app al cerrar sesión. Uno de otro usuario, uno que no existe
o uno ya dado de baja responde `404 not_found`.

### `GET /v1/me/notification-settings`

`200`, todos los tipos de aviso, ordenados por `type`:

```json
{
  "items": [
    { "type": "goal.milestone", "description": "Te falta poco para el próximo hito de una meta",
      "enabled": true, "can_disable": true },
    { "type": "security.new_login", "description": "Nuevo inicio de sesión en tu cuenta",
      "enabled": true, "can_disable": false }
  ]
}
```

- `can_disable` en `false` son los avisos de seguridad y de cobro: siempre llegan.
- Los tipos son datos (`notify.notification_types`): la app no debe tener la
  lista fija, sino mostrar la que llega.

### `PUT /v1/me/notification-settings`

```json
{ "items": [{ "type": "goal.milestone", "enabled": false }] }
```

`200` con la lista completa, como el `GET`. Solo cambian los tipos enviados.
Un tipo que no existe o uno con `can_disable` en `false` responde
`422 validation_error` y no cambia ninguno de los enviados.

### Qué llega en un aviso push

No es un endpoint: es lo que la app recibe del sistema. Los workers dejan cada
aviso en `notify.notifications` y el envío (FCM y APNs, todavía pendiente) lo
reparte entre los dispositivos activos. Cada aviso trae `title`, `body` y en
`data` la pantalla que debe abrir la app:

| Tipo | Cuándo | `data` |
|---|---|---|
| `recurring.due_soon` | `remind_days_before` días antes de un gasto recurrente (por defecto 1), a las 09:00 de Bolivia. Uno solo por día de vencimiento. | `{ "screen": "recurring", "due_on": "2026-10-22" }` |
| `money_story.ready` | Cuando se cierra el mes, uno solo aunque haya historias en varias monedas. | `{ "screen": "money_story", "period": "2026-09" }` |
| `goal.milestone` | Al llegar al 25, 50 y 75 % de una meta, una vez por hito. Si un aporte salta varios, solo el más alto. | `{ "screen": "goal", "goal_id": "…" }` |
| `goal.achieved` | Al cumplir una meta. | `{ "screen": "goal", "goal_id": "…" }` |
| `budget.threshold` | Al llegar al 80 % de un presupuesto, una vez por mes. | `{ "screen": "budgets", "budget_id": "…" }` |
| `budget.exceeded` | Al pasar el 100 % de un presupuesto, una vez por mes. Si salta del 50 al 120 %, solo este. | `{ "screen": "budgets", "budget_id": "…" }` |

Con el modo privado (`hide_amounts`), los textos no llevan montos ni nombres:
"Tienes 2 pagos recurrentes mañana" / "Abre MoneyMap para verlos.".

### `GET /v1/me/notifications?before=&limit=`

La pantalla Avisos. Son los mismos avisos de la tabla de arriba, y quedan en la
bandeja **aunque el usuario no tenga un dispositivo registrado**: en ese caso no
se manda push. Un tipo de aviso apagado no se guarda.

| Parámetro | Qué hace |
|---|---|
| `limit` | Cuántos por página, de 1 a 100. Por defecto, 50. |
| `before` | El `created_at` del último aviso de la página anterior, tal cual. Sin él, la primera página. |

`200`:

```json
{
  "items": [
    {
      "id": "01a1a2b0-6c3e-7f00-9d1e-2b6f0f0d8a11",
      "type": "budget.threshold",
      "title": "Usaste el 80 % de Restaurantes",
      "body": "Llevas Bs 400.00 de Bs 500.00 este mes.",
      "data": { "screen": "budgets", "budget_id": "…" },
      "created_at": "2026-10-22T13:20:01.114Z",
      "read_at": null
    }
  ],
  "unread": 1
}
```

`unread` cuenta todos los avisos sin leer, no solo los de la página: sirve para
el puntito de la campana.

### `POST /v1/me/notifications/read`

`204` — todos los avisos sin leer pasan a leídos. Se llama al abrir la pantalla
Avisos.

### `PATCH /v1/accounts/{id}`

Se corrige solo lo que se envía:

```json
{ "name": "Efectivo Bs", "currency": "BOB" }
```

La moneda **solo se corrige mientras la cuenta no se haya usado**: si ya tiene
movimientos, recurrentes o aportes a metas responde `409 account_currency_locked`. Devuelve la
cuenta como quedó, con el saldo intacto.

`{ "archived": true }` la archiva y `{ "archived": false }` la desarchiva:

- Archivada, sale de la lista, de los totales por moneda y de Safe to Spend, y
  ya no recibe transferencias. Su historial queda. Si era la de por defecto, la
  marca pasa a la siguiente cuenta activa.
- Archivar libera su cupo del plan (tarjetas y monedas). Desarchivar lo vuelve
  a ocupar: sin cupo, `409 plan_limit`.

`{ "opening_balance": "3000.00" }` corrige el saldo inicial (BUG-036: el
onboarding deja volver a un paso y cambiar el efectivo o la tarjeta ya
creados). El saldo actual se mueve por la diferencia: con un saldo inicial de
2500, un gasto de 500 y el nuevo saldo inicial 3000, queda en 2500. Con más
decimales que la moneda, `422 invalid_amount`.

### `GET /v1/currencies`

`200` — Mis monedas primero, después las demás activas del catálogo:

```json
[
  {
    "code": "BOB",
    "name": "Boliviano",
    "symbol": "Bs",
    "decimals": 2,
    "is_active": true,
    "is_mine": true,
    "is_main_currency": true
  },
  {
    "code": "USD",
    "name": "Dólar estadounidense",
    "symbol": "$",
    "decimals": 2,
    "is_active": true,
    "is_mine": true,
    "is_main_currency": false
  }
]
```

`is_active`, `is_mine` y `is_main_currency` no los pide el requisito: sin ellos
la app no puede desactivar en pantalla una moneda retirada del catálogo (RF-20)
ni separar Mis monedas del resto.

### `DELETE /v1/me/currencies/{code}`

`204` y la moneda deja de ofrecerse en el selector. No toca ninguna cuenta.
Responde `409 currency_in_use` si es la moneda principal o si tiene cuentas
activas, y `404 not_found` si no está entre las del usuario.

### `PUT /v1/me/currencies/{code}`

Sin cuerpo. Suma la moneda a Mis monedas para que salga primero en el selector,
**sin crear ninguna cuenta**. Es idempotente: repetirlo devuelve lo mismo.

Respeta el límite de monedas del plan (`finance.currencies`, MM-186): con el
gratuito, Mis monedas tiene una sola. Sumar otra responde `409 plan_limit` con
`"feature": "finance.currencies"`; una que ya está siempre responde `200`.

`200` — la moneda como queda en `GET /v1/currencies`:

```json
{
  "code": "USD",
  "name": "Dólar estadounidense",
  "symbol": "$",
  "decimals": 2,
  "is_active": true,
  "is_mine": true,
  "is_main_currency": false
}
```

Una moneda que no existe o está desactivada: `422 currency_unavailable`. No
cuenta para el límite de monedas del plan: ese límite mira las cuentas.

### `POST /v1/transactions`

Un gasto o un ingreso lleva categoría; una transferencia lleva la cuenta de
destino. **La moneda no se manda**: la pone la cuenta. `kind` es `income`,
`expense` o `transfer`. Una categoría borrada o de otro usuario responde
`404 not_found`; una del otro tipo (un gasto en una de ingreso),
`422 validation_error`.

`description` es opcional (hasta 200 caracteres). Se guarda sin espacios al
borde ni repetidos; vacía o solo espacios queda `""`. Si tiene algo, necesita al
menos una letra o un número: `"-"`, `"..."` o un emoji solo responden
`422 validation_error`, también en `PATCH /v1/transactions/{id}` (BUG-050).

```json
{
  "kind": "expense",
  "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
  "category_id": "01a14034-2a10-7c33-9d4e-5f6a7b8c9d0e",
  "amount": "25.50",
  "occurred_on": "2026-10-15",
  "description": "Almuerzo",
  "source": "quick_add"
}
```

Una transferencia, entre cuentas del usuario en la misma moneda:

```json
{
  "kind": "transfer",
  "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
  "transfer_account_id": "01a14034-3b20-7a11-8c22-9d3e4f5a6b7c",
  "amount": "100.00",
  "occurred_on": "2026-10-15",
  "description": "Al ahorro"
}
```

Una transferencia no saca de la cuenta de origen más de lo que tiene:
`422 account_insufficient` (BUG-029). Desde la migración 0025 un gasto común
tampoco (BUG-024): un gasto que pasa el saldo de su cuenta, al crearlo o al
editarlo para que saque más, es `422 account_insufficient`. Un ingreso no tiene
límite.

`201` — el movimiento y el saldo que quedó en cada cuenta. Los saldos los mueven
los triggers de la base, no la API:

```json
{
  "id": "01a14102-9c4b-7010-9b22-a11a46626d7f",
  "kind": "transfer",
  "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
  "category_id": null,
  "transfer_account_id": "01a14034-3b20-7a11-8c22-9d3e4f5a6b7c",
  "amount": "100.00",
  "currency": "BOB",
  "occurred_on": "2026-10-15",
  "description": "Al ahorro",
  "source": "manual",
  "created_at": "2026-10-15T19:20:29.146968Z",
  "account_balance": "900.00",
  "transfer_account_balance": "600.00"
}
```

Con `Idempotency-Key`, dos peticiones iguales devuelven el mismo `id` y crean un
solo movimiento.

### `PATCH /v1/transactions/{id}`

Se corrige solo lo que se envía: `account_id`, `category_id`, `amount`,
`occurred_on`, `description` o `transfer_account_id`. **La moneda no se cambia**:
es la de su cuenta, y si la cuenta nueva es de otra responde
`422 currency_mismatch` dejando el movimiento como estaba. Pasarlo a una
categoría borrada responde `404 not_found`; un movimiento viejo de una categoría
que después se borró se sigue editando. Devuelve `200` con la misma forma que el
`POST`.

### `GET /v1/transactions?account_id=&currency=&category_id=&from=&to=&q=&cursor=&limit=`

El historial. Todos los parámetros son opcionales y se combinan:

| Parámetro | Qué hace |
|---|---|
| `account_id` | Solo los movimientos de esa cuenta, incluidas las transferencias que **llegan** a ella. |
| `currency` | Solo los de esa moneda (`BOB`). Nunca se convierte: los de otras monedas no aparecen. |
| `category_id` | Solo los de esa categoría. |
| `from`, `to` | Desde y hasta esos días (`2026-10-01`), los dos incluidos. `from` después de `to`: `422 validation_error`. |
| `q` | Texto que aparece en la descripción, sin distinguir mayúsculas (sí distingue tildes). `%` y `_` se buscan tal cual. Vacío: sin filtro. |
| `limit` | Cuántos por página, de 1 a 100. Por defecto, 50. |
| `cursor` | El `next_cursor` de la página anterior, tal cual. Sin él, la primera página. Sirve con los mismos filtros: si cambian, se pide desde la primera. |

`200`:

```json
{
  "items": [
    {
      "id": "01a14036-5c1d-7f00-b3e2-9e0c4a7d2f10",
      "kind": "expense",
      "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
      "category_id": "01a14030-77aa-7b51-8c0e-1f2a3b4c5d6e",
      "transfer_account_id": null,
      "amount": "25.50",
      "currency": "BOB",
      "occurred_on": "2026-10-15",
      "description": "Almuerzo",
      "source": "manual",
      "created_at": "2026-10-15T16:20:11.004Z"
    }
  ],
  "next_cursor": "MjAyNi0xMC0xNV8wMWExNDAzNi01YzFk..."
}
```

- Orden: `occurred_on` del más reciente al más viejo y, el mismo día, el último
  registrado primero.
- `next_cursor: null` = no hay más páginas. El cursor es opaco: la app **no lo
  arma ni lo interpreta**, solo lo devuelve. Uno inventado responde
  `422 invalid_cursor`.
- No trae saldos: los da `GET /v1/accounts`.
- En una transferencia, `account_id` es la cuenta de **origen** y
  `transfer_account_id` la de destino. Al mirar el historial de la cuenta de
  destino, la app la muestra como dinero que entra.

### `DELETE /v1/transactions/{id}`

`204` sin cuerpo. El movimiento deja de contar y la base devuelve el monto al
saldo de su cuenta (y de la de destino, si era una transferencia). Si no existe,
ya se borró o es de otro usuario: `404 not_found`.

### `GET /v1/transactions/category-suggestion?description=Netflix&type=expense`

Para completar la categoría mientras se escribe un movimiento. Responde `200`
con la categoría (la misma forma que `GET /v1/categories`) del último
movimiento del usuario con esa descripción y ese tipo, sin distinguir
mayúsculas, tildes ni espacios de sobra. Si no hay ninguno, o su categoría ya
se borró y no hay uno anterior: `204` sin cuerpo. No usa IA: es una consulta
sobre el historial propio.

- `description`: obligatoria, hasta 200 caracteres y con algo más que espacios.
- `type`: `income` o `expense`, obligatorio.

Errores: `422 validation_error` si falta alguno de los dos o viene vacío.

### `GET /v1/countries`

Los países activos del catálogo, ordenados. `currency` es la moneda local: el
onboarding la sugiere como principal.

```json
[{ "code": "BO", "name": "Bolivia", "currency": "BOB" }]
```

### `GET /v1/institutions?country=BO`

Los bancos y billeteras activos de un país, para el `institution_code` de una
tarjeta. `country` son dos letras mayúsculas (si no, `422 validation_error`);
un país sin catálogo responde `[]`.

```json
[{ "code": "bo.bnb", "name": "Banco Nacional de Bolivia", "short_name": "BNB", "kind": "bank" }]
```

### `GET /v1/categories?type=expense`

Las categorías del usuario. `type` es `income` o `expense` (opcional; sin él
vienen las dos). `money_flow_group` es `needs` o `lifestyle` en los gastos y
`null` en los ingresos. `template_key` dice de qué categoría inicial salió
(`salary`, `freelance`, `family_support`, `housing`, `utilities`,
`transport`…), o `null` si la creó el usuario: la app la reconoce por esa clave
y no por el nombre, que el usuario puede cambiar.

```json
[{
  "id": "0192…",
  "name": "Vivienda y alquiler",
  "type": "expense",
  "money_flow_group": "needs",
  "icon": "home",
  "color": "#7C3AED",
  "template_key": "housing"
}]
```

### `POST /v1/categories`

`201` con la categoría, en la misma forma que `GET /v1/categories`
(`template_key` en `null`).

```json
{ "name": "Mascotas", "type": "expense", "money_flow_group": "lifestyle", "icon": "pets", "color": "#F59E0B" }
```

- `name`: de 1 a 60 caracteres; se le quitan los espacios de sobra. Necesita al menos una letra o un número y no lleva emojis (la categoría ya tiene su ícono): si no, `422 validation_error` (BUG-010, BUG-011).
- `type`: `income` o `expense`.
- `money_flow_group`: `needs` o `lifestyle`, obligatorio en un gasto; un
  ingreso no lleva.
- `icon` y `color` son opcionales: sin ellos quedan `label` y `#6B7280`. El
  color va en hexadecimal (`#RRGGBB`).

Errores: `422 validation_error` (gasto sin grupo, ingreso con grupo, nombre
vacío o largo, color mal escrito) y `409 category_name_taken` si ya hay una del
mismo tipo con ese nombre, sin distinguir mayúsculas.

### `PATCH /v1/categories/{id}`

`200` con la categoría. Se corrige solo lo que se envía, con los mismos campos
que al crearla. Pasar a `income` quita el grupo; pasar a `expense` necesita
`money_flow_group` (si no, `422 validation_error`). Si la categoría ya tiene
movimientos (aun borrados) o recurrentes, el tipo no cambia:
`409 category_type_in_use`. La de otro usuario o una borrada: `404 not_found`.

### `DELETE /v1/categories/{id}`

`204` sin cuerpo. La categoría deja de aparecer, y sus movimientos quedan
como están: en los reportes se juntan en la fila sin categoría
(`category_id` y `name` en `null`). Desde entonces no se registran movimientos
ni recurrentes nuevos en ella (`404 not_found`).

Si algún recurrente sin borrar la usa, no se borra:
`409 category_in_use`, con cuántos son en el `detail`. La app puede ofrecer
cambiarlos de categoría (`PATCH /v1/recurring-rules/{id}`) o borrarlos, y
después volver a intentar. Si no existe, ya se borró o es de otro usuario:
`404 not_found`.

### `POST /v1/recurring-rules`

Un ingreso o gasto que se repite. Ingreso o gasto sale de la categoría; la
moneda, de la cuenta (spec 002, RF-21).

```json
{
  "account_id": "0192…",
  "category_id": "0192…",
  "amount": "450.00",
  "description": "Alquiler",
  "frequency": "monthly",
  "start_date": "2026-10-16",
  "auto_post": false
}
```

- `account_id` es opcional: sin él va a la cuenta por defecto del usuario.
- Con `currency` y sin `account_id`, el gasto fijo queda **sin cuenta**
  (BUG-027): `account_id` sale en `null` y la cuenta se elige al pagar.
- `frequency`: `weekly`, `biweekly`, `monthly` (por defecto) o `yearly`.
- `start_date` es opcional: sin ella, el primer vencimiento es hoy en la zona
  horaria del usuario.
- `amount` mayor que cero, como texto, con los decimales de la moneda de la
  cuenta (si no, `422 invalid_amount`).
- `description` de 1 a 120 caracteres después de quitar espacios, con al menos
  una letra o un número: `"-"` o un emoji solo responden `422 validation_error`
  (BUG-003). Lo mismo al corregirlo con `PATCH`.
- `auto_post` está obsoleto: los recurrentes son **recordatorios** y siempre se
  guarda `false`, aunque llegue `true` (al crear o al corregir). La persona lo
  marca pagado con `POST /v1/recurring-rules/{id}/payments`. Uno con
  `next_due_on` de hoy o anterior está vencido: la web lo muestra en "Cuentas
  por pagar" hasta que se paga.

Responde `201` con `id`, `account_id`, `category_id`, `type`, `amount`,
`currency`, `description`, `frequency`, `next_due_on`, `auto_post` y `pending_dates`. Una cuenta o categoría
que no es del usuario, una categoría borrada o una cuenta por defecto que no
existe responden `404 not_found`.

### `GET /v1/recurring-rules`

`200` — los vigentes, el que vence primero arriba. Cada uno con la misma forma
que devuelve `POST /v1/recurring-rules`:

```json
[
  {
    "id": "01a14040-2b3c-7d4e-8f50-6a7b8c9d0e1f",
    "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
    "category_id": "01a14030-77aa-7b51-8c0e-1f2a3b4c5d6e",
    "type": "expense",
    "amount": "1500.00",
    "currency": "BOB",
    "description": "Alquiler",
    "frequency": "monthly",
    "next_due_on": "2026-10-29",
    "auto_post": false,
    "pending_dates": ["2026-10-29", "2026-11-29"]
  }
]
```

`pending_dates` son las veces por pagar, la más vieja primero (spec 003, RF-23):
un gasto fijo sin pagar trae la atrasada y las que vencen hasta el fin del
periodo, las mismas que suma Cuentas por pagar. La primera siempre es
`next_due_on` y es la única que se paga u omite. Un ingreso fijo trae solo
`next_due_on`. Las demás respuestas (`POST`, `PATCH`, `/payments`, `/skip`)
traen solo `next_due_on` en la lista: para ver las siguientes se vuelve a pedir
este `GET`.

### `PATCH /v1/recurring-rules/{id}`

Se corrige solo lo que se envía: `account_id`, `category_id`, `amount`,
`description`, `frequency` y `auto_post`.

```json
{ "amount": "1650.00" }
```

`200` — el recurrente como quedó. La moneda es siempre la de la cuenta: pasarlo
a una cuenta de otra moneda responde `422 currency_mismatch`. Si el recurrente,
la cuenta o la categoría no son del usuario: `404 not_found`. Cambiar la
frecuencia **no mueve `next_due_on`**: cambia los vencimientos que vienen
después.

### `DELETE /v1/recurring-rules/{id}`

`204` sin cuerpo. Deja de vencer; los movimientos que ya registró se quedan.

### `POST /v1/recurring-rules/{id}/payments`

Marca un recurrente como pagado. Los tres campos son opcionales:

```json
{ "amount": "185.40", "occurred_on": "2026-10-05", "account_id": "0192…" }
```

Sin `amount` se usa el monto del recurrente (útil cuando la luz o el agua varían,
se manda el real); sin `occurred_on`, hoy en la zona horaria del usuario.

- `account_id` es la cuenta con la que se paga, en la moneda del recurrente
  (otra moneda: `422 currency_mismatch`). Sin ella, la del recurrente; si el
  recurrente no tiene cuenta, `422 account_required` (BUG-027).
- Un gasto que pasa el saldo de esa cuenta es `422 account_insufficient`
  (BUG-028). Un ingreso no tiene límite.

`201`:

```json
{
  "transaction": {
    "id": "01a14041-7e2a-7b10-9c3d-4f5e6a7b8c9d",
    "kind": "expense",
    "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
    "category_id": "01a14030-77aa-7b51-8c0e-1f2a3b4c5d6e",
    "transfer_account_id": null,
    "amount": "185.40",
    "currency": "BOB",
    "occurred_on": "2026-10-05",
    "description": "Luz",
    "source": "recurring",
    "created_at": "2026-10-05T13:10:44.201Z"
  },
  "recurring_rule": {
    "id": "01a14040-2b3c-7d4e-8f50-6a7b8c9d0e1f",
    "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
    "category_id": "01a14030-77aa-7b51-8c0e-1f2a3b4c5d6e",
    "type": "expense",
    "amount": "180.00",
    "currency": "BOB",
    "description": "Luz",
    "frequency": "monthly",
    "next_due_on": "2026-11-05",
    "auto_post": false
  }
}
```

- Un ingreso recurrente registra un ingreso; un gasto, un gasto. El movimiento
  va a la cuenta del recurrente y sale en `GET /v1/transactions`.
- `next_due_on` pasa al vencimiento siguiente, así deja de contar como pendiente
  en `GET /v1/safe-to-spend`. Si pasa la fecha de fin, el recurrente termina y
  deja de salir en `GET /v1/recurring-rules`.
- No trae saldos: los da `GET /v1/accounts`.
- Acepta `Idempotency-Key`: un reintento no registra dos pagos.
- El que no existe, está dado de baja o es de otro usuario: `404 not_found`.

### `POST /v1/recurring-rules/{id}/skip`

Sin cuerpo. Para lo que ya se pagó por fuera de la app: pasa `next_due_on` al
vencimiento siguiente **sin registrar un movimiento** ni tocar saldos, y esa vez
deja de contar en `pending_recurring` de `GET /v1/safe-to-spend`. Con varias
veces atrasadas, cada llamada omite una.

`200` con el recurrente como quedó (el mismo objeto de `GET /v1/recurring-rules`).

- Si el vencimiento siguiente pasa la fecha de fin, el recurrente termina.
- El que no existe, está dado de baja o es de otro usuario: `404 not_found`.

### `POST /v1/goals`

```json
{ "name": "Viaje a Cusco", "target_amount": "5000.00", "currency": "BOB", "target_date": "2027-06-30", "priority": 1 }
```

- `target_date` es opcional. `priority` va de 1 (la más alta) a 5; sin ella, 3.
- La meta tiene su propia moneda y no se vincula a una cuenta: aportar no mueve
  saldos.
- `target_amount` en cero, negativo o con más decimales que la moneda:
  `422 invalid_amount`. Una moneda que no existe o está desactivada:
  `422 currency_unavailable`.
- El plan gratuito permite **2 metas activas**: la tercera es
  `409 plan_limit` con `feature: "goals.active"`.
- El nombre necesita al menos una letra o un número: "🏠" o "-" solos son
  `422 validation_error` (BUG-006); "Casa 🏠" sí.
- Dos metas vivas no se llaman igual, sin distinguir mayúsculas ni espacios
  de los bordes: `409 goal_name_taken` al crear o al renombrar (BUG-030).

Responde `201` con la meta, en cero:

```json
{
  "id": "01a14060-3c4d-7e5f-8a9b-0c1d2e3f4a5b",
  "name": "Viaje a Cusco",
  "target_amount": "5000.00",
  "current_amount": "0.00",
  "currency": "BOB",
  "target_date": "2027-06-30",
  "priority": 1,
  "status": "active",
  "progress_percent": 0,
  "estimated_completion": null
}
```

### `GET /v1/goals`

Todas las metas vivas, la de prioridad más alta primero, cada una con su moneda:
nunca se suman entre sí. `200` con una lista de metas como la de arriba.

- `current_amount` lo mantiene la base con los aportes.
- `progress_percent` es un entero de 0 a 100, redondeado hacia abajo.
- `status`: `active`, `paused`, `achieved` (cumplida) o `archived`. Las
  cumplidas también salen.
- `estimated_completion`: cuándo llega al ritmo de sus aportes. Es lo que falta
  dividido entre el aporte mensual promedio, redondeado hacia arriba a meses
  enteros y contado desde hoy en la zona del usuario. El promedio usa solo los
  meses con aporte: 300 en enero y 400 en junio son 350 por mes. Viene en
  `null` si la meta no tiene aportes o no está `active`. Es una fecha, pero la
  app muestra el mes: *alcanzarás tu meta en marzo de 2027*.

### `PATCH /v1/goals/{id}`

Se corrige solo lo que se envía: `name`, `target_amount`, `target_date` y
`priority`. La moneda no se cambia, porque los aportes van en ella. Sin ningún
campo: `422 validation_error`. Si el objetivo nuevo queda igual o por debajo de
lo ahorrado, la meta queda cumplida. Responde `200` con la meta como quedó.

### `DELETE /v1/goals/{id}`

`204`. La meta y sus aportes dejan de contar en Safe to Spend y en los
reportes. No cambia ninguna cuenta. Si la meta tiene saldo
(`current_amount > 0`), responde `409 goal_has_saved` y no la borra: primero
hay que retirar ese saldo a una cuenta con `POST /v1/goals/{id}/withdrawals`.

### `POST /v1/goals/{id}/contributions`

```json
{ "amount": "2500.00", "contributed_on": "2026-10-01", "account_id": "01a14050-…" }
```

Sin `contributed_on`, hoy en la zona horaria del usuario. El monto va en la
moneda de la meta. Con `account_id`, el aporte sale de esa cuenta: su saldo baja
en la misma transacción. La cuenta tiene que ser de la moneda de la meta
(`422 currency_mismatch`); una que no existe o es de otro, `404`. Sin
`account_id` (clientes viejos) no se toca ninguna cuenta. `201`:

```json
{
  "contribution": { "id": "01a14061-4d5e-7f60-8b1c-2d3e4f5a6b7c", "amount": "2500.00", "contributed_on": "2026-10-01" },
  "goal": {
    "id": "01a14060-3c4d-7e5f-8a9b-0c1d2e3f4a5b",
    "name": "Viaje a Cusco",
    "target_amount": "5000.00",
    "current_amount": "2500.00",
    "currency": "BOB",
    "target_date": "2027-06-30",
    "priority": 1,
    "status": "active",
    "progress_percent": 50,
    "estimated_completion": "2027-03-18"
  }
}
```

- Un aporte llega como mucho a lo que le falta a la meta
  (`target_amount − current_amount`). El que lo completa justo se acepta y la
  meta queda `achieved` con `progress_percent: 100`. Uno que lo pasa:
  `422 contribution_exceeds_remaining`, con lo que falta en `detail` (BUG-049).
- A una meta `achieved` o `archived` no se aporta: `422 goal_closed`. Retirar
  de ella sí se puede.
- El monto va siempre en la moneda de la meta y no se convierte: la cuenta
  también tiene que ser de esa moneda.
- Si un retiro o un objetivo más alto la deja por debajo del objetivo, la meta
  vuelve a `active` y `achieved_at` queda en `null`; vuelve a estimar su fecha.
- Cero, negativo o con más decimales que la moneda: `422 invalid_amount`. Para
  sacar dinero está `POST /v1/goals/{id}/withdrawals`.
- Con `account_id`, no puede pasar el saldo de la cuenta: `422
  account_insufficient`, como un gasto o una transferencia (BUG-024).
  Dos aportes a la vez desde la misma cuenta esperan su turno.
- Acepta `Idempotency-Key`: un reintento no aporta dos veces.
- Cuenta en los reportes (`saved`, `goals`) del periodo del aporte. En
  `GET /v1/safe-to-spend` (`goal_contributions`) solo cuentan los aportes sin
  cuenta: los que salieron de una ya bajaron `current_balance`.
- No crea un movimiento: ahorrar no es un gasto.

### `POST /v1/goals/{id}/withdrawals`

```json
{ "amount": "200.00", "account_id": "01a14050-…", "withdrawn_on": "2026-10-29" }
```

Lo acumulado en la meta vuelve a una cuenta de su moneda: la meta baja y el
saldo de la cuenta sube. `account_id` es obligatorio. Responde `201` con la
misma forma que el aporte, con `contribution.amount` en negativo
(`"-200.00"`).

- Más de lo acumulado: `422 goal_insufficient`. Cero o negativo:
  `422 invalid_amount`. Cuenta de otra moneda: `422 currency_mismatch`.
  Cuenta archivada, borrada o de otro usuario: `404`.
- Dos retiros a la vez esperan su turno: entre los dos nunca sacan más de lo
  acumulado.
- Una meta cumplida no se reabre al retirar (migración 0007).
- Acepta `Idempotency-Key`.

### `GET /v1/goals/movements?currency=&account_id=&from=&to=&cursor=&limit=`

REQ-056: el filtro "Metas" de Movimientos. Un aporte saca dinero de una cuenta y un retiro lo devuelve, pero no son movimientos de `/v1/transactions`: esta lista los muestra, del más reciente al más viejo. Entran también los de una meta borrada, porque el dinero igual se movió.

| Parámetro | Qué hace |
|---|---|
| `currency` | Solo los de metas en esa moneda (`BOB`). Nunca se convierte. |
| `account_id` | Solo los que salieron de esa cuenta o volvieron a ella. |
| `from`, `to` | Desde y hasta esos días, los dos incluidos. `from` después de `to`: `422 validation_error`. |
| `limit` | Cuántos por página, de 1 a 100. Por defecto, 50. |
| `cursor` | El `next_cursor` de la página anterior, tal cual. Otro texto: `422 invalid_cursor`. Sirve con los mismos filtros. |

`200`:

```json
{
  "items": [
    {
      "id": "01a14040-2b3c-7d10-9e8f-0a1b2c3d4e5f",
      "kind": "contribution",
      "goal_id": "01a14038-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
      "goal_name": "Viaje a Cusco",
      "account_id": "01a14034-1f22-7d10-8f2e-2b6f0f0d8a11",
      "amount": "300.00",
      "currency": "BOB",
      "occurred_on": "2026-10-15",
      "created_at": "2026-10-15T16:20:11.004Z"
    }
  ],
  "next_cursor": null
}
```

- `kind`: `contribution` (salió de la cuenta hacia la meta) o `withdrawal` (volvió de la meta a la cuenta).
- `amount` va siempre positivo, en la moneda de la meta; `kind` dice hacia dónde fue.
- `account_id` es `null` en los aportes de antes de que salieran de una cuenta.

### `POST /v1/affordability-checks`

Can I Afford It?: cuánto cuesta una compra frente a lo que realmente hay
disponible. **No guarda nada**: ni movimiento ni escenario. Es una estimación
con sus supuestos, no un consejo.

```json
{ "amount": "4000.00", "currency": "BOB", "category_id": null }
```

Cada consulta que pasa las validaciones cuenta contra el plan
(`planning.affordability_checks`, MM-186: 10 al mes en el gratuito). Sin
consultas en el mes: `409 plan_limit` con `"feature": "planning.affordability_checks"`.

`category_id` es opcional y, si va, tiene que ser una categoría de gasto (si no:
`422 validation_error`). Hoy no cambia el cálculo. `200`:

```json
{
  "verdict": "not_yet",
  "currency": "BOB",
  "amount": "4000.00",
  "safe_to_spend": "500.00",
  "breakdown": {
    "current_balance": "1000.00",
    "pending_recurring": "300.00",
    "planned_savings": "0.00",
    "goal_contributions": "200.00"
  },
  "income_in_period": "3000.00",
  "remaining_variable_spending": "340.00",
  "available": "3160.00",
  "available_after": "-840.00",
  "goal_impacts": [
    { "goal_id": "01a14060-3c4d-7e5f-8a9b-0c1d2e3f4a5b", "name": "Viaje", "amount": "200.00", "delay_months": 1 },
    { "goal_id": "01a14062-5e6f-7a80-9b1c-2d3e4f5a6b7c", "name": "Fondo", "amount": "300.00", "delay_months": 0 }
  ],
  "estimated_on": "2026-11-20",
  "projection": [
    { "on": "2026-10-15", "balance": "3160.00" },
    { "on": "2026-11-15", "balance": "2610.00" },
    { "on": "2026-11-20", "balance": "5426.67" }
  ],
  "assumptions": {
    "period_starts_on": "2026-10-01",
    "period_ends_on": "2026-10-31",
    "monthly_income": "3000.00",
    "monthly_expenses": "1300.00",
    "monthly_goals": "500.00",
    "monthly_planned_savings": "0.00",
    "monthly_surplus": "1200.00",
    "limited_history": false
  }
}
```

`verdict`, según PRD §6.13:

| `verdict` | Cuándo | Qué trae |
|---|---|---|
| `affordable` | El monto entra en `available`. | `available_after`: lo que queda después de todo. |
| `not_yet` | El monto supera `available`. | `available_after` negativo, `goal_impacts` informativos y `estimated_on` si hay sobrante mensual y se junta en 5 años. |

- `available` es `safe_to_spend + income_in_period − remaining_variable_spending`.
  `safe_to_spend` sale del motor de la spec 003 y llega con su `breakdown`
  (`current_balance`, `pending_recurring`, `planned_savings`,
  `goal_contributions`) para explicar el número; `income_in_period` son los
  recurrentes de ingreso que todavía faltan llegar en el periodo; y
  `remaining_variable_spending` es el gasto variable promedio que falta gastar
  hasta el fin del periodo. Con esto el "sí" no depende solo del saldo: cuenta
  el sueldo que falta llegar, pero también lo que falta gastar.
- `assumptions.monthly_surplus` es el sobrante mensual real:
  `monthly_income − monthly_expenses − monthly_goals − monthly_planned_savings`.
  `monthly_income` y los recurrentes de `monthly_expenses` son el **promedio de
  los próximos 12 meses**: un seguro anual o un aguinaldo cuentan su parte en
  cada mes. `monthly_expenses` suma además el gasto variable promedio.
  `monthly_planned_savings` es el ahorro planificado llevado a 30 días (solo
  existe en la moneda principal). Es para mostrar: la fecha no se calcula con él.
- `estimated_on` es el **día** en que el saldo simulado llega al precio. La
  simulación arranca en `available`, que ya cuenta todo hasta
  `period_ends_on`; desde el día siguiente suma y resta cada recurrente el día
  que vence, y resta el gasto variable, las metas y el ahorro planificado de a un
  trigésimo por día. Suele caer el día que llega un ingreso. `null` si
  `monthly_surplus` no es positivo o si no se junta en 5 años.
- `projection` es la curva de esa misma simulación: un punto hoy (el
  `available`, no el saldo de las cuentas), uno por mes desde hoy y el último en
  `estimated_on`, que siempre llega al precio. Nunca hay dos puntos del mismo mes
  después de hoy: el de `estimated_on` reemplaza al punto mensual de su mes.
  Vacío en `affordable` o sin fecha.
- `goal_impacts` es **información**, no una forma de pagar: dice de dónde
  saldría lo que falta si se usaran los aportes del periodo a metas y cuántos
  meses se atrasaría cada una. Se informan **de la menor prioridad a la mayor**
  (5 antes que 1) y cada una como máximo en lo que se le aportó en el periodo.
  En `affordable` va vacío.
- `delay_months` sale de la misma cuenta que `estimated_completion` de las metas;
  `null` si la meta no tiene ritmo de aportes.
- `limited_history` es `true` cuando no hay meses completos de historial: el
  gasto variable sale de lo que va del mes.
- Todo en la moneda pedida, nunca convertido. Sin cuentas en esa moneda,
  `safe_to_spend` y `available` son `"0.00"`.
- `amount` mayor que cero (si no, `422 validation_error`); con más decimales
  que la moneda, `422 invalid_amount`. Moneda desactivada:
  `422 currency_unavailable`.

### `POST /v1/budgets`

```json
{ "category_id": "…", "amount": "400.00", "currency": "BOB" }
```

Un límite por mes para una categoría de gasto. Sin `currency`, va en la moneda
principal, y solo cuentan los gastos en esa moneda: no hay conversión. Se repite
todos los meses hasta que se corrige o se borra, y lo no gastado no pasa al mes
siguiente. Responde `201` con el presupuesto como en `GET /v1/budgets`.

| Respuesta | Cuándo |
|---|---|
| `404 not_found` | La categoría no existe, es de otro o está borrada |
| `409 budget_exists` | Ya hay un presupuesto para esa categoría en esa moneda |
| `409 plan_limit` | Ya tiene los que permite su plan (3 en el gratuito, provisional), con `feature: "planning.budgets"` |
| `422 validation_error` | La categoría es de ingreso |
| `422 invalid_amount` | Más decimales que los de la moneda |

Si se borra la categoría, se borran sus presupuestos.

### `GET /v1/budgets`

Los presupuestos del mes en curso, en la zona horaria del usuario, por nombre de
categoría:

```json
[
  {
    "id": "…",
    "category_id": "…",
    "category_name": "Supermercado",
    "currency": "BOB",
    "amount": "400.00",
    "spent": "240.00",
    "remaining": "160.00",
    "percent_used": 60,
    "pace": { "status": "too_fast", "projected_total": "600.00" },
    "period_starts_on": "2026-11-01",
    "period_ends_on": "2026-11-30",
    "daily": [
      { "on": "2026-11-03", "spent": "90.00", "cumulative": "90.00" },
      { "on": "2026-11-10", "spent": "150.00", "cumulative": "240.00" }
    ],
    "alert_at_80": true,
    "alert_at_100": true
  }
]
```

- `alert_at_80` y `alert_at_100`: si avisa al llegar al 80 % y al pasar el
  100 % de ese presupuesto. Si el del 100 % está apagado y se pasa, avisa el del
  80 % (si está encendido y no se avisó antes). Los ajustes generales de
  `/v1/me/notification-settings` siguen mandando: apagado ahí, no avisa ningún
  presupuesto.

- `daily` es el gasto día por día del mes, para dibujar la línea real: solo los
  días con gasto, en orden. `cumulative` es lo gastado desde el 1 hasta ese día;
  el último es igual a `spent`.
- Si se pasó, `remaining` es negativo y `percent_used` pasa de 100.
- `pace` es el Spending Pace. Compara lo gastado (60 %) con lo que va del mes
  (día 12 de 30, 40 %): `on_track` si va igual o más lento, `a_bit_fast` hasta
  10 puntos más rápido y `too_fast` si va más rápido que eso. Los primeros 3 días
  del mes `status` es `null`.
- `projected_total` es lo que se gastaría al cierre a este ritmo.

El tono lo pone la app: describe el ritmo y no juzga.

### `PATCH /v1/budgets/{id}`

`{ "amount": "500.00", "alert_at_100": false }`. Se cambia solo lo que se envía, y
al menos un campo. El monto vale desde el mes en curso. Para otra categoría u
otra moneda, se crea otro presupuesto. Responde `200` como en la lista. Si es de
otro o ya está borrado: `404`. `POST /v1/budgets` también acepta `alert_at_80` y
`alert_at_100`; sin ellos, los dos encendidos.

### `DELETE /v1/budgets/{id}`

`204`. Los gastos no cambian. Si es de otro o ya está borrado: `404`.

### `POST /v1/what-if`

Simula uno o dos cambios y muestra su efecto sin guardar ni cambiar nada:

```json
{
  "currency": "BOB",
  "changes": [
    { "type": "recurring_expense", "monthly_change": "200.00" },
    { "type": "goal_contribution", "goal_id": "…", "monthly_amount": "300.00" }
  ]
}
```

| `type` | Campo | Qué simula |
|---|---|---|
| `income` | `monthly_change` | El ingreso mensual sube (positivo) o baja (negativo) |
| `recurring_expense` | `monthly_change` | Un gasto fijo nuevo (positivo) o uno que se quita (negativo) |
| `category_spending` | `category_id`, `monthly_change` | Gastar más (positivo) o menos (negativo) por mes en una categoría de gasto. Mueve el dinero igual que un gasto fijo. Una categoría que no es de gasto, o de otro usuario: `422 validation_error` |
| `goal_contribution` | `goal_id`, `monthly_amount` | El aporte mensual nuevo a una meta |
| `planned_savings` | `amount` | El ahorro planificado nuevo del periodo |

Sin `currency`, se usa la moneda principal. Responde `200`:

```json
{
  "currency": "BOB",
  "safe_to_spend": "500.00",
  "safe_to_spend_after": "-200.00",
  "goals": [
    {
      "goal_id": "…",
      "name": "Viaje",
      "estimated_completion": "2028-10-21",
      "estimated_completion_after": null,
      "delay_months": null
    }
  ],
  "forecast": [
    { "days": 30, "on": "2026-11-20", "balance": "500.00", "balance_after": "0.00" },
    { "days": 60, "on": "2026-12-20", "balance": "0.00", "balance_after": "-1000.00" },
    { "days": 90, "on": "2027-01-19", "balance": "-500.00", "balance_after": "-2000.00" }
  ],
  "goes_negative_on": "2026-12-21",
  "goes_negative_on_after": "2026-11-21",
  "assumptions": {
    "period_starts_on": "2026-10-01",
    "period_ends_on": "2026-10-31",
    "monthly_savings": "500.00",
    "monthly_savings_after": "300.00"
  }
}
```

- Cada cambio mueve Safe to Spend por la diferencia con lo de hoy.
- Si Safe to Spend queda negativo, lo que falta sale de los aportes mensuales a
  las metas, primero de la de menor prioridad.
- `delay_months` es positivo si la meta se atrasa y negativo si se adelanta. Es
  `null` si alguna de las dos fechas no existe, por ejemplo porque la meta se
  queda sin ritmo.
- `forecast` es el de `GET /v1/forecast`, antes y después. El ingreso y los
  gastos fijos cambian lo que entra a las cuentas; el aporte a una meta y los
  recortes cambian lo que se aparta. El ahorro planificado no cambia el saldo,
  solo Safe to Spend.
- `goes_negative_on_after` es la fecha aproximada en que el saldo bajaría de 0
  con los cambios. Es `null` si no baja en 90 días.

| Respuesta | Cuándo |
|---|---|
| `404 not_found` | La meta no existe, es de otro o es de otra moneda |
| `422 validation_error` | Ningún cambio, más de dos o un `type` que no existe |
| `422 invalid_amount` | Más decimales que los de la moneda |
| `422 onboarding_incomplete` | Todavía no tiene moneda principal |

### `GET /v1/what-if/baseline?period_type=&on=&currency=&account_id=`

Lo de partida del simulador de What If?: lo que entró y salió por categoría en
un periodo, y lo que se aporta a cada meta. Los cambios los mueve la app sobre
estos montos; no se guarda nada. `200`:

```json
{
  "currency": "BOB",
  "period_type": "semi_monthly",
  "periods_per_year": 24,
  "period_starts_on": "2026-03-01",
  "period_ends_on": "2026-03-15",
  "account_id": null,
  "income": [
    { "category_id": "…", "name": "Salario", "group": "income", "amount": "6000.00" }
  ],
  "expenses": [
    { "category_id": "…", "name": "Vivienda", "group": "needs", "amount": "1500.00" },
    { "category_id": null, "name": null, "group": "lifestyle", "amount": "800.00" }
  ],
  "goals": [
    {
      "goal_id": "…",
      "name": "Fondo",
      "target_amount": "5000.00",
      "current_amount": "300.00",
      "monthly_contribution": "300.00",
      "period_contribution": "150.00"
    }
  ]
}
```

| Parámetro | Qué hace |
|---|---|
| `period_type` | `weekly`, `semi_monthly` o `monthly`. Sin él, el que configuró el usuario (`GET /v1/me/settings`). Si es su tipo, el periodo empieza en su `period_start_day`; si es otro, el día 1 (quincenas 1-15 y 16-fin) o el lunes. |
| `on` | Un día del periodo (`AAAA-MM-DD`). Sin él, hoy en su zona horaria. |
| `currency` | Sin ella, la principal. Nunca se suman monedas distintas. |
| `account_id` | Solo los movimientos de esa cuenta (el efectivo o una tarjeta). Sin él, todas las de la moneda. |

- `income` y `expenses` van de mayor a menor; `expenses` junta Necesidades y
  Estilo de vida. Solo salen las categorías con movimientos en el periodo.
  `category_id` y `name` en `null` es **Sin categoría** (las borradas).
- `goals` son las metas activas de la moneda, por prioridad. No dependen de
  `account_id`. `monthly_contribution` es el aporte mensual promedio de los
  meses con aporte (el mismo ritmo de `estimated_completion` en
  `GET /v1/goals`); `null` si todavía no tiene aportes.
  `period_contribution` es ese ritmo pasado al periodo
  (× 12 ÷ `periods_per_year`); `0.00` sin aportes.
- `periods_per_year` (52, 24 o 12) sirve para pasar un monto del periodo a
  mensual, por ejemplo para estimar cuándo se llega a una meta.

| Respuesta | Cuándo |
|---|---|
| `404 not_found` | La cuenta no existe, es de otro, está borrada o es de otra moneda |
| `422 validation_error` | Un `period_type` que no existe o un `on` que no es fecha |
| `422 currency_unavailable` | Una moneda que no existe o está desactivada (y sin cuentas tuyas en ella) |
| `422 onboarding_incomplete` | Todavía no tiene moneda principal |

### `GET /v1/forecast?currency=`

El saldo proyectado a 30, 60 y 90 días, en la moneda pedida o, sin ella, en la
principal. Es una estimación, nunca una recomendación:

```json
{
  "currency": "BOB",
  "balance": "2500.00",
  "points": [
    {
      "days": 30,
      "on": "2026-11-20",
      "balance": "3000.00",
      "recurring_income": "3000.00",
      "recurring_expenses": "700.00",
      "goal_contributions": "300.00",
      "variable_spending": "1500.00"
    },
    {
      "days": 60,
      "on": "2026-12-20",
      "balance": "3500.00",
      "recurring_income": "6000.00",
      "recurring_expenses": "1400.00",
      "goal_contributions": "600.00",
      "variable_spending": "3000.00"
    },
    {
      "days": 90,
      "on": "2027-01-19",
      "balance": "4000.00",
      "recurring_income": "9000.00",
      "recurring_expenses": "2100.00",
      "goal_contributions": "900.00",
      "variable_spending": "4500.00"
    }
  ],
  "goes_negative_on": null,
  "limited_history": false,
  "assumptions": {
    "recurring_income": "3000.00",
    "recurring_expenses": "700.00",
    "goal_contributions": "300.00",
    "variable_spending": "1500.00",
    "history_months": 3
  }
}
```

- La fórmula es saldo de hoy + ingresos recurrentes − gastos recurrentes −
  aportes a metas − gasto variable promedio.
- Cada recurrente cuenta en la fecha en que vence. Un **gasto** vencido que
  sigue pendiente cuenta hoy; un **ingreso** vencido que no se marcó recibido
  no cuenta (no se sabe si llega). Los siguientes sí.
- El gasto variable es el que no sale de un recurrente: el promedio de los
  últimos 3 meses completos con movimientos.
- `goes_negative_on` es la fecha aproximada en que el saldo bajaría de 0. Es
  `null` si no baja en los 90 días.
- Con menos de un mes completo de datos, `limited_history` es `true` y el gasto
  variable sale de lo que va del mes. La app tiene que avisar que la estimación
  mejora con más historial.
- Cada punto trae su desglose: lo que entra y sale **desde hoy hasta ese día**.
  `balance` = saldo de hoy + `recurring_income` − `recurring_expenses` −
  `goal_contributions` − `variable_spending`; puede diferir en un centavo por el
  redondeo. Una meta que llega a su objetivo deja de sumar aportes.
- `assumptions` son los supuestos que la app muestra junto al gráfico.

Si todavía no tiene moneda principal: `422 onboarding_incomplete`.

### `GET /v1/onboarding`

Hasta dónde llegó el onboarding. La app lo pide al iniciar sesión: si
`completed` es `true` va al Map; si no, retoma en el primer paso que falta.

```json
{
  "completed": false,
  "completed_at": null,
  "main_currency": "BOB",
  "accounts": 1,
  "income_rules": 0,
  "expense_rules": 0
}
```

`main_currency` es `null` mientras no se haya hecho el paso 1.

### `POST /v1/onboarding/complete`

Marca el onboarding como terminado y responde `201` con el resumen del periodo
vigente en la moneda principal. Idempotente: repetirlo no cambia la fecha y
devuelve el resumen de nuevo.

```json
{
  "currency": "BOB",
  "period_starts_on": "2026-10-01",
  "period_ends_on": "2026-10-31",
  "income": "3000.00",
  "committed": "700.00",
  "balance": "2500.00",
  "planned_savings": "0.00",
  "goal_contributions": "0.00",
  "safe_to_spend": "1800.00"
}
```

- `income` y `committed`: los recurrentes de ingreso y de gasto que vencen en
  el periodo, solo en la moneda principal. Sin recurrentes son `"0.00"`.
- `safe_to_spend` = `balance − committed − planned_savings − goal_contributions`
  (PRD §6.10).
- Sin moneda principal o sin ninguna cuenta responde
  `422 onboarding_incomplete` con `missing_step`: `currency` o `accounts`.

### `GET /v1/plans`

`200` — los planes públicos, del gratuito (`tier` 0) al más alto. **Los planes de
pago son provisionales** (spec 011): nombres, precios y límites cambian con un
UPDATE en la base, sin tocar la app, así que la app no debe escribirlos en su
código.

```json
[
  {
    "code": "paid_1",
    "name": "Plus",
    "description": "Más tarjetas, monedas y metas.",
    "tier": 1,
    "prices": [
      {
        "currency": "BOB",
        "monthly": "29.00",
        "yearly": "290.00",
        "yearly_per_month": "24.17",
        "yearly_saving_pct": "16.7",
        "purchasable": false
      }
    ],
    "features": [
      { "key": "finance.cards", "description": "Tarjetas activas", "enabled": true, "limit": 3, "period": "total" },
      { "key": "reports.money_story", "description": "Monthly Money Story", "enabled": true, "limit": null, "period": null }
    ]
  }
]
```

- `prices` está vacío en el gratuito. `yearly` puede ser `null` si un plan solo
  se vende por mes.
- `purchasable: false`: el precio todavía no está en App Store ni en Play Store.
  La app muestra el plan pero no deja comprarlo.
- En `features`, `limit: null` es ilimitado. `period` es `total` (cuántos puede
  tener a la vez: tarjetas, monedas, metas, presupuestos), `month` (cuántos usos
  por mes: dictados, Can I Afford It?) o `null` (funcionalidad de sí o no; mirar
  `enabled`).

### `GET /v1/me/plan`

`200` — el plan que vale hoy. Sin suscripción vigente es el gratuito con
`status: "free"`. Las `features` son las de `GET /v1/plans` más `used`, para
mostrar "1 de 1 tarjetas":

```json
{
  "code": "free",
  "name": "Gratuito",
  "tier": 0,
  "status": "free",
  "has_paid_access": false,
  "billing_period": null,
  "current_period_end": null,
  "auto_renew": null,
  "features": [
    { "key": "finance.cards", "description": "Tarjetas activas", "enabled": true, "limit": 1, "period": "total", "used": 1 }
  ]
}
```

`status` puede ser también `trialing`, `active`, `grace_period`, `on_hold` o
`paused`. Con `on_hold` y `paused` el usuario ve su estado pero tiene los límites
del gratuito hasta que se recupere el pago.

### `PUT /v1/me/plan`

Elige otro plan (MM-186). **Todavía no hay cobros**: el cambio vale al instante,
con una suscripción `provider: "internal"`, mensual y con renovación automática.

```json
{ "code": "paid_1" }
```

`200` — el plan nuevo, igual que `GET /v1/me/plan`. Elegir `free` termina la
suscripción. Al bajar de plan **no se borra nada**: lo que ya existe queda y, si
pasa el límite nuevo, no se puede crear más (`409 plan_limit`) hasta estar
dentro.

Errores: `404 not_found` si el plan no existe o no es público;
`409 plan_managed_by_store` si la suscripción viva es de App Store o Play Store
(se cambia en la tienda).

### Panel de administrador de planes (spec 013, MM-189)

Un solo administrador entra con el mismo login: `GET /v1/me` responde
`"is_admin": true` para él. Para cualquier otro usuario, las rutas `/v1/admin`
responden `404 not_found`, así no se revela que existen. Cada cambio queda en
`core.audit_log`. No se crean ni se borran planes.

#### `GET /v1/admin/plans`

`200` — del gratuito al más alto:

```json
[
  {
    "code": "paid_1",
    "name": "Plus",
    "description": "Más tarjetas, monedas y metas.",
    "tier": 1,
    "is_public": true,
    "subscribers": 12,
    "prices": [{ "period": "month", "currency": "BOB", "amount": "29.00" }],
    "features": [
      { "key": "goals.active", "description": "Metas activas", "kind": "limit", "period": "total", "enabled": true, "limit": 10 },
      { "key": "notify.push", "description": "Notificaciones push", "kind": "boolean", "period": null, "enabled": true, "limit": null }
    ]
  }
]
```

`subscribers` del gratuito = los usuarios sin una suscripción vigente.

#### `PATCH /v1/admin/plans/{code}`

```json
{ "name": "Plus", "description": "Más tarjetas, monedas y metas.", "is_public": true }
```

`204`. El gratuito no se puede ocultar: `409 free_plan_required`.

#### `PUT /v1/admin/plans/{code}/features/{key}`

```json
{ "enabled": true, "limit": 5 }
```

`204`. `limit: null` = ilimitado. Una funcionalidad de sí o no (`kind: "boolean"`)
no lleva límite: `422 invalid_limit`. Bajar un límite **no borra nada**: lo que
ya existe queda y no se puede crear más (`409 plan_limit`) hasta estar dentro.
Vale al instante para todos los usuarios de ese plan.

#### `PUT /v1/admin/plans/{code}/prices/{period}/{currency}`

`period` es `month` o `year`. Cuerpo `{ "amount": "35.00" }` → `204`. El precio
anterior se cierra y se abre otro: las suscripciones que ya existen siguen con
el suyo. El gratuito no tiene precio: `409 free_plan_required`.

#### `GET /v1/admin/plan-changes?limit=50`

`200` — los últimos cambios (hasta 200), el más nuevo primero:
`{ "occurred_at", "entity", "action", "changes" }`, con `changes` por campo como
`[antes, después]` (en un alta, la fila).

### Registro por voz (spec 012)

El usuario dicta o escribe una frase ("gasté 50 en almuerzo con la Visa") y la
API devuelve el movimiento prellenado para confirmarlo. El proceso corre en el
worker con modelos propios (voz a texto y LLM): la app crea el dictado, consulta
hasta que termina y, si el usuario confirma, guarda el movimiento con
`POST /v1/transactions` y lo enlaza.

```
POST /v1/voice-entries  ──202──▶ GET /v1/voice-entries/{id} (cada 1 s)
                                   ├─ extracted ─▶ el usuario confirma ─▶ POST /v1/transactions (source: "voice")
                                   │                                     └▶ POST /v1/voice-entries/{id}/confirm
                                   └─ failed ────▶ abrir Quick Add vacío (la cuota se devolvió)
```

Cada dictado o frase descuenta uno de la cuota del mes (`ai.voice_entries`). El
plan gratuito no dicta: `409 plan_limit` con `feature: "ai.voice_entries"`
(migración 0023). Si fallan todos los modelos, la cuota se devuelve.

#### `POST /v1/voice-entries`

El audio crudo en el cuerpo, con `Content-Type: audio/*` (m4a, ogg, webm o wav),
hasta 2 MB y 60 s. El audio no se guarda. Responde `202` con el dictado en
`received` (la misma forma que el `GET`, con `transcript`, `extraction` y
`transaction_id` en `null`).

| Error | Cuándo |
|---|---|
| `422 invalid_audio` | Sin `Content-Type: audio/*`, vacío o de más de 2 MB |
| `409 plan_limit` | Ya usó los dictados del mes, con `feature: "ai.voice_entries"` |
| `503 voice_queue_unavailable` | La cola no aceptó el dictado; la entrada queda `failed` y se devuelve la cuota |

#### `POST /v1/voice-entries/text`

`{ "text": "gasté 50 en almuerzo" }` (1 a 500 caracteres). Igual que el
anterior, sin el paso de voz a texto: `input_type: "text"` y la frase en
`transcript`.

#### `GET /v1/voice-entries/{id}`

El dictado como va. `status`: `received` → `transcribed` → `extracted`, o
`failed`; después `confirmed` o `discarded`. Con `extracted`:

```json
{
  "status": "extracted",
  "transcript": "Gasté 50 bolivianos en almuerzo con la Visa ayer.",
  "extraction": {
    "kind": "expense",
    "amount": "50",
    "currency": "BOB",
    "category_id": "01a1…",
    "account_id": null,
    "description": "Almuerzo",
    "occurred_on": "2026-10-22",
    "missing": ["account_id"],
    "multiple": false,
    "movements": [{ "kind": "expense", "amount": "50", "…": "…" }]
  }
}
```

- `missing`: lo que la frase no dijo, lo que el modelo no supo o un id que no es
  del usuario. La app lo pide antes de guardar; nunca adivina.
- `currency` es una de las monedas del usuario. Si nombra una moneda que ninguna
  de sus cuentas tiene, `account_id` queda en `missing`: la app le pide elegir o
  crear una cuenta en esa moneda, sin convertir.
- `movements`: todos los movimientos de la frase ("pollo 15, aceite 13 y mi
  sueldo 4500" son tres), en el orden en que se dijeron y como mucho cinco, cada
  uno con los mismos campos y su propio `missing`. Arriba va el primero, como
  antes, y `multiple: true` cuando hay más de uno. La app los confirma uno por
  uno; `/confirm` enlaza el primero. Un dictado guardado antes de este cambio
  trae `movements` vacío.
- El método de pago (efectivo o tarjeta) es el `type` de la cuenta elegida: no
  hay un campo aparte.
- Cuánto tarda: unos 10 a 15 s con el modelo cargado y hasta 40 s si estaba
  frío. Con los reintentos y el respaldo, el peor caso pasa el minuto. La app
  consulta cada 1 o 2 s y se rinde a los **90 s**, ofreciendo Quick Add.
- Cuántos dictados lleva en el mes: `GET /v1/me/plan`, la feature
  `ai.voice_entries` trae `used` y `limit` ("28 / 30"; `limit: null` es sin
  límite). Se actualiza al crear el dictado y vuelve atrás si falla.
- Si es de otro usuario o no existe: `404`.

#### `POST /v1/voice-entries/{id}/confirm` y `/discard`

`confirm` recibe `{ "transaction_id": "…" }`, el movimiento que la app creó con
`POST /v1/transactions` y `source: "voice"`, y pasa el dictado a `confirmed`.
`discard` lo pasa a `discarded`, también uno que todavía se procesa (la app lo
cancela, BUG-047): el worker ya no lo pisa. La cuota no se devuelve. Los dos
responden `200` con el dictado.

| Error | Cuándo |
|---|---|
| `409 voice_entry_not_ready` | `confirm`: todavía se está procesando o ya se cerró. `discard`: ya se confirmó o descartó |
| `422 validation_error` | El `transaction_id` no es un movimiento vivo del usuario |

### Agenda (spec 014)

Calendario personal y actividades con recordatorio. Las fechas se envían y devuelven en UTC (ISO 8601 con `Z`).

#### `POST /v1/agenda`
Crea una actividad (`kind: "activity"`, requiere `activity_type`) o un recordatorio (`kind: "reminder"`, sin tipo). Responde `201` con el evento creado.

#### `GET /v1/agenda?from=&to=&kind=&activity_type=`
Devuelve los eventos del usuario en el rango `[from, to]`, con las repeticiones expandidas en ocurrencias (`occurrence_starts_at` y `occurrence_ends_at`).

#### `GET /v1/agenda/upcoming?limit=10`
Devuelve las próximas ocurrencias desde ahora ordenadas cronológicamente.

#### `GET /v1/agenda/{id}`
Devuelve el evento base por su UUID sin expandir. Responde `404` si no existe o es de otro usuario.

#### `PATCH /v1/agenda/{id}`
Actualiza parcialmente los campos enviados del evento. Responde `200` con el evento actualizado.

#### `DELETE /v1/agenda/{id}`
Borrado lógico (`deleted_at`) del evento. Responde `204`.

## Endpoints planificados

Nada de acá está implementado: sale de los requisitos de las specs y sirve para
que la app sepa qué viene. La spec manda.

| Método | Ruta | Qué hará | Spec |
|---|---|---|---|
| POST | `/v1/me/avatar-upload-url` | URL firmada para subir la foto. | 001 · RF-13, RF-14 |

### Huecos que faltan cerrar en las specs

Las specs definen muy bien las **escrituras** y los **agregados** (saldos,
reportes, Safe to Spend), pero quedaron cortas en las lecturas y en algunas
rutas. Todo esto hay que escribirlo antes de programarlo:

- **El origen de un movimiento (`source`) no está en ningún RF.** La API lo acepta
  porque la columna existe (mide Quick Add, voz y escaneo), pero nadie definió
  quién puede mandarlo.
- **Un recurrente que nunca se marca pagado** se queda con `next_due_on` en el
  pasado y deja de contar como pendiente en Safe to Spend al cambiar de
  periodo. La web lo avisa en "Cuentas por pagar" hasta que se paga.

## Catálogo de errores

Todos son `application/problem+json`. El `code` es lo que la app debe mirar; el
`detail` es el texto para mostrar.

| `code` | HTTP | Cuándo |
|---|---|---|
| `validation_error` | 422 | Falta un campo, tiene mala forma o un monto no vino como texto. Trae `errors[]` con `field` y `message`. |
| `unauthorized` | 401 | Sin token, con uno vencido o con uno que no sirve. |
| `invalid_provider_token` | 401 | El token de Google no sirve: firma, audiencia, vencimiento o correo sin verificar. |
| `invalid_reset_code` | 401 | El código del restablecimiento no sirve: no existe, venció o ya se usó. |
| `invalid_registration_token` | 401 | El `registration_token` del registro social no sirve o venció: hay que hacer el ingreso de nuevo. |
| `email_required` | 422 | El proveedor no dio el correo y el pedido tampoco: no se puede crear la cuenta. |
| `not_found` | 404 | El recurso no existe o no es del usuario. Nunca un 403, para no revelar que existe. |
| `invalid_credentials` | 401 | El correo no existe o la contraseña no coincide. No dice cuál. |
| `invalid_refresh_token` | 401 | El refresh token no existe o venció. |
| `refresh_token_reused` | 401 | Ese refresh token ya se usó: se cortó la cadena. Volver a iniciar sesión. Si se rotó hace menos de 60 s y el par nuevo nunca se usó (la respuesta se perdió), no es reuso: responde `200` con otro par (BUG-053). |
| `too_many_requests` | 429 | Se pasó el límite de intentos. Trae `Retry-After` en segundos. |
| `email_taken` | 409 | Ese correo ya tiene cuenta. Sale al pedir el link o, si dos registros compiten, al registrarse. |
| `email_not_verified` | 409 | El correo no está confirmado: se intentó registrar sin abrir el link o entrar sin verificarlo. La app manda a la pantalla de verificación. |
| `verification_expired` | 410 | El link venció sin abrirse, o el correo verificado no se usó en 30 minutos. Pedir otro link. |
| `terms_outdated` | 422 | La versión de los términos no es la vigente. |
| `plan_limit` | 409 | El plan no da para más tarjetas, monedas, metas, presupuestos o dictados. Trae `feature` (`finance.cards`, `finance.currencies`, `goals.active`, `planning.budgets`, `ai.voice_entries`). |
| `invalid_audio` | 422 | El dictado no trae audio (`Content-Type: audio/*`) o pasa de 2 MB. |
| `voice_queue_unavailable` | 503 | La cola no aceptó el dictado; la entrada queda `failed` y se devuelve la cuota. |
| `voice_entry_not_ready` | 409 | El dictado todavía se procesa o ya se confirmó o descartó. |
| `currency_unavailable` | 422 | La moneda no existe o está desactivada. |
| `currency_mismatch` | 422 | El movimiento va en una moneda distinta de la de su cuenta. |
| `transfer_currency_mismatch` | 422 | Se intentó transferir entre cuentas de distinta moneda. |
| `invalid_transfer_target` | 422 | La cuenta de destino es la misma, o está archivada. |
| `invalid_amount` | 422 | El monto tiene más decimales que los de la moneda, o no es positivo. En el ahorro planificado: negativo o con decimales de más. En una meta: el objetivo o el aporte. |
| `reauthentication_failed` | 403 | Al borrar la cuenta, la contraseña o la cuenta del proveedor no son las de la persona. La sesión sigue válida. |
| `account_name_taken` | 409 | Otra cuenta del usuario ya tiene ese nombre, sin distinguir mayúsculas. |
| `account_currency_locked` | 409 | La cuenta ya se usó: su moneda no se cambia. |
| `account_insufficient` | 422 | Un gasto, una transferencia, el pago de un gasto fijo o el aporte a una meta pasan el saldo de la cuenta de donde sale (BUG-024, migración 0025). |
| `account_required` | 422 | El gasto fijo no tiene cuenta y el pago no dice con cuál se paga. |
| `recurring_duplicate` | 409 | Ya hay un gasto o ingreso fijo vivo con el mismo nombre (sin distinguir mayúsculas), monto, frecuencia y moneda (BUG-012, migración 0026). |
| `goal_name_taken` | 409 | Otra meta viva del usuario ya tiene ese nombre, sin distinguir mayúsculas. |
| `goal_has_saved` | 409 | La meta tiene saldo: hay que retirarlo a una cuenta antes de borrarla. |
| `goal_insufficient` | 422 | El retiro pasa lo acumulado en la meta. |
| `contribution_exceeds_remaining` | 422 | El aporte pasa lo que le falta a la meta para completarse (BUG-049). |
| `goal_closed` | 422 | La meta ya está cumplida o archivada: no recibe más aportes (BUG-049). |
| `currency_in_use` | 409 | No se puede quitar una moneda que es la principal o que tiene cuentas. |
| `category_name_taken` | 409 | Otra categoría del mismo tipo ya tiene ese nombre, sin distinguir mayúsculas. |
| `category_in_use` | 409 | La categoría tiene recurrentes sin borrar: hay que cambiarlos de categoría o borrarlos antes. |
| `category_type_in_use` | 409 | La categoría tiene movimientos o recurrentes: no pasa de ingreso a gasto ni al revés. |
| `invalid_cursor` | 422 | El `cursor` del historial no es uno que dio la API. Pedir la primera página. |
| `onboarding_incomplete` | 422 | Falta la moneda principal o una cuenta para cerrar el onboarding, o se pidió el Safe to Spend, un reporte o se guardó el periodo sin moneda principal. Trae `missing_step` (`currency`, `accounts`). |

## Qué necesita la app

1. Regenerar su cliente desde `openapi.json` cada vez que este documento cambie.
2. Guardar **siempre el último** `refresh_token`: el anterior queda revocado.
3. Al recibir `refresh_token_reused`, cerrar la sesión y pedir la contraseña.
   Para que el usuario cierre la sesión, `POST /v1/auth/logout` con el refresh
   guardado y, responda lo que responda, borrar los tokens del dispositivo.
4. Ante `429`, esperar lo que diga `Retry-After`.
5. Mostrar los montos como texto sin convertirlos a número: son exactos y nunca
   se suman entre monedas distintas.
6. Con `409 email_not_verified`, mandar a la pantalla de verificación del correo.
7. Mirar el `code` y no solo el estado: un `401` por `unauthorized` o
   `refresh_token_reused` cierra la sesión, pero un `403 reauthentication_failed`
   no.
