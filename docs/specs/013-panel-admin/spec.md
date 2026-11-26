# Spec 013 — Panel de administrador de planes (API)

## Contexto y objetivo
Todavía no hay cobros (MM-186): toda cuenta empieza en el gratuito y elige su plan. Para ajustar los planes sin escribir SQL, un único administrador gestiona desde la web los planes vigentes: nombre, descripción, si se muestran, sus precios y qué funcionalidades tiene cada uno con qué límite. MM-189 (back) y MM-190 (web).

## Usuarios / actores
- El administrador: un usuario normal con `iam.users.is_admin = true`. Entra con el mismo login.
- Cualquier otro usuario: no ve ni puede usar el panel.

## Requisitos funcionales (EARS)
- RF-1: CUANDO llega `GET /v1/me`, EL SISTEMA responde `is_admin` para que la web muestre el panel solo al administrador.
- RF-2: CUANDO el administrador pide `GET /v1/admin/plans`, EL SISTEMA responde los planes vigentes con sus precios activos, cada funcionalidad del catálogo (activa o no y su límite) y cuántos usuarios tiene cada plan.
- RF-3: CUANDO el administrador corrige un plan (`PATCH /v1/admin/plans/{code}`), EL SISTEMA guarda nombre, descripción y visibilidad; el gratuito no se oculta (409 `free_plan_required`).
- RF-4: CUANDO el administrador fija una funcionalidad de un plan (`PUT …/features/{key}`), EL SISTEMA la guarda y vale al instante. `limit` null es ilimitado; una de sí o no no lleva límite (422 `invalid_limit`). Bajar un límite no borra nada: solo impide crear más.
- RF-5: CUANDO el administrador fija un precio (`PUT …/prices/{period}/{currency}`), EL SISTEMA cierra el precio activo y abre otro; las suscripciones que ya existen siguen con el suyo. El gratuito no tiene precio (409 `free_plan_required`).
- RF-6: CUANDO el administrador pide `GET /v1/admin/plan-changes`, EL SISTEMA responde los últimos cambios auditados a planes, funcionalidades y precios.
- RF-7: SI quien llama no es el administrador, ENTONCES las rutas `/v1/admin` responden 404 y la base rechaza cualquier escritura (`42501`, HINT `admin_required`).

## Requisitos no funcionales
- A lo sumo un administrador: índice único parcial sobre `iam.users (is_admin)`.
- Toda escritura pasa por funciones `billing.admin_*` SECURITY DEFINER que vuelven a mirar el rol, y queda en `core.audit_log`.

## Cómo se nombra al administrador
Con el script, desde `moneymap-back` y con la base levantada:

```bash
uv run python -m app.scripts.make_admin correo@dominio.com [--nombre Ana] [--apellido Quispe]
```

Pide la contraseña dos veces sin mostrarla. Si el correo no tiene cuenta, la crea ya verificada; si la tiene, le pone esa contraseña. En los dos casos la deja como el único administrador (el anterior deja de serlo). Usa la conexión del dueño de la base (`MIGRATIONS_DATABASE_URL`). En el servidor se corre con el servicio `migrate`, que es el que tiene esa conexión: `docker compose run --rm -it migrate python -m app.scripts.make_admin correo@dominio.com`.

A mano, con el dueño de la base, para una cuenta que ya existe:

```sql
UPDATE iam.users SET is_admin = true WHERE email = '<correo del administrador>';
```

Para cambiarlo, primero `is_admin = false` al actual.

## Criterios de finalización
- Cada RF con al menos un test (`tests/integration/test_billing_admin.py`).
- `docs/api.md` y `db/DICCIONARIO_CAMPOS.md` al día.

## Trazabilidad
| RF | Ticket | Estado |
|---|---|---|
| RF-1 a RF-7 | MM-189 | Hecho |

## Dudas abiertas
- [NECESITA ACLARACIÓN] ¿El administrador podrá más adelante cambiar el plan de un usuario o crear planes nuevos? Hoy no: solo los dos vigentes, Gratuito y Premium.
