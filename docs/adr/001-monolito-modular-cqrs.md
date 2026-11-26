# ADR-001 · Monolito modular con CQRS por casos de uso

- **Estado:** aceptado
- **Fecha:** 2026-10-15
- **Alcance:** backend (`moneymap-back`)
- **Cambia:** la sección 3.3 de `docs/engineering.md` (la que hablaba de `service.py` y `repository.py`)

## Contexto

La API era un esqueleto: nueve módulos con el router vacío y `app/core/` con la
configuración, la sesión por usuario y la traducción de errores. Lo que existe,
está probado y manda es `db/`: quince migraciones con triggers, claves foráneas
compuestas, RLS y funciones (`finance.setup_user`, `finance.current_period`,
`finance.balance_totals`), más 71 pruebas de humo.

De ahí sale la restricción que decide todo: **las reglas del dinero viven en
PostgreSQL**. La constitución §3 lo dice con todas las letras — "La API no
duplica esas validaciones: las deja actuar y traduce el error a una respuesta
clara" — y la sección 3.3 de `engineering.md` proponía `router.py` →
`service.py` → `repository.py`, con un solo archivo de reglas por módulo.

Con siete specs y alrededor de noventa requisitos funcionales, ese `service.py`
único termina siendo un archivo de cientos de líneas, contra el límite de 300
líneas de `engineering.md` §3.1.1, y mezcla la escritura con la lectura.

Se pidió trabajar con CQRS y DDD para que el backend sea escalable y modular.

## Decisión

**Monolito modular con DDD táctico pragmático y CQRS por caso de uso** dentro
de cada módulo de `app/modules/<módulo>/`.

| Pieza | Responsabilidad |
|---|---|
| `router.py` | HTTP: valida con el esquema, llama al caso de uso, devuelve el esquema. Sin SQL y sin reglas. |
| `schemas.py` | Pydantic: la forma de lo que entra y de lo que sale. |
| `application/commands/<verbo>_<sustantivo>.py` | Un caso de uso de escritura por requisito funcional. |
| `application/queries/<nombre>.py` | Un caso de uso de lectura por consulta; devuelve un read model. |
| `domain/models.py` | Los read models del módulo. |
| `domain/ports.py` | `Protocol`: lo que la aplicación necesita, sin saber cómo se guarda. |
| `domain/errors.py` | Los errores del módulo, con su `code`. |
| `infrastructure/*.py` | El SQL con SQLAlchemy. Implementa los puertos. Sin reglas. |
| `deps.py` | El único lugar donde la aplicación y la infraestructura se encuentran. |

1. **La dirección es `router → application → domain`, e `infrastructure`
   implementa `domain`.** La aplicación nunca importa infraestructura.
2. **CQRS se aplica en el código, no en la infraestructura.** Comandos y
   consultas se separan en archivos distintos; hay una sola base de datos, una
   sola transacción y ningún bus.
3. **Los read models no son agregados.** El lado de lectura proyecta con SQL
   (vistas, CTEs, `finance.balance_totals`) y devuelve un DTO; el lado de
   escritura devuelve lo que quedó guardado, no una entidad rica.
4. **El dominio en Python es fino y solo lo que es puro y reutilizable.** Hoy
   `app/core/money/` (`Money` y el código de moneda), que codifica la
   constitución §2: `Decimal` exacto, los decimales de cada moneda como dato y
   ninguna operación entre monedas distintas.
5. **Ningún caso de uso revalida lo que la base ya aplica.** Traduce el error
   con `core/errors.py` (`SQLSTATE MM001` → 409 `plan_limit`, `HINT` → su
   estado). El esquema valida solo la *forma* —código ISO 4217, cuatro dígitos,
   monto en texto—, que es lo que evita un 500 por un `CHECK` sin `HINT`.
6. **Sin SQLAlchemy ORM.** El SQL es `text()` con parámetros y `mappings()`: el
   esquema real es `db/` y mapear 48 tablas a clases sería duplicarlo.
7. **Sin dependencias nuevas.** No hay bus, ni mediador, ni contenedor: FastAPI
   arma las piezas con `Depends` y la sesión por usuario de `core/db.py`.

## Alternativas descartadas

- **DDD completo: agregados ricos, eventos de dominio y bus interno.**
  Duplicaría en Python las invariantes que ya aplica PostgreSQL (triggers de
  saldo, claves compuestas, `MM001`, RLS), contra la constitución §3, y
  agregaría código que nadie ejecuta (`engineering.md` §3.4.5). Los eventos de
  dominio ya tienen su lugar: `core.outbox_events`, que un módulo escribe en la
  misma transacción.
- **Un `service.py` por módulo (la sección 3.3 anterior).** Choca con el límite
  de 300 líneas y no separa la lectura de la escritura; con dos o tres specs
  encima hay que partirlo igual, pero sin una regla que diga cómo.
- **Un microservicio por módulo.** La V1 es un equipo chico con un solo
  despliegue en Cloud Run; la modularidad se consigue con carpetas y puertos sin
  pagar red, despliegues y consistencia distribuida.
- **CQRS con base de lectura aparte o event sourcing.** No hay volumen ni
  proyecciones que lo justifiquen, y multiplica las piezas a mantener.

## Consecuencias

- Un requisito funcional de la spec se lee directo como un caso de uso: por RF de
  escritura, un archivo en `application/commands/`; por consulta, uno en
  `application/queries/`. El nombre del test y el de la spec quedan alineados.
- Los archivos quedan cortos por construcción: el límite de 300 líneas deja de
  ser una pelea en cada revisión.
- La aplicación se puede probar con un repositorio falso y la infraestructura
  contra PostgreSQL real, sin mocks del ORM.
- Cuesta un archivo más por operación y una indirección (`ports.py`, `deps.py`).
  Es el precio de poder cambiar el SQL sin tocar las reglas.
- **Obliga a actualizar `docs/engineering.md`:** §3.3 (capas del backend), §2.4 y
  §2.5 (cobertura por capa). Ese documento es espejo con `moneymap-app`, así que
  el cambio se aplicó también en la copia de la app en el mismo momento.

## Pendientes que deja abiertos

- **Identidad del usuario.** Resuelta con la spec 001: `get_current_user_id` verifica el
  JWT y de ahí sale `app.user_id`. Las pruebas de los módulos ya autenticados inyectan
  el usuario con `dependency_overrides`; las de `iam` usan el token de verdad.
- **Errores de la base sin `HINT`.** Resuelto el 2026-10-17 (spec 002, RF-24 y
  RF-25): el nombre de cuenta repetido es 409 `account_name_taken` y la
  institución que no existe, 422 `validation_error`, por `CONSTRAINT_PROBLEMS`.
- **El commit ocurre al cerrar la dependencia de sesión**, después de armar la
  respuesta. Eso ya mordió una vez: un `ApiError` hace que la dependencia haga
  *rollback*, así que el corte de seguridad de RF-18 se perdía. La solución fue el
  puerto `UnitOfWork` (`domain/ports.py`), que confirma esa escritura antes de
  responder 401. La regla que queda: **cuando una escritura tiene que sobrevivir al
  error que viene después, se confirma explícitamente**; no alcanza con el cierre de
  la dependencia.
- **CI.** Las reglas de `engineering.md` secciones 1, 2 y 3 siguen dependiendo de
  la disciplina (§6.9). Sin pipeline, esta arquitectura se puede erosionar.
