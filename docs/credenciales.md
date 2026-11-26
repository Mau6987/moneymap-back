# Credenciales

Dónde se consigue cada credencial, cómo se llama la variable y dónde va. En dev
todo esto es opcional; en staging y producción van en las variables de entorno de Dokploy (`.env.prod.example`).

Los valores locales van en `.env` (que no se versiona). `.env.example` tiene las
variables con un ejemplo. **Ningún valor real va en el repositorio.**

---

## Correo saliente (SMTP)

Lo usan la verificación del correo y el restablecimiento de la contraseña.

En dev alcanza con lo que viene por defecto, `EMAIL_BACKEND=log`, que **escribe el
link en el log de la API** en vez de mandarlo. Fuera de dev la API **no arranca**
con `log`, porque el link es una credencial y no puede quedar en los logs.

Para que el correo salga de verdad:

```dotenv
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu-cuenta@gmail.com
SMTP_PASSWORD=la-contraseña-de-aplicación
SMTP_STARTTLS=true
EMAIL_FROM=tu-cuenta@gmail.com
```

Puerto **587 con `SMTP_STARTTLS=true`** es lo habitual (Gmail, el correo de la
empresa). Si tu proveedor pide TLS directo, es el **465 con `SMTP_STARTTLS=false`**.

### Gmail, paso a paso

Gmail no acepta la contraseña de la cuenta: pide una **contraseña de aplicación**,
que es un secreto de 16 caracteres solo para esta integración.

1. **Activá la verificación en dos pasos.** Entrá a <https://myaccount.google.com/security>
   → *Verificación en dos pasos* y completala. Sin esto el paso 3 no existe.
   *(Si la cuenta es de Google Workspace, el administrador tiene que permitir las
   contraseñas de aplicación.)*
2. Entrá a <https://myaccount.google.com/apppasswords> (también está en
   *Seguridad* → *Contraseñas de aplicaciones*).
3. Escribí un nombre, por ejemplo `MoneyMap API`, y tocá **Crear**.
4. Google muestra **16 caracteres en cuatro grupos** (`abcd efgh ijkl mnop`).
   Copialos **sin los espacios**.
5. Ese valor es `SMTP_PASSWORD`. `SMTP_USER` y `EMAIL_FROM` son **la misma
   dirección completa** (`tu-cuenta@gmail.com`): Gmail rechaza otro remitente.

**Ojo:** Gmail permite unos 500 destinatarios por día y es para probar, no para
producción. Cuando la app tenga usuarios reales conviene un proveedor dedicado
(Resend, SES, SendGrid) o el correo del dominio con su propio SMTP; el cambio es
solo estas variables.

Para probar que salió:

```bash
docker compose logs -f db >/dev/null &   # (opcional) para ver la base
EMAIL_BACKEND=smtp uv run uvicorn app.main:app --reload
# Pedí el link y mirá tu bandeja:  POST /v1/auth/email-verifications
```

Si el correo no llega, revisá **spam** y que `SMTP_USER` y `EMAIL_FROM` sean la
misma cuenta.

---

## Ingreso con Google

El backend **verifica el token que le manda la app**, así que lo único que
necesita es el **Client ID de tipo Web**. El secreto **no** hace falta: no se
intercambia código en el servidor.

### Google Cloud, paso a paso

1. Entrá a <https://console.cloud.google.com/> y **creá un proyecto** (por ejemplo
   `MoneyMap`).
2. **Pantalla de consentimiento de OAuth** (*APIs y servicios* → *Pantalla de
   consentimiento de OAuth*; en pantallas nuevas aparece como *Marca* + *Público*):
   - Tipo de usuario: **Externo** (los usuarios son de cualquier cuenta de Google).
   - Nombre de la app, correo de asistencia y correo del desarrollador.
   - Permisos (`scopes`): `openid`, `email` y `profile`. Nada más: no pedimos
     acceso a Drive ni a Gmail.
   - Mientras la app esté en modo *Prueba*, agregá en **Usuarios de prueba** las
     cuentas de Google con las que vas a probar.
3. **Credenciales** (*APIs y servicios* → *Credenciales* → *Crear credenciales* →
   *ID de cliente de OAuth*). Se crean **tres**, una por plataforma:
   - **Android**: pide el **nombre del paquete** (`applicationId`, por ejemplo
     `app.moneymap`) y la **huella SHA-1** de la clave con la que se firma la app.
     La saca el equipo de la app con
     `keytool -list -v -keystore <keystore> -alias <alias>`.
   - **iOS**: pide el **bundle ID**.
   - **Web**: no pide nada más que un nombre.
