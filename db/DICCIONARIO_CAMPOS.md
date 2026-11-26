# Diccionario de datos · MoneyMap V1

**49 tablas, 517 campos y 10 vistas** en 11 módulos. Este archivo se genera desde la base de datos (`tools/build_dictionary.py`), así que coincide con las migraciones.

## Cómo leerlo

- Cada tabla dice **para qué sirve**, **quién la escribe** (la API, un worker, el equipo o la base sola) y un **ejemplo**.
- **Relaciones:** *Apunta a* = tablas de las que depende; *La usan* = tablas que dependen de ella.
- **Lo que hace la base sola:** reglas y cálculos automáticos (triggers). La API no los repite.
- **Obligatorio:** *Sí* = no puede quedar vacío; *Calculado* = lo calcula la base.
- **Clave y relación:** PK = clave primaria. *FK → tabla.campo* = el valor debe existir allí. *Del mismo usuario* = la clave incluye user_id e impide usar datos de otra persona. *En cascada* = si se borra la fila relacionada, se borra esta. *Si se borra, queda vacío* = esta fila se conserva sin el enlace.
- **Seguridad por filas (RLS):** en las tablas marcadas, cada usuario solo ve y cambia sus propias filas.
- Los valores de estados y tipos (expense, active, debit_card…) se guardan en inglés; la app los muestra traducidos.

## Glosario

| Término | Qué significa |
|---|---|
| Moneda principal | La moneda que la app muestra primero. Nada se convierte: cada total va por moneda. |
| Cuenta por defecto | La cuenta (efectivo o tarjeta) que la app propone primero al registrar un movimiento. Una por usuario. |
| Periodo | Cómo agrupa el usuario su dinero: semanal, quincenal o mensual, desde el día que elija. |
| Money Flow | Diagrama de a dónde se fue el dinero: Ingresos → Necesidades, Estilo de vida, Metas → Disponible. |
| Safe to Spend | Cuánto puede gastar en el periodo: saldo − recurrentes pendientes − ahorro planificado − aportes a metas. |
| Borrado lógico | La fila no se borra: se llena deleted_at y deja de mostrarse, pero queda para el historial. |
| UUID v7 | Identificador único que además va ordenado por fecha de creación. |
| Trigger | Regla que la base ejecuta sola al insertar, editar o borrar una fila. |

## Módulos