4. Copiá el **Client ID de tipo Web** (termina en
   `.apps.googleusercontent.com`) → esa es la variable `GOOGLE_CLIENT_ID` de la
   API.

### Dónde va cada uno de los tres

**Solo el de Web va en el backend.** Los otros dos son de la app.

| Lo que creaste en Google | Dónde va |
|---|---|
| Cliente de **Android** (el paquete y la huella SHA-1) | **En la app**: en `android/app/google-services.json` o en la configuración de Google Sign-In del proyecto Flutter. **La API no lo usa** |
| Cliente de **iOS** | **En la app**: en su `Info.plist` o en la configuración del plugin |
| Cliente de **Web** | **En la app**, como `serverClientId`, **y en la API** como `GOOGLE_CLIENT_ID` |

Es el único de los tres que va en el `.env` del backend (o en las variables de Dokploy).

**Ojo con la huella SHA-1:** vale la de la clave con la que se firma de verdad.
Para probar en local es la del *debug keystore*; para la versión que se publica es
la de **Play App Signing**, que el Play Console muestra en *Protección de Play →
Firma de apps de Play*. Si probás con la de debug y después publicás, el ingreso con
Google deja de andar en la app publicada: hay que registrar las dos (o crear dos
clientes de Android, uno por clave).

### Por qué el de Web y no el de Android

La app hace el ingreso con Google de forma nativa y le pide a Google un **token de
identidad**. Ese token trae en `aud` (audiencia) el Client ID para el que fue
emitido, y la API **rechaza cualquier token que no sea para el suyo**.

Para que el token llegue con la audiencia correcta, la app pide el token **con el
Client ID de Web como `serverClientId`** (así lo llaman los SDK de Android y
Flutter). Por eso:

- el equipo de la app configura los ids de **Android** e **iOS** en la app;
- la API valida con el de **Web**.

Si el token llegara con el de Android, la API responde `401` y el log dice que la
audiencia no coincide: no es un bug de la app, es que falta pasar el de Web.

### Apple

El ingreso con Apple se verifica **sin secretos**: la API comprueba el token con las
claves públicas de Apple (`https://appleid.apple.com/auth/keys`). No hace falta la
clave `.p8`, ni el `APPLE_TEAM_ID`, ni el `APPLE_KEY_ID`: esos son para el flujo que
canjea el código de autorización, que acá no se usa.

Lo que sí hay que configurar es **a quién va dirigido el token** (la audiencia), que
depende de quién lo pida:

| Cliente | Audiencia | De dónde sale |
|---|---|---|
| App iOS | `com.moneymap.moneymapApp` (el bundle ID) | Xcode → Runner → Signing & Capabilities |
| Web | El **Service ID** (por ejemplo `com.moneymap.web`) | Apple Developer → Identifiers → Services IDs |

Van en **`APPLE_CLIENT_IDS`**, separadas por coma. Basta con las que existan:

```dotenv
APPLE_CLIENT_IDS=com.moneymap.moneymapApp
```

Cuando esté el Service ID de la web:

```dotenv
APPLE_CLIENT_IDS=com.moneymap.moneymapApp,com.moneymap.web
```

Sin `APPLE_CLIENT_IDS`, la ruta `/v1/auth/oauth/apple` responde `401`.

**En la app iOS** hay que habilitar la capacidad *Sign in with Apple* en Xcode (con el
mismo bundle ID) y marcar el App ID con esa capacidad en el portal de Apple. La app
manda el `identityToken` que devuelve `ASAuthorizationAppleIDCredential`.

**Ojo con el correo:** Apple lo manda **solo la primera vez** que la persona autoriza
la app. En los ingresos siguientes el token no lo trae, y eso está contemplado: la
cuenta se encuentra por el `sub`, no por el correo. Si es una cuenta nueva y no vino el
correo, la app lo pide al completar el registro (RF-7). El correo privado de Apple
(`@privaterelay.appleid.com`) es válido: la API no distingue.

---

## Resumen de variables

| Variable | Se usa para | En dev |
|---|---|---|
| `JWT_SECRET` | Firmar los tokens de acceso | En `.env`, obligatorio |
| `PUBLIC_BASE_URL` | La base del link que va en el correo | `http://localhost:8000` |
| `EMAIL_BACKEND` | `log` o `smtp` | `log` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `EMAIL_FROM` | Enviar los correos | Comentadas |
| `GOOGLE_CLIENT_ID` | Verificar el token de Google | Comentada |
| `APPLE_CLIENT_IDS` | Verificar el token de Apple (bundle ID y Service ID) | Comentada |