| Módulo | Tablas | Para qué |
|---|---|---|
| [iam · Usuarios y acceso](#iam--usuarios-y-acceso) | 8 | Quién es la persona y cómo entra: perfil, términos aceptados, personalización, formas de iniciar sesión, sesiones y dispositivos. |
| [billing · Planes y suscripciones](#billing--planes-y-suscripciones) | 9 | Plan gratuito y planes de pago, precios mensual y anual, suscripciones de App Store y Google Play, pagos y límites por plan (tarjetas, monedas, metas, dictados). |
| [catalog · Datos de referencia](#catalog--datos-de-referencia) | 5 | Lo que comparten todos los usuarios y define el equipo: monedas, tipos de cuenta, grupos del Money Flow y categorías iniciales. |
| [finance · Núcleo financiero](#finance--núcleo-financiero) | 7 | El dinero del usuario: configuración y periodo, Mis monedas, cuentas (efectivo y tarjetas), datos de tarjeta, categorías, recurrentes y transacciones. |
| [goals · Metas de ahorro](#goals--metas-de-ahorro) | 2 | Metas con su moneda y sus aportes; alimentan el Goal Forecast y Safe to Spend. |
| [planning · Decisiones](#planning--decisiones) | 1 | Historial de Can I Afford It?. |
| [reports · Resúmenes](#reports--resúmenes) | 1 | Money Story semanal y mensual. |
| [notify · Notificaciones](#notify--notificaciones) | 3 | Tipos de aviso, lo que el usuario apagó y la bandeja de avisos enviados. |
| [ai · Registro por voz con IA](#ai--registro-por-voz-con-ia) | 7 | Proveedores de IA con principal y respaldos, cada dictado, cada llamada con su costo y el uso por usuario. |
| [ops · Logs e incidentes](#ops--logs-e-incidentes) | 4 | Eventos importantes del sistema (solo inserción) e incidentes con su ciclo de vida. |
| [core · Infraestructura](#core--infraestructura) | 2 | Auditoría de cambios y eventos pendientes de publicar (outbox). |

## iam · Usuarios y acceso

Quién es la persona y cómo entra: perfil, términos aceptados, personalización, formas de iniciar sesión, sesiones y dispositivos. Solo mayores de 18 años.

### iam.auth_identities

Formas de entrar de cada usuario: correo y contraseña, Google, Meta o Apple. Un usuario puede tener varias; cada una identifica a un solo usuario.

- **Quién la escribe:** la API al registrarse o vincular un método.
- **Ejemplo:** María entra con Google (sub 1093…) y con su contraseña.
- **Apunta a:** `iam.users`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | Única (user_id, provider); FK → iam.users.id (en cascada) |
| provider | texto | Sí | — | password, google, meta o apple. Un usuario tiene como máximo una identidad por proveedor | Única (user_id, provider); Única (provider, provider_subject) |
| provider_subject | texto | Sí | — | El correo para password; el id que entrega el proveedor en los demás. La pareja (provider, provider_subject) es única: una cuenta de Google no se liga a dos usuarios | Única (provider, provider_subject) |
| password_hash | texto | No | — | Contraseña cifrada con argon2id; solo existe cuando provider es password | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| last_used_at | fecha y hora | No | — | Último inicio de sesión con este método | — |

### iam.devices

Teléfonos y navegadores del usuario: token de notificaciones push y si activó huella o rostro.

- **Quién la escribe:** la API al iniciar sesión o renovar el token push.
- **Ejemplo:** iPhone de María, iOS 19, biometría activada.
- **Apunta a:** `iam.users`
- **La usan:** `iam.sessions`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| platform | texto | Sí | — | ios, android o web | — |
| push_token | texto | No | — | Token de Firebase Cloud Messaging para enviar notificaciones | Única, si ((push_token IS NOT NULL) AND (revoked_at IS NULL)) |
| app_version | texto | No | — | Versión de la app instalada | — |
| os_version | texto | No | — | Versión del sistema operativo | — |
| biometric_enabled | sí/no | Sí | no | Si activó huella o rostro; la validación la hace el sistema operativo, no la app. Por defecto no | — |
| last_seen_at | fecha y hora | Sí | ahora | Última vez que el dispositivo usó la app | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| revoked_at | fecha y hora | No | — | Cuándo se cerró la sesión en este dispositivo | — |

### iam.email_verifications

Correos verificados con un link antes de crear la cuenta; del link solo se guarda el hash


| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | gen_random_uuid() | Identificador que recibe la app para consultar el estado (UUID aleatorio, no se adivina) | PK |
| email | texto (sin distinguir mayúsculas) | Sí | — | Correo que se está verificando | — |
| token_hash | texto | Sí | — | Hash del token del link; único | Única |
| expires_at | fecha y hora | Sí | — | Hasta cuándo vale el link (5 minutos desde el último envío) | — |
| last_sent_at | fecha y hora | Sí | ahora | Cuándo se envió el último link; marca la espera para reenviar | — |
| verified_at | fecha y hora | No | — | Cuándo se abrió el link; vacío si todavía no | — |
| used_at | fecha y hora | No | — | Cuándo se creó la cuenta con esta verificación; no vale otra vez | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

### iam.sessions

Sesiones abiertas: cada refresh token (guardado como hash) y su dispositivo. Permite cerrar sesión en un dispositivo, ver dispositivos activos y detectar un token robado que se reusa.

- **Quién la escribe:** la API al iniciar sesión y en cada renovación (rotación).
- **Ejemplo:** sesión del iPhone, vence en 30 días.
- **Apunta a:** `iam.devices`, `iam.users`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| device_id | UUID | No | — | Dispositivo de la sesión; si se borra el dispositivo, queda vacío | FK → iam.devices.id (si se borra, queda vacío) |
| refresh_token_hash | texto | Sí | — | Hash del refresh token (nunca el token); único | Única |
| replaced_by | UUID | No | — | Sesión nueva creada al renovar. Si alguien usa un token ya reemplazado, se detecta un posible robo | FK → iam.sessions.id (si se borra, queda vacío) |
| ip | IP | No | — | IP desde la que se abrió | — |
| user_agent | texto | No | — | Navegador o app que la abrió | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| expires_at | fecha y hora | Sí | — | Vencimiento; debe ser posterior a created_at | — |
| revoked_at | fecha y hora | No | — | Cuándo se cerró la sesión | — |

### iam.terms_versions

Versiones publicadas de los términos de uso y la política de privacidad; solo una es la vigente.

- **Quién la escribe:** el equipo, al publicar una versión nueva.
- **Ejemplo:** 2026-10, vigente, con sus dos enlaces.
- **La usan:** `iam.users`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| version | texto | Sí | — | Versión, por ejemplo 2026-10 | PK |
| terms_url | texto | Sí | — | Enlace a los términos | — |
| privacy_url | texto | Sí | — | Enlace a la política de privacidad | — |
| is_current | sí/no | Sí | no | Si es la vigente; solo una puede serlo | Única, si is_current |
| published_at | fecha y hora | Sí | ahora | Cuándo se publicó | — |

### iam.user_preferences

Personalización de la app guardada en el servidor, para que sea igual en todos los dispositivos.

- **Quién la escribe:** un trigger la crea al registrarse; después la API cuando el usuario cambia tema, color, modo privado o inicio de semana.
- **Ejemplo:** tema oscuro, acento verde, montos ocultos, semana desde el lunes.
- **Apunta a:** `iam.users`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario dueño; es también la clave primaria | PK; FK → iam.users.id (en cascada) |
| theme | texto | Sí | system | system (del teléfono), light o dark. Por defecto system | — |
| accent_color | texto | No | — | Color de acento #RRGGBB; vacío = color de la marca | — |
| hide_amounts | sí/no | Sí | no | Modo privado: la app abre con los montos ocultos. Por defecto no | — |
| week_starts_on | entero | Sí | 1 | Día de inicio de semana: 0 domingo a 6 sábado. Por defecto 1 (lunes) | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### iam.users

Una fila por persona registrada: es la cuenta que inicia sesión, paga y es dueña de todos sus datos financieros.

- **Quién la escribe:** la API al registrarse y al editar el perfil; la base limpia nombres, teléfono y país y exige 18 años y los términos vigentes.
- **Ejemplo:** María José Rojas, maria@correo.com, nacida en 1995, estudiante en La Paz.
- **Apunta a:** `catalog.countries`, `iam.terms_versions`
- **La usan:** `ai.voice_entries`, `billing.payments`, `billing.subscription_changes`, `billing.subscriptions`, `billing.usage_counters`, `finance.accounts`, `finance.categories`, `finance.recurring_rules`, `finance.transactions`, `finance.user_currencies`, `finance.user_settings`, `goals.goals`, `iam.auth_identities`, `iam.devices`, `iam.sessions`, `iam.user_preferences`, `iam.verification_tokens`, `notify.notifications`, `notify.preferences`, `planning.affordability_checks`, `reports.money_stories`
- **Lo que hace la base sola:**
  - Limpia nombre, apellido, teléfono, país y ciudad; display_name vacío toma el nombre; al registrarse exige los términos vigentes (terms_outdated).
  - Crea las preferencias por defecto de cada usuario nuevo.
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| email | texto (sin distinguir mayúsculas) | Sí | — | Correo de la cuenta; único sin distinguir mayúsculas | Única, si (deleted_at IS NULL) |
| email_verified_at | fecha y hora | No | — | Cuándo confirmó su correo; vacío si no lo confirmó | — |
| first_name | texto | Sí | — | Nombre (1 a 60 caracteres); se guarda sin espacios de más | — |
| last_name | texto | Sí | — | Apellido (1 a 60 caracteres); se guarda sin espacios de más | — |
| display_name | texto | Sí | — | Cómo quiere que lo llame la app (1 a 120 caracteres); vacío = su nombre | — |
| avatar_object_key | texto | No | — | Ruta de la foto de perfil en Cloud Storage | — |
| country_code | texto de 2 | No | — | País ISO 3166-1 en mayúsculas (BO) | FK → catalog.countries.code |
| city | texto | No | — | Ciudad (hasta 80 caracteres) | — |
| occupation | texto | No | — | student, employee, self_employed, entrepreneur, unemployed, retired u other | — |
| terms_version | texto | Sí | — | Versión de los términos que aceptó; al registrarse debe ser la vigente (terms_outdated) | FK → iam.terms_versions.version |
| terms_accepted_at | fecha y hora | Sí | ahora | Cuándo aceptó los términos | — |
| locale | texto | Sí | es-BO | Idioma y región de la app. Por defecto es-BO | — |
| timezone | texto | Sí | America/La_Paz | Zona horaria para fechas y avisos. Por defecto America/La_Paz | — |
| is_admin | sí/no | Sí | no | MM-189: el único administrador del panel de planes. A lo sumo uno (índice único parcial) | — |
| status | texto | Sí | active | active, suspended, pending_deletion o deleted. Por defecto active | — |
| onboarding_completed_at | fecha y hora | No | — | Cuándo terminó el onboarding; con fecha, no se vuelve a mostrar | — |
| last_login_at | fecha y hora | No | — | Último inicio de sesión | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |
| deletion_requested_at | fecha y hora | No | — | Cuándo pidió borrar su cuenta. A los 30 días un job la borra en cascada; entrar antes lo cancela. Existe solo si status es pending_deletion. | — |

### iam.verification_tokens

Códigos de un solo uso para verificar el correo, recuperar la contraseña o cambiar el correo, guardados como hash.

- **Quién la escribe:** la API al enviar el correo; se marca usado al confirmarlo.
- **Ejemplo:** recuperación de contraseña, vence en 1 hora.
- **Apunta a:** `iam.users`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| purpose | texto | Sí | — | email_verification, password_reset o email_change | — |
| token_hash | texto | Sí | — | Hash del código; único | Única |
| expires_at | fecha y hora | Sí | — | Hasta cuándo vale el código | — |
| used_at | fecha y hora | No | — | Cuándo se usó; un código usado no vale otra vez | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

## billing · Planes y suscripciones

Plan gratuito y planes de pago, precios mensual y anual, suscripciones de App Store y Google Play, pagos y límites por plan (tarjetas, monedas, metas, dictados). Sin suscripción con acceso, el usuario está en el gratuito.

### billing.features

Funcionalidades que un plan habilita o limita. total = recursos vivos (tarjetas, monedas, metas); month = usos en el mes (dictados, consultas).

- **Quién la escribe:** el equipo.
- **Ejemplo:** finance.cards (límite total), ai.voice_entries (límite al mes).
- **La usan:** `billing.plan_features`, `billing.usage_counters`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| key | texto | Sí | — | Clave, por ejemplo finance.cards o ai.voice_entries | PK |
| description | texto | Sí | — | Qué significa, para el equipo | — |
| value_type | texto | Sí | — | boolean (sí o no) o limit (con un número máximo) | — |
| limit_period | texto | No | — | Solo en limit: total (por ejemplo, tarjetas activas) o month (por ejemplo, dictados al mes) | — |

### billing.payments

Cada cobro, renovación o reembolso informado por las tiendas. La clave (provider, provider_transaction_id) evita registrar dos veces el mismo cobro.

- **Quién la escribe:** los workers.
- **Ejemplo:** App Store, renovación, 4,99 USD.
- **Apunta a:** `billing.plan_prices`, `billing.subscriptions`, `iam.users`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| subscription_id | UUID | No | — | Suscripción cobrada; si se borra, queda vacío | FK → billing.subscriptions.id (si se borra, queda vacío) |
| plan_price_id | UUID | No | — | Precio cobrado | FK → billing.plan_prices.id |
| provider | texto | Sí | — | app_store, play_store, web o internal | Única (provider, provider_transaction_id) |
| provider_transaction_id | texto | Sí | — | Id del cobro en la tienda | Única (provider, provider_transaction_id) |
| kind | texto | Sí | — | initial, renewal, upgrade, refund o chargeback | — |
| status | texto | Sí | — | pending, succeeded, failed o refunded | — |
| amount | decimal (12,2) | Sí | — | Monto cobrado; negativo en reembolsos | — |
| currency | texto de 3 | Sí | — | Moneda local que cobró la tienda | — |
| billing_period | texto | No | — | month o year | — |
| period_start | fecha y hora | No | — | Inicio del periodo pagado | — |
| period_end | fecha y hora | No | — | Fin del periodo pagado | — |
| store_fee | decimal (12,2) | No | — | Comisión de la tienda, si se conoce | — |
| occurred_at | fecha y hora | Sí | ahora | Cuándo ocurrió el cobro | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

### billing.plan_features

Cuánto permite cada plan de cada funcionalidad. Cambiar un límite es un UPDATE, sin desplegar.

- **Quién la escribe:** el equipo.
- **Ejemplo:** free → finance.cards 1, finance.currencies 1, ai.voice_entries 30.
- **Apunta a:** `billing.features`, `billing.plans`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| plan_id | UUID | Sí | — | Plan; parte de la clave primaria. Si se borra el plan, se borran sus filas | PK (plan_id, feature_key); FK → billing.plans.id (en cascada) |
| feature_key | texto | Sí | — | Funcionalidad; parte de la clave primaria | FK → billing.features.key; PK (plan_id, feature_key) |
| is_enabled | sí/no | Sí | sí | Si el plan la incluye. Por defecto sí | — |
| limit_value | entero | No | — | Máximo permitido; vacío = ilimitado. 0 = nada (el plan gratuito tiene 0 tarjetas) | — |

### billing.plan_prices

Precio mensual y anual de cada plan de pago, con el producto de App Store y de Google Play. Un cambio de precio es una fila nueva: quien ya pagaba conserva su precio.

- **Quién la escribe:** el equipo.
- **Ejemplo:** paid_1 mensual 4,99 USD, mm.plus.monthly.
- **Apunta a:** `billing.plans`, `catalog.currencies`
- **La usan:** `billing.payments`, `billing.subscription_changes`, `billing.subscriptions`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| plan_id | UUID | Sí | — | Plan al que pertenece | FK → billing.plans.id; Única (plan_id, billing_period, currency, si is_active) |
| billing_period | texto | Sí | — | month o year | Única (plan_id, billing_period, currency, si is_active) |
| currency | texto de 3 | Sí | — | Moneda del precio | FK → catalog.currencies.code; Única (plan_id, billing_period, currency, si is_active) |
| amount | decimal (12,2) | Sí | — | Precio por periodo, mayor que 0 | — |
| trial_days | entero | Sí | 0 | Días de prueba gratis (0 a 90). Por defecto 0 | — |
| app_store_product_id | texto | No | — | Id del producto en App Store | Única, si ((app_store_product_id IS NOT NULL) AND is_active) |
| play_store_product_id | texto | No | — | Id del producto y plan base en Google Play | Única, si ((play_store_product_id IS NOT NULL) AND is_active) |
| web_price_id | texto | No | — | Id en una pasarela web, si algún día se cobra fuera de las tiendas | — |
| is_active | sí/no | Sí | sí | Si se ofrece a suscriptores nuevos. Por defecto sí | — |
| valid_from | fecha y hora | Sí | ahora | Desde cuándo rige el precio | — |
| valid_until | fecha y hora | No | — | Hasta cuándo rige; vacío = vigente | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

### billing.plans

Planes de la app: uno gratuito (tier 0) y tres de pago.

- **Quién la escribe:** el equipo.
- **Ejemplo:** free, paid_1, paid_2, paid_3.
- **La usan:** `billing.plan_features`, `billing.plan_prices`, `billing.subscription_changes`, `billing.subscriptions`
- **Lo que hace la base sola:**
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| code | texto | Sí | — | Código interno: free, paid_1, paid_2, paid_3; único | Única |
| name | texto | Sí | — | Nombre comercial | — |
| description | texto | No | — | Descripción para la pantalla de planes | — |
| tier | entero | Sí | — | Nivel: 0 = gratuito, mayor = plan superior; único. Sirve para saber si un cambio es subida o bajada | Única |
| is_public | sí/no | Sí | sí | Si se muestra en la pantalla de planes. Por defecto sí | — |
| is_active | sí/no | Sí | sí | Si se puede contratar. Por defecto sí | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### billing.subscription_changes

Historial de cada cambio de suscripción: alta, renovación, subida o bajada de plan, cancelación, expiración, vuelta a gratuito.

- **Quién la escribe:** un trigger de billing.subscriptions; nadie lo edita.
- **Ejemplo:** 14-10 started; 20-10 period_changed (mensual → anual).
- **Apunta a:** `billing.plan_prices`, `billing.plans`, `billing.subscriptions`, `iam.users`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| seq | entero | Sí | — | Número correlativo del cambio | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| subscription_id | UUID | No | — | Suscripción que cambió; si se borra, queda vacío y el historial se conserva | FK → billing.subscriptions.id (si se borra, queda vacío) |
| change_type | texto | Sí | — | Qué pasó: started, renewed, upgraded, downgraded, period_changed, auto_renew_disabled, expired, reverted_to_free y otros 13 tipos | — |
| from_plan_id | UUID | No | — | Plan anterior | FK → billing.plans.id |
| to_plan_id | UUID | No | — | Plan nuevo | FK → billing.plans.id |
| from_price_id | UUID | No | — | Precio anterior | FK → billing.plan_prices.id |
| to_price_id | UUID | No | — | Precio nuevo | FK → billing.plan_prices.id |
| from_period | texto | No | — | Periodo anterior (month o year) | — |
| to_period | texto | No | — | Periodo nuevo | — |
| from_status | texto | No | — | Estado anterior | — |
| to_status | texto | No | — | Estado nuevo | — |
| source | texto | Sí | system | Quién lo originó: store_webhook, user, admin, job o system. Por defecto system | — |
| effective_at | fecha y hora | Sí | ahora | Cuándo tuvo efecto | — |

### billing.subscription_events

Avisos crudos recibidos de App Store y Google Play, para procesarlos una sola vez y poder reintentarlos.

- **Quién la escribe:** el worker de webhooks.
- **Ejemplo:** DID_RENEW recibido a las 10:02, procesado a las 10:02.
- **Apunta a:** `billing.subscriptions`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| subscription_id | UUID | No | — | Suscripción a la que se refiere, una vez identificada | FK → billing.subscriptions.id (si se borra, queda vacío) |
| provider | texto | Sí | — | Tienda que la envió | Única (provider, provider_event_id) |
| provider_event_id | texto | Sí | — | Id del aviso en la tienda | Única (provider, provider_event_id) |
| event_type | texto | Sí | — | Tipo de aviso según la tienda | — |
| payload | JSON | Sí | — | Contenido completo del aviso, en JSON | — |
| received_at | fecha y hora | Sí | ahora | Cuándo llegó | — |
| processed_at | fecha y hora | No | — | Cuándo lo procesó el worker; vacío = pendiente | — |
| error | texto | No | — | Error al procesarlo, si lo hubo | — |

### billing.subscriptions

Suscripción de un usuario a un plan de pago, mensual o anual, con su estado. Sin suscripción con acceso, el usuario está en el plan gratuito.

- **Quién la escribe:** los workers que procesan los avisos de App Store y Google Play.
- **Ejemplo:** María en paid_1 mensual, activa hasta el 14-11.
- **Apunta a:** `billing.plan_prices`, `billing.plans`, `iam.users`
- **La usan:** `billing.payments`, `billing.subscription_changes`, `billing.subscription_events`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).
  - Mantiene canceled_at, cancel_reason y ended_at según el estado y la renovación automática.
  - Escribe cada cambio de la suscripción en billing.subscription_changes.
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada); Única, si (status = ANY (ARRAY['trialing'::text, 'active'::text, 'grace_period'::text, 'on_hold'::text, 'paused'::text])) |
| plan_id | UUID | Sí | — | Plan contratado | FK → billing.plans.id; FK → billing.plan_prices.plan_id (junto con plan_price_id, billing_period) |
| plan_price_id | UUID | Sí | — | Precio contratado; la FK (plan_price_id, plan_id, billing_period) exige que sea de ese plan y ese periodo | FK → billing.plan_prices.id (junto con plan_id, billing_period) |
| billing_period | texto | Sí | — | month o year | FK → billing.plan_prices.billing_period (junto con plan_price_id, plan_id) |
| status | texto | Sí | — | trialing, active, grace_period, on_hold, paused, expired o revoked. Los tres primeros dan acceso al plan de pago | — |
| provider | texto | Sí | — | Dónde se pagó: app_store, play_store, web o internal | Única (provider, provider_subscription_id) |
| provider_subscription_id | texto | No | — | Id en la tienda (original_transaction_id en App Store, purchase token en Google Play); único por tienda | Única (provider, provider_subscription_id) |
| auto_renew | sí/no | Sí | sí | false = el usuario canceló; conserva el acceso hasta current_period_end. Por defecto sí | — |
| started_at | fecha y hora | Sí | ahora | Cuándo empezó la suscripción | — |
| trial_ends_at | fecha y hora | No | — | Fin de la prueba gratis | — |
| current_period_start | fecha y hora | Sí | ahora | Inicio del periodo pagado actual | — |
| current_period_end | fecha y hora | Sí | — | Hasta cuándo tiene acceso pagado | — |
| grace_period_ends_at | fecha y hora | No | — | Fin del periodo de gracia tras un cobro fallido | — |
| pending_plan_price_id | UUID | No | — | Cambio programado para el fin del periodo (por ejemplo, de mensual a anual) | FK → billing.plan_prices.id |
| pending_change_at | fecha y hora | No | — | Cuándo se aplica el cambio programado; existe solo junto con pending_plan_price_id | — |
| canceled_at | fecha y hora | No | — | Cuándo apagó la renovación | — |
| cancel_reason | texto | No | — | user, billing_error, refund, price_increase_declined, replaced u other | — |
| ended_at | fecha y hora | No | — | Cuándo perdió el acceso; existe solo si status es expired o revoked | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### billing.usage_counters

Usos del mes de las funcionalidades con límite mensual. Se descuentan con billing.try_consume() y se devuelven con billing.release().

- **Quién la escribe:** esas funciones.
- **Ejemplo:** María, ai.voice_entries, octubre: 12 usados.
- **Apunta a:** `billing.features`, `iam.users`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario; parte de la clave primaria | PK (user_id, feature_key, period_start); FK → iam.users.id (en cascada) |
| feature_key | texto | Sí | — | Funcionalidad; parte de la clave primaria | FK → billing.features.key; PK (user_id, feature_key, period_start) |
| period_start | fecha | Sí | — | Mes (día 1); parte de la clave primaria | PK (user_id, feature_key, period_start) |
| used | entero | Sí | 0 | Usos en el mes. billing.release() lo devuelve si la acción falló por nosotros. Por defecto 0 | — |
| updated_at | fecha y hora | Sí | ahora | Última vez que se sumó o devolvió un uso | — |

## catalog · Datos de referencia

Lo que comparten todos los usuarios y define el equipo: monedas, tipos de cuenta, grupos del Money Flow y categorías iniciales. Cambiarlo es un INSERT o UPDATE, sin desplegar código.

### catalog.account_types

Tipos de cuenta: efectivo y tarjeta (sin distinguir débito de crédito). De aquí sale si un movimiento se pagó en efectivo o con tarjeta (is_card).

- **Quién la escribe:** el equipo.
- **Ejemplo:** card, Tarjeta, es tarjeta.
- **La usan:** `finance.accounts`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| code | texto | Sí | — | Clave: cash (efectivo) o card (tarjeta) | PK |
| names | JSON | Sí | — | Nombre por idioma en JSON; el español es obligatorio | — |
| icon | texto | Sí | — | Nombre del ícono que muestra la app | — |
| is_card | sí/no | Sí | no | true = es una tarjeta: cuenta para el límite de tarjetas del plan y sus movimientos se pagan "con tarjeta". false = efectivo | — |
| sort_order | entero | Sí | 0 | Orden en que se muestra en la app. Por defecto 0 | — |
| is_active | sí/no | Sí | sí | Si se puede usar; desactivar no borra nada. Por defecto sí | — |

### catalog.category_templates

Categorías iniciales que recibe cada usuario nuevo. Solo categorías, sin subcategorías.

- **Quién la escribe:** el equipo.
- **Ejemplo:** groceries (Supermercado), gasto, grupo Necesidades.
- **La usan:** `finance.categories`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| key | texto | Sí | — | Clave en minúsculas, por ejemplo groceries | PK |
| kind | lista fija: income, expense, transfer | Sí | — | income (ingreso) o expense (gasto). Lista fija catalog.money_kind | — |
| flow_group | lista fija: needs, lifestyle | No | — | Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos | — |
| names | JSON | Sí | — | Nombre por idioma en JSON, por ejemplo {"es": "Comida", "en": "Food"}; el español es obligatorio | — |
| icon | texto | Sí | — | Nombre del ícono que muestra la app | — |
| color | texto | Sí | — | Color en hexadecimal (#RRGGBB) | — |
| sort_order | entero | Sí | 0 | Orden en que se muestra en la app. Por defecto 0 | — |
| is_active | sí/no | Sí | sí | Si se puede usar; desactivar no borra nada. Por defecto sí | — |

### catalog.countries

Países (ISO 3166-1) con su moneda local. Sirve para el país del perfil y para mostrar los bancos de cada país.

- **Quién la escribe:** el equipo; agregar un país es un INSERT.
- **Ejemplo:** BO, Bolivia, BOB.
- **Apunta a:** `catalog.currencies`
- **La usan:** `catalog.financial_institutions`, `iam.users`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| code | texto de 2 | Sí | — | Código ISO 3166-1 de 2 letras, por ejemplo BO | PK |
| name | texto | Sí | — | Nombre del país en español | — |
| currency | texto de 3 | No | — | Moneda local del país (opcional); la app la propone como moneda principal | FK → catalog.currencies.code |
| is_active | sí/no | Sí | sí | Si se ofrece en la app. Por defecto sí | — |
| sort_order | entero | Sí | 100 | Orden en el selector. Por defecto 100 | — |

### catalog.currencies

Monedas que ofrece la app (ISO 4217). Agregar una es un INSERT; desactivarla la oculta para cuentas nuevas sin tocar lo existente.

- **Quién la escribe:** el equipo.
- **Ejemplo:** BOB, Boliviano, Bs, 2 decimales.
- **La usan:** `billing.plan_prices`, `catalog.countries`, `finance.accounts`, `finance.user_currencies`, `finance.user_settings`, `goals.goals`, `planning.affordability_checks`, `reports.money_stories`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| code | texto de 3 | Sí | — | Código ISO de 3 letras, por ejemplo BOB | PK |
| name | texto | Sí | — | Nombre de la moneda | — |
| symbol | texto | Sí | — | Símbolo, por ejemplo Bs o $ | — |
| decimals | entero | Sí | 2 | Cuántos decimales acepta un monto en esta moneda: BOB y USD 2, CLP y PYG 0 (0 a 4). Por defecto 2. 1000,5 pesos chilenos se rechaza (invalid_amount) | — |
| is_active | sí/no | Sí | sí | Si se ofrece en la app. Inactiva = no se acepta en cuentas, metas, moneda principal ni Mis monedas nuevos; las cuentas que ya existen siguen registrando. Por defecto sí | — |
| sort_order | entero | Sí | 100 | Orden en el selector, después de Mis monedas. Por defecto 100 | — |

### catalog.financial_institutions

Bancos, cooperativas, microfinancieras y billeteras de cada país que emiten tarjetas. La app muestra la lista del país del usuario en vez de pedir el nombre como texto.

- **Quién la escribe:** el equipo.
- **Ejemplo:** bo.bnb, Banco Nacional de Bolivia (BNB), banco.
- **Apunta a:** `catalog.countries`
- **La usan:** `finance.cards`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| code | texto | Sí | — | Clave: país en minúsculas, punto y nombre corto, por ejemplo bo.bnb | PK |
| country_code | texto de 2 | Sí | — | País de la institución | FK → catalog.countries.code; Única (country_code, short_name) |
| name | texto | Sí | — | Nombre completo, por ejemplo Banco Nacional de Bolivia | — |
| short_name | texto | Sí | — | Nombre corto que muestra la app, por ejemplo BNB; único dentro del país | Única (country_code, short_name) |
| kind | texto | Sí | bank | bank (banco), cooperative (cooperativa), microfinance (microfinanciera) o fintech (billetera o banco digital). Por defecto bank | — |
| is_active | sí/no | Sí | sí | Si se ofrece en la app; desactivarla no afecta las tarjetas que ya la usan. Por defecto sí | — |
| sort_order | entero | Sí | 100 | Orden en la lista: los más usados primero. Por defecto 100 | — |

### catalog.story_templates

El texto de cada frase de la Money Story, por versión. La historia guarda la clave y los parámetros; la API arma el texto con esta tabla, así que cambiar una frase no regenera nada.

- **Quién la escribe:** el equipo, con una migración.
- **Ejemplo:** versión 1, summary, "En {month} entraron {income} y salieron {expense}."

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| template_version | texto | Sí | — | Versión de las plantillas; la de cada historia está en reports.money_stories.template_version | PK (template_version, key) |
| key | texto | Sí | — | Clave de la frase, la misma de reports.money_stories.highlights | PK (template_version, key) |
| body | texto | Sí | — | El texto; {nombre} es un parámetro de la frase (los montos llegan con su símbolo y los meses con su nombre) | — |

## finance · Núcleo financiero

El dinero del usuario: configuración y periodo, Mis monedas, cuentas (efectivo y tarjetas), datos de tarjeta, categorías, recurrentes y transacciones. Cada cuenta tiene una moneda y nada se convierte; los saldos los mantiene la base de datos.

### finance.accounts

Dónde está el dinero del usuario: su efectivo y sus tarjetas, cada una con su saldo. Una moneda por cuenta y una sola cuenta por defecto.

- **Quién la escribe:** la API (crear, renombrar, archivar); los triggers (saldo, cuenta por defecto, límites del plan).
- **Ejemplo:** 'Tarjeta BNB Bs', tarjeta, BOB, saldo 1.525,40.
- **Apunta a:** `catalog.account_types`, `catalog.currencies`, `iam.users`
- **La usan:** `finance.cards`, `finance.recurring_rules`, `finance.transactions`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Agrega la moneda a Mis monedas y mantiene una sola cuenta por defecto (marcar otra desmarca la anterior; si se archiva, pasa a la siguiente).
  - Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).
  - Valida tipo y moneda, bloquea la moneda de una cuenta usada, aplica los límites de tarjetas y monedas del plan (MM001) y deja por defecto la primera cuenta.
  - updated_at se actualiza solo en cada cambio.
  - El saldo actual arranca en el saldo inicial y se corrige si este cambia.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| name | texto | Sí | — | Nombre que le da el usuario (1 a 80 caracteres) | — |
| type | texto | Sí | — | cash (efectivo) o card (tarjeta). Las dos tienen saldo. Crear una tarjeta, desarchivarla o convertir una cuenta en tarjeta cuenta para el límite de tarjetas del plan. No cambia si la cuenta ya tiene movimientos | FK → catalog.account_types.code |
| currency | texto de 3 | Sí | — | Moneda de la cuenta; debe estar activa. Todo lo que pasa en la cuenta queda en esta moneda. Para tener Bs y USD se crean dos cuentas; una moneda nueva cuenta para el límite de monedas del plan. Solo se corrige mientras la cuenta no tenga movimientos ni recurrentes (account_currency_locked) | FK → catalog.currencies.code |
| opening_balance | decimal (19,4) | Sí | 0 | Saldo con el que se creó la cuenta. Por defecto 0 | — |
| current_balance | decimal (19,4) | Sí | 0 | Saldo actual. Lo mantiene un trigger con cada movimiento; la API no lo escribe. En tarjetas de crédito es negativo (deuda). Por defecto 0 | — |
| is_default | sí/no | Sí | no | Cuenta por defecto: la que la app propone primero en Quick Add, voz y escaneo. Una sola por usuario. La primera cuenta lo es sola; marcar otra desmarca la anterior; si se archiva, pasa a la siguiente cuenta activa | — |
| sort_order | entero | Sí | 0 | Orden en que se muestra en la app. Por defecto 0 | — |
| archived_at | fecha y hora | No | — | Archivada: se oculta en la app y conserva su historial. Una cuenta archivada no cuenta para los límites del plan ni puede ser la cuenta por defecto | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |

### finance.cards

Datos que solo tienen las tarjetas (1 a 1 con su cuenta): banco emisor del catálogo y últimos 4 dígitos. El saldo y la moneda están en finance.accounts.

- **Quién la escribe:** la API al crear o editar una tarjeta.
- **Ejemplo:** Visa del BNB ••9012.
- **Apunta a:** `catalog.financial_institutions`, `finance.accounts`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| account_id | UUID | Sí | — | Cuenta de tipo tarjeta a la que pertenecen estos datos; es también la clave primaria (1 a 1) | FK → finance.accounts.id (junto con account_type, del mismo usuario, en cascada); PK |
| user_id | UUID | Sí | — | Usuario dueño; junto con account_id y account_type asegura que la tarjeta sea suya | — |
| account_type | texto | Sí | card | Siempre card: junto con account_id asegura que la cuenta sea una tarjeta. El efectivo no puede tener fila aquí | FK → finance.accounts.type (junto con account_id, del mismo usuario, en cascada) |
| institution_code | texto | No | — | Banco emisor, elegido de catalog.financial_institutions (opcional) | FK → catalog.financial_institutions.code |
| last4 | texto de 4 | No | — | Últimos 4 dígitos para reconocer la tarjeta (opcional). Nunca se guarda el número completo | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### finance.categories

Categorías de cada usuario: copia editable de las iniciales más las que cree. kind dice si es ingreso o gasto; flow_group, a qué nodo del Money Flow va un gasto.

- **Quién la escribe:** finance.setup_user() al registrarse; la API cuando el usuario crea, renombra o borra.
- **Ejemplo:** 'Supermercado', gasto, Necesidades.
- **Apunta a:** `catalog.category_templates`, `iam.users`
- **La usan:** `finance.recurring_rules`, `finance.transactions`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - No deja borrar (deleted_at) una categoría que usa un recurrente sin borrar (category_in_use).
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| template_key | texto | No | — | Plantilla de la que salió; se conserva aunque el usuario la renombre | FK → catalog.category_templates.key (si se borra, queda vacío) |
| kind | lista fija: income, expense, transfer | Sí | — | income (ingreso) o expense (gasto). Decide si un movimiento suma o resta, y no deja registrar un gasto en una categoría de ingreso | — |
| flow_group | lista fija: needs, lifestyle | No | — | Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos | — |
| name | texto | Sí | — | Nombre que ve el usuario (1 a 60 caracteres) | — |
| icon | texto | Sí | label | Nombre del ícono. Por defecto label | — |
| color | texto | Sí | #6B7280 | Color en hexadecimal. Por defecto #6B7280 | — |
| sort_order | entero | Sí | 0 | Orden en que se muestra en la app. Por defecto 0 | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |

### finance.recurring_rules

Gastos e ingresos que se repiten: alquiler, sueldo, Netflix. Sirven para recordatorios (desde la migración 0019 ya no se registran solos) y para restarse en Safe to Spend (is_committed). Ingreso o gasto sale de su categoría.

- **Quién la escribe:** la API (onboarding y Ajustes); el worker avanza next_due_on.
- **Ejemplo:** Alquiler, 1.500 Bs desde Efectivo, mensual desde el 31-01.
- **Apunta a:** `finance.accounts`, `finance.categories`, `iam.users`
- **La usan:** `finance.transactions`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Toma la moneda de la cuenta (currency_mismatch si se envía otra) y usa start_date como primer vencimiento.
  - Rechaza una categoría borrada o de otro usuario al crearlo o al cambiarle la categoría.
  - No deja dos recurrentes vivos con el mismo nombre (sin mayúsculas), monto, frecuencia y moneda (recurring_duplicate, migración 0026).
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| account_id | UUID | No | — | Cuenta sugerida para pagarlo; sin ella, la cuenta se elige al pagar (BUG-027) | FK → finance.accounts.id (junto con currency, del mismo usuario) |
| category_id | UUID | Sí | — | Categoría del mismo usuario. De ella sale si la regla es un ingreso o un gasto | FK → finance.categories.id (del mismo usuario) |
| amount | decimal (19,4) | Sí | — | Monto de cada repetición, mayor que 0 | — |
| currency | texto de 3 | Sí | — | Moneda de la cuenta; si no se envía, la completa la base de datos y otra se rechaza (currency_mismatch) | FK → finance.accounts.currency (junto con account_id, del mismo usuario) |
| description | texto | Sí | — | Texto que ve el usuario (1 a 120 caracteres) | — |
| frequency | lista fija: weekly, biweekly, monthly, yearly | Sí | — | weekly (cada semana), biweekly (cada 2 semanas), monthly (cada mes) o yearly (cada año). Las fechas se cuentan desde start_date: un pago del 31 cae el 28 o 29 en febrero y vuelve al 31 | — |
| start_date | fecha | Sí | — | Desde cuándo rige | — |
| end_date | fecha | No | — | Hasta cuándo rige; vacío = sin fin | — |
| next_due_on | fecha | Sí | — | Próximo vencimiento; si no se envía, es start_date. De aquí salen los recordatorios y lo comprometido del periodo. El worker lo avanza con finance.next_occurrence() | — |
| is_committed | sí/no | Sí | sí | Si Safe to Spend lo resta como gasto comprometido. Por defecto sí | — |
| auto_post | sí/no | Sí | no | Si al vencer se registra solo como transacción. Desde la migración 0019 siempre es no: los recurrentes son recordatorios y la API ignora un true | — |
| remind_days_before | entero | Sí | 1 | Días de anticipación del recordatorio (0 a 14). Por defecto 1 | — |
| is_active | sí/no | Sí | sí | Si la regla sigue vigente. Por defecto sí | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |

### finance.transactions

Cada ingreso, gasto o transferencia, en la moneda de su cuenta. Es la tabla más grande: está dividida en 16 particiones por usuario. Guarda la moneda (copia de la de su cuenta) para sumar por moneda sin unir tablas.

- **Quién la escribe:** la API (Quick Add, voz, escaneo) y el worker (recurrentes); los triggers ajustan los saldos.
- **Ejemplo:** gasto de 105 Bs, 'Netflix', con la tarjeta BNB el 14-10.
- **Apunta a:** `finance.accounts`, `finance.categories`, `finance.recurring_rules`, `iam.users`
- **La usan:** `ai.voice_entries`, `finance.transaction_receipts`, `goals.goal_contributions`
- **Características:** con seguridad por filas (RLS), particionada
- **Lo que hace la base sola:**
  - Ajusta el saldo de las cuentas con cada alta, edición o borrado de un movimiento.
  - Toma la moneda de la cuenta, valida los decimales y que una transferencia vaya a otra cuenta activa de la misma moneda.
  - Un gasto, una transferencia o el pago de un gasto fijo no sacan de la cuenta más de lo que tiene (account_insufficient, migraciones 0021 y 0025).
  - Rechaza una categoría borrada o de otro usuario al crearlo o al cambiarle la categoría.
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK (user_id, id) |
| user_id | UUID | Sí | — | Usuario dueño de la fila | PK (user_id, id); FK → iam.users.id (en cascada) |
| kind | lista fija: income, expense, transfer | Sí | — | income (ingreso, suma al saldo), expense (gasto, resta) o transfer (transferencia entre dos cuentas propias). Debe coincidir con el tipo de su categoría | FK → finance.categories.kind (junto con category_id, del mismo usuario) |
| account_id | UUID | Sí | — | Cuenta de origen. La FK compuesta (user_id, account_id, currency) exige que sea del mismo usuario y que currency sea su moneda | FK → finance.accounts.id (junto con currency, del mismo usuario) |
| category_id | UUID | No | — | Categoría del mismo usuario y del mismo tipo; vacía solo en transferencias | FK → finance.categories.id (junto con kind, del mismo usuario) |
| amount | decimal (19,4) | Sí | — | Monto en la moneda de la cuenta, mayor que 0 y con los decimales de esa moneda; de aquí sale el saldo | — |
| currency | texto de 3 | Sí | — | Moneda de la cuenta, copiada aquí para sumar por moneda sin unir con accounts. Si no se envía, la completa la base de datos; otra se rechaza (currency_mismatch) | FK → finance.accounts.currency (junto con account_id, del mismo usuario); FK → finance.accounts.currency (junto con transfer_account_id, del mismo usuario) |
| transfer_account_id | UUID | No | — | Cuenta de destino; solo en transferencias, activa, del mismo usuario y en la misma moneda (transfer_currency_mismatch) | FK → finance.accounts.id (junto con currency, del mismo usuario) |
| occurred_on | fecha | Sí | — | Fecha del movimiento | — |
| description | texto | Sí | — | Qué fue, en palabras del usuario (hasta 200 caracteres): 'Netflix', 'Almuerzo'. Se busca por texto y sirve para sugerir categoría y cuenta en Quick Add (finance.suggest_from_history) | — |
| source | lista fija: manual, quick_add, voice, scan, recurring, onboarding, adjustment | Sí | manual | Cómo se registró: manual, quick_add, voice (dictado), scan (factura), recurring (lo registró un recurrente), onboarding o adjustment (corrección de saldo). Por defecto manual | — |
| recurring_rule_id | UUID | No | — | Regla recurrente que lo generó; si se borra la regla, queda vacío | FK → finance.recurring_rules.id (del mismo usuario, si se borra, queda vacío) |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |

### finance.transaction_receipts

La foto del comprobante de un gasto (spec 014, migración 0029). La imagen vive en el S3 propio (servicio `receipts` del docker-compose); acá solo dónde está, su tipo y su tamaño. Una por gasto: subir otra la reemplaza.

- **Quién la escribe:** la API (`PUT` y `DELETE /v1/transactions/{id}/receipt`).
- **Ejemplo:** la foto del ticket del almuerzo de 25,50 Bs, en JPEG de 800 KB.
- **Apunta a:** `finance.transactions`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Al borrar el movimiento de verdad (o al usuario), se borra en cascada. Un borrado lógico la deja, pero la API ya no la muestra.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario dueño de la fila | PK (user_id, transaction_id); FK → finance.transactions.user_id |
| transaction_id | UUID | Sí | — | El gasto al que pertenece la foto | PK (user_id, transaction_id); FK → finance.transactions.id (del mismo usuario, en cascada) |
| object_key | texto | Sí | — | Dónde está la imagen en el S3: `{user_id}/{transaction_id}` | — |
| content_type | texto | Sí | — | image/jpeg, image/png o image/webp, según los primeros bytes de la imagen | — |
| size_bytes | entero | Sí | — | Tamaño en bytes, de 1 a 5 MB | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se subió (o reemplazó) | — |

### finance.user_currencies

Mis monedas: las que el usuario ve primero al elegir moneda. Se llena sola con la moneda principal y las de sus cuentas.

- **Quién la escribe:** triggers, y la API cuando el usuario agrega o quita una.
- **Ejemplo:** María tiene BOB y USD.
- **Apunta a:** `catalog.currencies`, `iam.users`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Solo monedas activas; no deja quitar la moneda principal ni la de una cuenta activa (currency_in_use).

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario dueño; parte de la clave primaria | PK (user_id, currency); FK → iam.users.id (en cascada) |
| currency | texto de 3 | Sí | — | Moneda; debe estar activa al agregarla. No se puede quitar la moneda principal ni la de una cuenta activa | FK → catalog.currencies.code; PK (user_id, currency) |
| sort_order | entero | Sí | 0 | Orden en el selector de monedas. Por defecto 0 | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

### finance.user_settings

Configuración financiera de cada usuario (una fila): moneda principal, periodo financiero y ahorro planificado.

- **Quién la escribe:** finance.setup_user() en el onboarding y la API desde Ajustes.
- **Ejemplo:** moneda principal BOB, periodo mensual desde el día 25 (su día de cobro), ahorra 500 Bs por periodo.
- **Apunta a:** `catalog.currencies`, `iam.users`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - La moneda principal entra sola a Mis monedas.
  - Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).
  - La moneda principal debe estar activa.
  - Rechaza un ahorro planificado con más decimales que los de la moneda principal (invalid_amount).
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario dueño; es también la clave primaria (una fila por usuario) | PK; FK → iam.users.id (en cascada) |
| main_currency | texto de 3 | Sí | — | Moneda principal: la que la app muestra primero. Se elige en el onboarding y se cambia en Ajustes; cambiarla no convierte ningún monto. Debe estar activa y entra sola a Mis monedas | FK → catalog.currencies.code |
| period_type | lista fija: weekly, semi_monthly, monthly | Sí | monthly | Cómo agrupa su dinero: weekly (semanal), semi_monthly (quincenal: dos por mes) o monthly (mensual). Por defecto monthly. Lo usan Safe to Spend, Money Flow y Money Story | — |
| period_start_day | entero | Sí | 1 | Día en que empieza el periodo. weekly: día de la semana (0 domingo … 6 sábado). semi_monthly: día d del mes (1 a 13); la segunda quincena empieza el d + 15. monthly: día del mes (1 a 28), por ejemplo su día de cobro. Por defecto 1 | — |
| planned_savings | decimal (19,4) | Sí | 0 | Cuánto quiere ahorrar en cada periodo, en la moneda principal. Safe to Spend de esa moneda lo resta. Por defecto 0 | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

## goals · Metas de ahorro

Metas con su moneda y sus aportes; alimentan el Goal Forecast y Safe to Spend.

### goals.goal_contributions

Aportes y retiros de cada meta, en la moneda de la meta. Su ritmo alimenta el Goal Forecast.

- **Quién la escribe:** la API.
- **Ejemplo:** +300 Bs el 01-10 desde Efectivo; −50 Bs el 10-10 de vuelta a Efectivo.
- **Apunta a:** `finance.accounts`, `finance.transactions`, `goals.goals`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Suma o resta cada aporte al monto ahorrado de la meta.
  - Rechaza un aporte con más decimales que los de la moneda de su meta (invalid_amount).
  - Baja el saldo de la cuenta del aporte, o lo sube si es un retiro (migración 0018).
  - Rechaza una cuenta de otra moneda (currency_mismatch) y un retiro mayor a lo acumulado (goal_insufficient).
  - Rechaza un aporte que pasa lo que le falta a la meta (contribution_exceeds_remaining) y uno a una meta cumplida o archivada (goal_closed) (migración 0024).

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | — |
| goal_id | UUID | Sí | — | Meta; la FK (user_id, goal_id) exige que sea del mismo usuario | FK → goals.goals.id (del mismo usuario, en cascada) |
| amount | decimal (19,4) | Sí | — | Monto del aporte; negativo = retiro. No puede ser 0 | — |
| contributed_on | fecha | Sí | hoy | Fecha del aporte. Por defecto hoy | — |
| source | texto | Sí | manual | manual, transaction o adjustment. Por defecto manual | — |
| transaction_id | UUID | No | — | Transferencia que lo originó; evita contar dos veces el mismo dinero | FK → finance.transactions.id (del mismo usuario, si se borra, queda vacío) |
| note | texto | No | — | Nota opcional (hasta 500 caracteres) | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| account_id | UUID | No | — | Cuenta de donde sale el aporte o a donde vuelve el retiro; su saldo se ajusta solo | FK → finance.accounts.id (del mismo usuario, si se borra, queda vacío) |

### goals.goals

Metas de ahorro: fondo de emergencia, laptop, viaje. Cada meta tiene su moneda; sus aportes pueden salir de una cuenta de esa moneda.

- **Quién la escribe:** la API; current_amount lo mantiene un trigger con los aportes.
- **Ejemplo:** Fondo de emergencia, 5.000 Bs, lleva 450, aporta 300 por periodo.
- **Apunta a:** `catalog.currencies`, `iam.users`
- **La usan:** `goals.goal_contributions`
- **Características:** con seguridad por filas (RLS)
- **Lo que hace la base sola:**
  - Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).
  - La moneda de la meta debe estar activa.
  - Decimales del objetivo (invalid_amount), límite de metas activas del plan (MM001) y meta cumplida al llegar al objetivo.
  - Dos metas vivas del usuario no se llaman igual (goal_name_taken, migración 0021).
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| name | texto | Sí | — | Nombre de la meta (1 a 80 caracteres) | — |
| target_amount | decimal (19,4) | Sí | — | Monto objetivo, mayor que 0 | — |
| currency | texto de 3 | Sí | — | Moneda de la meta y de sus aportes; debe estar activa al crearla | FK → catalog.currencies.code |
| current_amount | decimal (19,4) | Sí | 0 | Monto ahorrado; lo suma un trigger con cada aporte o retiro. Por defecto 0 | — |
| target_date | fecha | No | — | Fecha objetivo (opcional) | — |
| priority | entero | Sí | 3 | Prioridad de 1 (más alta) a 5. Por defecto 3; Can I Afford It? la usa para decidir qué meta se retrasa | — |
| planned_contribution | decimal (19,4) | No | — | Cuánto piensa aportar en cada periodo (semana, quincena o mes), opcional. Safe to Spend lo resta | — |
| status | texto | Sí | active | active, paused, achieved o archived. Por defecto active | — |
| achieved_at | fecha y hora | No | — | Cuándo se alcanzó; existe solo si status es achieved | — |
| icon | texto | No | — | Nombre del ícono que muestra la app | — |
| color | texto | No | — | Color en hexadecimal (#RRGGBB) | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |
| deleted_at | fecha y hora | No | — | Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial | — |

## planning · Decisiones

Presupuestos por categoría e historial de Can I Afford It?. Safe to Spend, Spending Pace y What If? se calculan al momento y no se guardan.

### planning.budgets

Presupuesto mensual por categoría de gasto y moneda. Se repite cada mes hasta que se cambia o se borra; lo no gastado no se acumula. Lo gastado sale de `reports.category_totals` en esa moneda.

- **Quién la escribe:** la API.
- **Ejemplo:** Supermercado 400 Bs por mes; el día 12 lleva 240 Bs (60 %).
- **Apunta a:** `catalog.currencies`, `finance.categories`, `iam.users`
- **Características:** con seguridad por filas (RLS); uno vivo por categoría y moneda; el plan gratuito permite 3 (`planning.budgets`); al borrar la categoría se borran sus presupuestos

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| category_id | UUID | Sí | — | Categoría de gasto del presupuesto | FK → finance.categories (user_id, id, kind) |
| currency | texto de 3 | Sí | — | Solo cuentan los gastos en esta moneda | FK → catalog.currencies.code |
| amount | decimal (19,4) | Sí | — | Monto por mes, mayor que 0, con los decimales de la moneda | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación | — |
| deleted_at | fecha y hora | No | — | Cuándo se borró (borrado lógico) | — |
| category_kind | lista fija | Sí | expense | Siempre expense: amarra la FK a una categoría de gasto | — |
| alert_at_80 | sí/no | Sí | true | Avisar al llegar al 80 % en el mes | — |
| alert_at_100 | sí/no | Sí | true | Avisar al pasar el 100 % en el mes | — |

### planning.affordability_checks

Historial de Can I Afford It?: qué consultó el usuario, el veredicto, el impacto en sus metas y lo que decidió. Cuenta para la North Star.

- **Quién la escribe:** la API.
- **Ejemplo:** Laptop 4.000 Bs → affordable_with_impact, retrasa el Fondo 2 meses; decidió esperar.
- **Apunta a:** `catalog.currencies`, `iam.users`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| description | texto | No | — | Qué quería comprar (opcional, hasta 120 caracteres) | — |
| amount | decimal (19,4) | Sí | — | Monto de la compra, mayor que 0 | — |
| currency | texto de 3 | Sí | — | Moneda del monto | FK → catalog.currencies.code |
| verdict | texto | Sí | — | affordable (alcanza), affordable_with_impact (alcanza retrasando metas) o not_now (todavía no) | — |
| safe_to_spend_before | decimal (19,4) | Sí | — | Safe to Spend antes de la compra | — |
| safe_to_spend_after | decimal (19,4) | Sí | — | Safe to Spend si hace la compra | — |
| earliest_affordable_on | fecha | No | — | Desde cuándo podría comprarlo, cuando el veredicto es not_now | — |
| impacts | JSON | Sí | [] | Metas afectadas y cuántos meses se retrasa cada una, en JSON | — |
| assumptions | JSON | Sí | {} | Supuestos que se mostraron al usuario, en JSON | — |
| algorithm_version | texto | Sí | — | Versión del cálculo, para explicar resultados pasados | — |
| decision | texto | No | — | Lo que hizo el usuario: bought, postponed o dismissed (opcional) | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

## reports · Resúmenes

Money Story semanal y mensual. Los totales del Money Flow y de efectivo o tarjeta se calculan al momento con funciones (ver la sección Funciones).

### reports.money_stories

Resumen semanal (Weekly Check-in) o mensual (Monthly Money Story) por moneda: cuánto ganó, gastó y ahorró, y frases destacadas guardadas como claves.

- **Quién la escribe:** el worker al cerrar la semana o el mes; la API marca viewed_at.
- **Ejemplo:** octubre en BOB: ingresó 5.000, gastó 3.800, ahorró 24 %.
- **Apunta a:** `catalog.currencies`, `iam.users`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| user_id | UUID | Sí | — | Usuario dueño de la fila | Única (user_id, period_type, period_start, currency); FK → iam.users.id (en cascada) |
| period_type | texto | Sí | — | week (Weekly Check-in) o month (Monthly Money Story) | Única (user_id, period_type, period_start, currency) |
| period_start | fecha | Sí | — | Primer día del periodo resumido | Única (user_id, period_type, period_start, currency) |
| period_end | fecha | Sí | — | Último día del periodo resumido | — |
| status | texto | Sí | pending | pending, ready o failed. Por defecto pending | — |
| currency | texto de 3 | Sí | — | Moneda de los totales: hay una historia por moneda con movimientos | FK → catalog.currencies.code; Única (user_id, period_type, period_start, currency) |
| income_total | decimal (19,4) | No | — | Ingresos del periodo | — |
| expense_total | decimal (19,4) | No | — | Gastos del periodo | — |
| savings_total | decimal (19,4) | No | — | Ahorro del periodo (ingresos − gastos) | — |
| savings_rate | decimal (7,4) | No | — | Tasa de ahorro (ahorro ÷ ingresos) | — |
| highlights | JSON | Sí | [] | Frases destacadas como claves y parámetros en JSON, no texto final: se pueden traducir o redactar distinto sin recalcular | — |
| template_version | texto | Sí | — | Versión de las plantillas de texto (`catalog.story_templates`) | — |
| comparison | JSON | No | — | El mes anterior en la misma moneda: ingresos, gastos, ahorro, mayor categoría de gasto y aportes a metas. Null si ese mes no tuvo movimientos en la moneda | — |
| generated_at | fecha y hora | No | — | Cuándo se generó | — |
| viewed_at | fecha y hora | No | — | Cuándo la abrió el usuario | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |

## notify · Notificaciones

Tipos de aviso, lo que el usuario apagó y la bandeja de avisos enviados.

### notify.notification_types

Tipos de aviso que existen y si el usuario los puede apagar (los de seguridad y suscripción no).

- **Quién la escribe:** el equipo.
- **Ejemplo:** recurring.due_soon, activado por defecto.
- **La usan:** `notify.notifications`, `notify.preferences`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| key | texto | Sí | — | Clave del aviso, por ejemplo recurring.due_soon | PK |
| description | texto | Sí | — | Qué avisa | — |
| default_enabled | sí/no | Sí | sí | Si está activo para quien no cambió sus preferencias. Por defecto sí | — |
| is_transactional | sí/no | Sí | no | true = obligatorio (seguridad, suscripción): no se puede desactivar. Por defecto no | — |

### notify.notifications

Bandeja y registro de envíos de cada aviso. Particionada por mes.

- **Quién la escribe:** los workers al encolar y al enviar; la API marca read_at.
- **Ejemplo:** 'Mañana vence tu alquiler de 1.500 Bs', enviada el 30-10.
- **Apunta a:** `iam.users`, `notify.notification_types`
- **Características:** con seguridad por filas (RLS), particionada

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador; la clave primaria es (created_at, id) por estar particionada por mes | PK (created_at, id) |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó; define la partición mensual | PK (created_at, id) |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| type_key | texto | Sí | — | Tipo de aviso | FK → notify.notification_types.key |
| channel | texto | Sí | push | push, email o in_app. Por defecto push | — |
| title | texto | Sí | — | Título (hasta 120 caracteres) | — |
| body | texto | Sí | — | Texto (hasta 500 caracteres) | — |
| data | JSON | Sí | {} | Enlace a la pantalla e ids relacionados, en JSON | — |
| dedupe_key | texto | No | — | Evita enviar el mismo aviso dos veces, por ejemplo recurring:<id>:2026-10 | — |
| status | texto | Sí | queued | queued, sent, failed, skipped o read. Por defecto queued | — |
| scheduled_for | fecha y hora | Sí | ahora | Cuándo debe enviarse | — |
| sent_at | fecha y hora | No | — | Cuándo se envió | — |
| read_at | fecha y hora | No | — | Cuándo lo leyó el usuario | — |
| error | texto | No | — | Error de envío, si lo hubo | — |

### notify.preferences

Avisos que el usuario cambió en Ajustes; sin fila se usa el valor por defecto del tipo.

- **Quién la escribe:** la API.
- **Ejemplo:** María apagó goal.milestone por push.
- **Apunta a:** `iam.users`, `notify.notification_types`
- **Características:** con seguridad por filas (RLS)

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario; parte de la clave primaria | PK (user_id, type_key, channel); FK → iam.users.id (en cascada) |
| type_key | texto | Sí | — | Tipo de aviso; parte de la clave primaria | PK (user_id, type_key, channel); FK → notify.notification_types.key |
| channel | texto | Sí | push | push, email o in_app; parte de la clave primaria. Por defecto push | PK (user_id, type_key, channel) |
| is_enabled | sí/no | Sí | — | Si quiere recibirlo | — |
| updated_at | fecha y hora | Sí | ahora | Última vez que cambió la preferencia | — |

## ai · Registro por voz con IA

Proveedores de IA con principal y respaldos, cada dictado, cada llamada con su costo y el uso por usuario.

### ai.calls

Cada llamada a un proveedor de IA, exitosa o no: estado, latencia, tokens o audio y costo. El detalle de un error va a ops.logs. Particionada por mes.

- **Quién la escribe:** el worker (solo inserta).
- **Ejemplo:** DeepSeek extrajo en 1.400 ms con 800/100 tokens, 0,00036 USD.
- **Apunta a:** `ai.models`, `ai.tasks`
- **Características:** particionada
- **Lo que hace la base sola:**
  - Suma la llamada al dictado (intentos, tokens, costo, modelo que respondió) y al uso mensual del usuario.
  - Calcula el costo de la llamada con el precio del modelo; una llamada que no llegó al proveedor cuesta 0.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador; la clave primaria es (created_at, id) | PK (created_at, id) |
| created_at | fecha y hora | Sí | ahora | Cuándo se hizo la llamada; define la partición mensual | PK (created_at, id) |
| task | texto | Sí | — | Paso: voice.transcribe o voice.extract | FK → ai.tasks.key |
| model_code | texto | Sí | — | Modelo llamado | FK → ai.models.code |
| route_position | entero | Sí | — | Posición del modelo en la ruta: 1 = principal; 2 o más = respaldo | — |
| attempt | entero | Sí | 1 | Número de intento con ese modelo (2 = primer reintento). Por defecto 1 | — |
| status | texto | Sí | — | ok, error, timeout, rate_limited, invalid_output o circuit_open (saltada porque el proveedor venía fallando). El mensaje del error va a ops.logs | — |
| user_id | UUID | No | — | Usuario del dictado (sin FK) | — |
| voice_entry_id | UUID | No | — | Dictado al que pertenece (sin FK) | — |
| voice_entry_created_at | fecha y hora | No | — | Fecha del dictado, para encontrarlo en su partición; va junto con voice_entry_id | — |
| latency_ms | entero | No | — | Cuánto tardó | — |
| audio_seconds | decimal (6,2) | No | — | Segundos de audio enviados (voz a texto) | — |
| input_tokens | entero | No | — | Tokens de entrada (LLM) | — |
| cached_input_tokens | entero | No | — | De esos, cuántos venían de caché (más baratos) | — |
| output_tokens | entero | No | — | Tokens de salida (LLM) | — |
| cost_usd | decimal (12,6) | No | — | Costo en dólares. Si no se envía, lo calcula un trigger con el precio de ai.models; las llamadas que no llegaron al proveedor cuestan 0 | — |

### ai.models

Modelos de IA disponibles con su precio. Agregar un proveedor es un INSERT aquí y una ruta.

- **Quién la escribe:** el equipo.
- **Ejemplo:** openai.gpt-transcribe, 0,0045 USD por minuto.
- **La usan:** `ai.calls`, `ai.routes`, `ai.voice_entries`
- **Lo que hace la base sola:**
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| code | texto | Sí | — | Clave proveedor.modelo, por ejemplo openai.gpt-transcribe | PK |
| provider | texto | Sí | — | Proveedor: openai, groq, deepgram, deepseek, anthropic, google | Única (provider, model) |
| model | texto | Sí | — | Id del modelo que espera la API del proveedor; único por proveedor | Única (provider, model) |
| kind | texto | Sí | — | stt, llm, audio_llm o vision_llm | — |
| price_per_minute_usd | decimal (12,6) | No | — | Precio por minuto de audio; obligatorio en stt | — |
| min_billed_seconds | decimal (6,2) | Sí | 0 | Mínimo que cobra el proveedor por llamada (Groq cobra 10 s). Por defecto 0 | — |
| input_per_mtok_usd | decimal (12,6) | No | — | Precio por millón de tokens de entrada; obligatorio en LLM | — |
| cached_input_per_mtok_usd | decimal (12,6) | No | — | Precio por millón de tokens de entrada en caché | — |
| output_per_mtok_usd | decimal (12,6) | No | — | Precio por millón de tokens de salida; obligatorio en LLM | — |
| is_active | sí/no | Sí | sí | false = no se usa aunque esté en una ruta (apagado de emergencia). Por defecto sí | — |
| shutdown_on | fecha | No | — | Fecha de retiro anunciada por el proveedor; desde ese día sale solo de las rutas | — |
| prices_checked_on | fecha | Sí | — | Cuándo se verificaron los precios | — |
| notes | texto | No | — | Notas para el equipo | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### ai.route_changes

Historial de cambios del orden de proveedores: quién, cuándo, el orden anterior, el nuevo y el motivo.

- **Quién la escribe:** ai.set_route_order().
- **Ejemplo:** Dana puso a DeepSeek de principal por timeouts de OpenAI.
- **Apunta a:** `ai.tasks`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | entero | Sí | — | Número correlativo del cambio | PK |
| task | texto | Sí | — | Paso que cambió | FK → ai.tasks.key |
| changed_at | fecha y hora | Sí | ahora | Cuándo | — |
| changed_by | texto | Sí | — | Quién (correo del equipo) | — |
| old_order | lista de textos | Sí | — | Orden anterior de modelos activos | — |
| new_order | lista de textos | Sí | — | Orden nuevo | — |
| reason | texto | No | — | Motivo, por ejemplo "OpenAI con timeouts" | — |

### ai.routes

Orden de proveedores por tarea: posición 1 = principal, 2+ = respaldos, con tiempo límite y reintentos.

- **Quién la escribe:** el equipo con ai.set_route_order().
- **Ejemplo:** voice.extract → 1 GPT-6 Luna, 2 DeepSeek, 3 Claude Haiku.
- **Apunta a:** `ai.models`, `ai.tasks`
- **Lo que hace la base sola:**
  - El modelo debe ser del tipo que pide la tarea (no se pone un LLM a transcribir).
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| task | texto | Sí | — | Paso; parte de la clave primaria | PK (task, position); FK → ai.tasks.key; Única (task, model_code) |
| position | entero | Sí | — | 1 = principal, 2 = primer respaldo…; parte de la clave primaria | PK (task, position) |
| model_code | texto | Sí | — | Modelo que se usa en esa posición | FK → ai.models.code; Única (task, model_code) |
| is_active | sí/no | Sí | sí | Si la posición se usa. Por defecto sí | — |
| timeout_ms | entero | Sí | 8000 | Tiempo máximo de espera (500 a 60.000 ms) antes de pasar al siguiente. Por defecto 8.000 | — |
| max_retries | entero | Sí | 1 | Reintentos con el mismo modelo antes de pasar al siguiente (0 a 3). Por defecto 1 | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### ai.tasks

Pasos que hace la IA. Una tarea nueva (por ejemplo leer facturas) es una fila más.

- **Quién la escribe:** el equipo.
- **Ejemplo:** voice.transcribe (voz a texto) y voice.extract (frase a movimiento).
- **La usan:** `ai.calls`, `ai.route_changes`, `ai.routes`, `ai.usage_monthly`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| key | texto | Sí | — | Clave del paso, por ejemplo voice.transcribe | PK |
| model_kind | texto | Sí | — | Tipo de modelo que necesita: stt (voz a texto), llm, audio_llm o vision_llm | — |
| description | texto | Sí | — | Qué hace el paso | — |

### ai.usage_monthly

Uso de IA por usuario, mes y tarea: llamadas, fallas, audio, tokens y costo. Permite contar cuánto usa y cuánto cuesta cada usuario sin recorrer ai.calls.

- **Quién la escribe:** un trigger de ai.calls.
- **Ejemplo:** María, octubre, voice.extract: 24 llamadas, 1 fallida, 0,0086 USD.
- **Apunta a:** `ai.tasks`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| user_id | UUID | Sí | — | Usuario (sin FK: el registro de costos sobrevive aunque se borre el usuario); parte de la clave primaria | PK (user_id, period, task) |
| period | fecha | Sí | — | Mes (siempre el día 1); parte de la clave primaria | PK (user_id, period, task) |
| task | texto | Sí | — | Tarea: voice.transcribe o voice.extract; parte de la clave primaria | PK (user_id, period, task); FK → ai.tasks.key |
| calls | entero | Sí | 0 | Llamadas hechas en el mes, sumando reintentos y respaldos | — |
| failed_calls | entero | Sí | 0 | De esas, cuántas no respondieron bien (status distinto de ok) | — |
| audio_seconds | decimal (12,2) | Sí | 0 | Segundos de audio enviados (voz a texto) | — |
| input_tokens | entero | Sí | 0 | Tokens de entrada enviados al LLM | — |
| output_tokens | entero | Sí | 0 | Tokens de salida recibidos del LLM | — |
| cost_usd | decimal (14,6) | Sí | 0 | Costo total en dólares, incluidas las llamadas fallidas que se cobraron | — |
| updated_at | fecha y hora | Sí | ahora | Última vez que se sumó una llamada | — |

### ai.voice_entries

Cada dictado (o frase escrita) y su resultado: transcripción, movimiento extraído, modelos que respondieron, intentos y costo. Particionada por mes.

- **Quién la escribe:** la API lo crea; el worker y los triggers de ai.calls lo completan.
- **Ejemplo:** 'gasté 50 en comida' → gasto de 50 BOB en Restaurantes, confirmado.
- **Apunta a:** `ai.models`, `finance.transactions`, `iam.users`
- **Características:** con seguridad por filas (RLS), particionada

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador; la clave primaria es (created_at, id) | PK (created_at, id) |
| created_at | fecha y hora | Sí | ahora | Cuándo se recibió; define la partición mensual | PK (created_at, id) |
| user_id | UUID | Sí | — | Usuario dueño de la fila | FK → iam.users.id (en cascada) |
| input_type | texto | Sí | voice | voice (dictado) o text (frase escrita). Por defecto voice | — |
| status | texto | Sí | received | received, transcribed, extracted, confirmed, discarded o failed. Por defecto received | — |
| audio_seconds | decimal (6,2) | No | — | Duración del audio; solo en dictados | — |
| audio_object_key | texto | No | — | Ruta del audio en Cloud Storage, solo si el usuario acepta guardarlo | — |
| transcript | texto | No | — | Texto transcrito o escrito (hasta 2.000 caracteres) | — |
| stt_model_code | texto | No | — | Modelo de voz a texto que respondió; lo completa la base de datos | FK → ai.models.code |
| llm_model_code | texto | No | — | LLM que respondió; lo completa la base de datos | FK → ai.models.code |
| prompt_version | texto | No | — | Versión del prompt, para comparar precisión entre versiones | — |
| extraction | JSON | No | — | Movimiento extraído en JSON: tipo, monto, moneda, categoría, cuenta, descripción, fecha y lo que falta | — |
| confidence | decimal (4,3) | No | — | Confianza del LLM entre 0 y 1 | — |
| attempts | entero | Sí | 0 | Llamadas hechas sumando respaldos. Por defecto 0 | — |
| fallback_used | sí/no | Sí | no | true si algún paso lo resolvió un respaldo. Por defecto no | — |
| input_tokens | entero | Sí | 0 | Tokens de entrada sumados. Por defecto 0 | — |
| output_tokens | entero | Sí | 0 | Tokens de salida sumados. Por defecto 0 | — |
| cost_usd | decimal (12,6) | Sí | 0 | Costo total del dictado, incluidas las llamadas fallidas. Por defecto 0 | — |
| latency_ms | entero | No | — | Tiempo de punta a punta; lo escribe el worker | — |
| transaction_id | UUID | No | — | Transacción creada al confirmar; si se borra, queda vacío y el dictado se conserva | FK → finance.transactions.id (del mismo usuario, si se borra, queda vacío) |
| error | texto | No | — | Error, si falló | — |
| confirmed_at | fecha y hora | No | — | Cuándo lo confirmó el usuario | — |

## ops · Logs e incidentes

Eventos importantes del sistema (solo inserción) e incidentes con su ciclo de vida. No guarda datos financieros.

### ops.incident_affected_users

Usuarios afectados por cada incidente, para avisarles o compensarlos.

- **Quién la escribe:** ops.log() cuando el error tiene usuario.
- **Ejemplo:** INC-000012 afectó a María; avisada el 15-10.
- **Apunta a:** `ops.incidents`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| incident_id | UUID | Sí | — | Incidente; parte de la clave primaria | FK → ops.incidents.id (en cascada); PK (incident_id, user_id) |
| user_id | UUID | Sí | — | Usuario afectado (sin FK); parte de la clave primaria | PK (incident_id, user_id) |
| first_seen_at | fecha y hora | Sí | ahora | Cuándo lo afectó por primera vez | — |
| notified_at | fecha y hora | No | — | Cuándo se le avisó | — |

### ops.incident_updates

Línea de tiempo de cada incidente: cambios de estado y severidad, y notas del equipo.

- **Quién la escribe:** triggers de ops.incidents y el equipo.
- **Ejemplo:** 10:05 open → investigating, por dana@moneymap.team.
- **Apunta a:** `ops.incidents`

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| incident_id | UUID | Sí | — | Incidente | FK → ops.incidents.id (en cascada) |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| author | texto | Sí | system | Quién hizo el cambio (correo del equipo o system). Por defecto system | — |
| status_from | texto | No | — | Estado anterior | — |
| status_to | texto | No | — | Estado nuevo | — |
| severity_from | texto | No | — | Severidad anterior | — |
| severity_to | texto | No | — | Severidad nueva | — |
| note | texto | No | — | Nota del equipo | — |
| is_public | sí/no | Sí | no | Si se puede comunicar a los usuarios. Por defecto no | — |

### ops.incidents

Agrupa errores repetidos con la misma huella y sigue su ciclo: abierto → investigando → identificado → monitoreo → resuelto → cerrado, con responsable y causa raíz.

- **Quién la escribe:** ops.log() abre o suma; el equipo cambia el estado.
- **Ejemplo:** INC-000012, sev3, push.fcm.timeout, 37 ocurrencias.
- **La usan:** `ops.incident_affected_users`, `ops.incident_updates`
- **Lo que hace la base sola:**
  - Escribe la primera entrada de la línea de tiempo.
  - Al cambiar estado o severidad, completa las fechas y escribe la línea de tiempo.
  - updated_at se actualiza solo en cada cambio.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| number | entero | Sí | nextval('ops.incident_number_seq') | Número correlativo; único | Única |
| code | texto | Calculado | ('INC-'\|\| lpad((number), 6, '0')) | INC- más el número con 6 dígitos (INC-000123) | — |
| title | texto | Sí | — | Título (1 a 200 caracteres) | — |
| description | texto | No | — | Descripción | — |
| severity | texto | Sí | — | sev1 (caída total o datos incorrectos) a sev4 (menor) | — |
| status | texto | Sí | open | open, investigating, identified, monitoring, resolved o closed. Por defecto open | — |
| category | texto | Sí | — | Categoría del log que lo abrió | — |
| fingerprint | texto | No | — | Huella de los errores agrupados; solo un incidente abierto por huella | Única, si ((fingerprint IS NOT NULL) AND (status <> ALL (ARRAY['resolved'::text, 'closed'::text]))) |
| detected_by | texto | Sí | automatic | automatic, monitoring, user_report o manual. Por defecto automatic | — |
| previous_incident_id | UUID | No | — | Incidente resuelto del que este es una regresión | FK → ops.incidents.id |
| first_seen_at | fecha y hora | Sí | ahora | Primera ocurrencia | — |
| last_seen_at | fecha y hora | Sí | ahora | Última ocurrencia | — |
| occurrences | entero | Sí | 1 | Veces que ocurrió. Por defecto 1 | — |
| affected_users | entero | Sí | 0 | Usuarios distintos afectados. Por defecto 0 | — |
| assigned_to | texto | No | — | Persona del equipo a cargo | — |
| acknowledged_at | fecha y hora | No | — | Cuándo el equipo lo tomó | — |
| resolved_at | fecha y hora | No | — | Cuándo se resolvió; existe solo en resolved o closed | — |
| closed_at | fecha y hora | No | — | Cuándo se cerró | — |
| impact | texto | No | — | Impacto en los usuarios | — |
| root_cause | texto | No | — | Causa raíz | — |
| resolution | texto | No | — | Cómo se resolvió | — |
| postmortem_url | texto | No | — | Enlace al análisis posterior | — |
| created_at | fecha y hora | Sí | ahora | Cuándo se creó la fila | — |
| updated_at | fecha y hora | Sí | ahora | Última modificación; la actualiza un trigger | — |

### ops.logs

Eventos importantes del sistema, de solo inserción: errores, fallos de integraciones (tiendas, IA, push), eventos de seguridad y jobs. Nadie puede editar ni borrar un log. Particionada por mes.

- **Quién la escribe:** la API y los workers con ops.log().
- **Ejemplo:** warning ai.call.timeout de GPT-6 Luna.
- **Características:** particionada
- **Lo que hace la base sola:**
  - Impide editar o borrar un log.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador; la clave primaria es (occurred_at, id) | PK (occurred_at, id) |
| occurred_at | fecha y hora | Sí | ahora | Cuándo ocurrió; define la partición mensual | PK (occurred_at, id) |
| level | texto | Sí | — | debug, info, notice, warning, error o critical | — |
| severity | entero | Calculado |  CASE level     WHEN 'debug'THEN 10     WHEN 'info'THEN 20     WHEN 'notice'THEN 30     WHEN 'warning'THEN 40     WHEN 'error'THEN 50     ELSE 60 END | Se calcula desde level (10 a 60) para ordenar y filtrar | — |
| category | texto | Sí | — | api, auth, security, billing, finance, ai, notify, integration, job, database, client o system | — |
| event_code | texto | Sí | — | Código estable del evento, por ejemplo billing.webhook.invalid_signature | — |
| message | texto | Sí | — | Descripción legible | — |
| service | texto | Sí | — | Quién lo escribió: api, worker, scheduler, ios, android, web o database | — |
| environment | texto | Sí | — | prod, staging o dev | — |
| release | texto | No | — | Versión de la app o commit desplegado | — |
| user_id | UUID | No | — | Usuario afectado (sin FK) | — |
| device_id | UUID | No | — | Dispositivo afectado | — |
| request_id | texto | No | — | Id de la petición | — |
| trace_id | texto | No | — | Id de traza, para seguir una petición entre servicios | — |
| http_method | texto | No | — | Método HTTP | — |
| http_path | texto | No | — | Ruta de la API | — |
| http_status | entero | No | — | Código HTTP | — |
| duration_ms | entero | No | — | Duración | — |
| error_type | texto | No | — | Tipo de excepción, por ejemplo TimeoutError | — |
| error_message | texto | No | — | Mensaje del error | — |
| stack_trace | texto | No | — | Traza del error | — |
| fingerprint | texto | No | — | Huella que agrupa errores iguales en un incidente | — |
| incident_id | UUID | No | — | Incidente al que se sumó (errores y critical); sin FK | — |
| context | JSON | Sí | {} | Datos extra en JSON; nunca contraseñas, tokens ni números de tarjeta | — |
| ip | IP | No | — | IP de origen | — |

## core · Infraestructura

Auditoría de cambios y eventos pendientes de publicar (outbox).

### core.audit_log

Historial de quién cambió qué dato sensible (cuentas, configuración, metas, suscripciones), solo con las columnas que cambiaron. Particionada por mes.

- **Quién la escribe:** triggers de auditoría.
- **Ejemplo:** María cambió el nombre de su cuenta de 'Efectivo' a 'Billetera'.
- **Características:** particionada

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador; la clave primaria es (occurred_at, id) | PK (occurred_at, id) |
| occurred_at | fecha y hora | Sí | ahora | Cuándo; define la partición mensual | PK (occurred_at, id) |
| actor_user_id | UUID | No | — | Quién hizo el cambio | — |
| owner_user_id | UUID | No | — | De quién es el dato cambiado | — |
| entity | texto | Sí | — | Tabla, por ejemplo finance.accounts | — |
| entity_id | UUID | No | — | Id de la fila | — |
| action | texto | Sí | — | insert, update, delete, login, export o plan_change | — |
| changes | JSON | No | — | Columnas cambiadas con su valor antes y después, en JSON | — |
| ip | IP | No | — | IP de origen | — |

### core.outbox_events

Eventos de dominio pendientes de publicar (patrón outbox): se escriben en la misma transacción que el cambio y un worker los envía a Celery.

- **Quién la escribe:** la API y los workers; el worker los marca publicados.
- **Ejemplo:** transaction.created de María.

| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |
|---|---|---|---|---|---|
| id | UUID | Sí | UUID v7 | Identificador único (UUID v7, ordenado por fecha de creación) | PK |
| aggregate_type | texto | Sí | — | Tipo de entidad: transaction, goal, subscription… | — |
| aggregate_id | UUID | Sí | — | Id de la entidad | — |
| user_id | UUID | No | — | Dueño del dato, si aplica | — |
| event_type | texto | Sí | — | Evento, por ejemplo transaction.created | — |
| payload | JSON | Sí | {} | Datos del evento en JSON | — |
| occurred_at | fecha y hora | Sí | ahora | Cuándo ocurrió | — |
| published_at | fecha y hora | No | — | Cuándo se publicó; vacío = pendiente | — |
| attempts | entero | Sí | 0 | Intentos de publicación. Por defecto 0 | — |

## Listas fijas (ENUM)

Valores que no cambian; la base no acepta otros.

| Tipo | Valores | Qué significa |
|---|---|---|
| `catalog.money_kind` | income, expense, transfer | income suma al saldo, expense resta, transfer mueve entre dos cuentas propias. |
| `catalog.flow_group` | needs, lifestyle | Grupo de gasto del Money Flow: needs (Necesidades) o lifestyle (Estilo de vida). |
| `finance.period_type` | weekly, semi_monthly, monthly | weekly (semanal), semi_monthly (quincenal: dos por mes, desde el día d y el d + 15) o monthly (mensual). |
| `finance.frequency` | weekly, biweekly, monthly, yearly | Cada cuánto se repite un recurrente: weekly (semana), biweekly (2 semanas), monthly (mes) o yearly (año). |
| `finance.transaction_source` | manual, quick_add, voice, scan, recurring, onboarding, adjustment | Cómo se registró un movimiento: manual, quick_add, voice, scan, recurring, onboarding o adjustment. |

## Vistas

No guardan datos: calculan al consultarlas y respetan la seguridad por filas de quien consulta.

| Vista | Qué muestra |
|---|---|
| `ai.monthly_cost_by_model` | Costo real de IA por modelo, tarea y mes, incluidas las llamadas fallidas. |
| `ai.monthly_cost_by_user` | Dictados por usuario y mes: cuántos, confirmados, con respaldo, confianza promedio y costo. |
| `ai.provider_health_24h` | Salud de cada proveedor de IA en las últimas 24 horas: llamadas, fallas, tasa de error, veces que salvó como respaldo, latencia p50/p95 y costo. |
| `billing.price_catalog` | Pantalla de planes: precio mensual, anual, precio por mes pagando el año y porcentaje de ahorro. |
| `billing.user_entitlements` | Qué puede hacer cada usuario según su plan y cuánto lleva usado. |
| `billing.user_plans` | Plan efectivo. on_hold y paused muestran su estado pero dan el plan gratuito hasta que se recupere el pago. |
| `finance.account_balances` | Saldo de cada cuenta activa en su moneda, con el banco y los últimos 4 dígitos si es tarjeta. |
| `finance.balance_totals` | Totales por moneda para el Map: total, en efectivo y en tarjetas. Nunca suma monedas distintas. |
| `ops.error_summary_24h` | Errores y advertencias de las últimas 24 horas agrupados por código, con usuarios afectados. |
| `ops.open_incidents` | Tablero del equipo: incidentes abiertos por severidad y última vez que ocurrieron. |

## Funciones

Las que llama la API o los workers. Los nombres de parámetros están en las migraciones.

| Función | Qué hace |
|---|---|
| `ai.route(text)` | Orden vigente de proveedores de una tarea (activos y no retirados). El worker lo lee y puede cachearlo 60 s. |
| `ai.set_route_order(text,text[],text)` | Define principal y respaldos de una tarea en un solo paso y deja el cambio en ai.route_changes. |
| `billing.limit_status(uuid,text)` | Para mostrar "1 de 1 tarjetas": límite, usado, restante y si puede agregar otra. |
| `billing.process_due_subscriptions(timestamp with time zone)` | Aplica cambios programados, expira suscripciones canceladas al terminar su periodo y pasa a on_hold las de gracia vencida. |
| `billing.release(uuid,text,integer)` | Revierte try_consume en el mes actual. No baja de 0. |
| `billing.resource_usage(uuid,text)` | Cuántos recursos vivos tiene el usuario de una funcionalidad: tarjetas, monedas o metas activas. |
| `billing.try_consume(uuid,text,integer)` | true si el plan permite la acción. Tras bajar a gratuito, los datos existentes se conservan pero no se pueden crear más por encima del límite. |
| `catalog.assert_currency_active(character)` | Falla con currency_unavailable si la moneda no existe o está desactivada. |
| `core.drop_partitions_older_than(regclass,date)` | Retención: elimina particiones mensuales completas anteriores a p_before. |
| `core.ensure_monthly_partitions(regclass,date,integer)` | Crea las particiones mensuales que falten desde p_from durante p_months meses. Idempotente. |
| `core.uuid_v7()` | Genera un UUID versión 7 (48 bits de timestamp en ms + aleatorio). |
| `finance.assert_amount_decimals(numeric,character)` | Rechaza un monto con más decimales que los de su moneda (1000.5 en CLP o PYG): HINT invalid_amount. |
| `finance.current_period(uuid,date)` | Inicio y fin del periodo del usuario. Safe to Spend, Money Flow y Money Story usan este rango. |
| `finance.next_occurrence(date,finance.frequency,date)` | Próximo vencimiento de un recurrente después de una fecha. El worker lo usa para avanzar next_due_on. |
| `finance.recurring_occurrences(date,finance.frequency,date,date)` | Las veces de un recurrente desde next_due_on hasta una fecha. Las usan Safe to Spend y la lista de recurrentes. |
| `finance.period_bounds(finance.period_type,smallint,date)` | Periodo que contiene la fecha: monthly día 25 → del 25 al 24 del mes siguiente; semi_monthly día 1 → 1-15 y 16-fin de mes; weekly día 1 → lunes a domingo. |
| `finance.recalculate_account_balance(uuid,uuid)` | Recalcula el saldo de una cuenta desde cero (conciliación nocturna o soporte) y lo devuelve. |
| `finance.setup_user(uuid,character,text)` | Crea la configuración financiera (la moneda principal entra a Mis monedas) y copia las categorías iniciales. Idempotente. |
| `finance.suggest_from_history(uuid,text)` | Categoría y cuenta que el usuario usó la última vez con esa descripción. Reemplaza a la antigua tabla categorization_memory. |
| `ops.log(text,text,text,text,jsonb,text,uuid,text,text,text,text,text,text,text,integer,integer,text,text,uuid,inet)` | Registra un evento. error y critical abren o suman a un incidente. Devuelve el id del log, o NULL si está bajo app.log_min_level. |
| `reports.category_totals(uuid,date,date)` | Cuánto entró o salió por categoría y moneda entre dos fechas. Sin transferencias ni borrados. |
| `reports.money_flow(uuid,date,date)` | Nodos del Money Flow por moneda: income, cada grupo de gasto, goals y available (ingresos − gastos − metas). |
| `reports.payment_method_totals(uuid,date,date)` | Gastos e ingresos en efectivo (cash) y con tarjeta (card), por moneda, entre dos fechas. |

## Tablas futuras

Están en `future/` y se aplican cuando cada funcionalidad entre al alcance; no forman parte de este diccionario hasta entonces.

| Archivo | Qué agrega |
|---|---|
| `future/120_scenarios.sql` | Escenarios guardados de What If? (FTR-011) |
| `future/130_attachments.sql` | Comprobantes adjuntos y OCR (FTR-030) |
| `future/140_insights.sql` | Insights y fugas de dinero (FTR-016, FTR-017) |
