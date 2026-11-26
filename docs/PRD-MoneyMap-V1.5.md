# PRD MoneyMap V1

**Última actualización:** Oct 23, 2026 · @Brandon Garcia

## Contenido

- [1. Resumen](#1-resumen)
- [2. Visión y problema](#2-visión-y-problema)
- [3. Objetivos de la V1 y criterios de éxito](#3-objetivos-de-la-v1-y-criterios-de-éxito)
- [4. Usuarios objetivo](#4-usuarios-objetivo)
- [5. Alcance de la V1](#5-alcance-de-la-v1)
- [6. Requerimientos funcionales](#6-requerimientos-funcionales)
- [7. Requerimientos no funcionales](#7-requerimientos-no-funcionales)
- [8. Modelo de datos](#8-modelo-de-datos)
- [9. Navegación y experiencia principal](#9-navegación-y-experiencia-principal)
- [10. Stack técnico y arquitectura](#10-stack-técnico-y-arquitectura)
- [11. Fuera del alcance de la V1](#11-fuera-del-alcance-de-la-v1)
- [12. Plan y estimaciones](#12-plan-y-estimaciones)
- [13. Riesgos y decisiones abiertas](#13-riesgos-y-decisiones-abiertas)
- [14. Historial de cambios](#14-historial-de-cambios)

---

## 1. Resumen

La V1 de MoneyMap incluye las 18 funcionalidades que el equipo marcó en verde, las notificaciones (FTR-023) y 6 funcionalidades que el equipo amplió para esta versión: Presupuestos (FTR-014), Spending Pace (FTR-015), Financial Forecast (FTR-020), Escaneo de facturas con IA (FTR-030), What If? (FTR-011) y Weekly Money Check-in (FTR-021). El plazo es de **15 días hábiles**, con QA incluido.

| Campo | Valor |
|---|---|
| Proyecto | MoneyMap |
| Equipo | Team Nexus Bo 1 |
| Manager | Danaé Castro |
| Tipo | SaaS de gestión de finanzas personales |
| Plataforma V1 | Web responsive y app móvil para iOS y Android, con Flutter |
| Objetivo de la V1 | Que una persona registre y organice sus ingresos y gastos, controle sus presupuestos, sepa cuánto puede gastar sin afectar sus metas y simule decisiones antes de tomarlas |
| Fuente del alcance | Matriz de Features y Feasibility V1: columna Consenso Equipo = Verde, más FTR-023, FTR-014, FTR-015, FTR-020, FTR-030, FTR-011 y FTR-021 promovidas por el equipo |
| Plazo estimado | 15 días hábiles (3 semanas), QA incluido |
| Versión | 1.5, del 14 de octubre de 2026 (ver Historial de cambios) |
| Estado | Borrador para revisión del equipo |

## 2. Visión y problema

MoneyMap es un "GPS financiero": muestra dónde está el dinero del usuario, hacia dónde va y qué puede hacer a continuación. La V1 lleva esa idea a lo esencial: registrar movimientos rápido, ver el mapa del dinero, controlar presupuestos, saber cuánto se puede gastar y simular qué pasaría antes de decidir.

Muchas personas llevan sus finanzas entre notas del teléfono, hojas de Excel, apps bancarias y memoria. Así no saben cuánto gastaron, cuánto les queda, en qué gastan más ni si avanzan hacia sus metas.

| Pregunta del usuario | Cómo la responde la V1 |
|---|---|
| ¿Cuánto dinero tengo? | Financial Position (FTR-012) y multicuenta (FTR-003) |
| ¿Dónde se va mi dinero? | Money Flow (FTR-013) e historial (FTR-006) |
| ¿Cuánto puedo gastar sin meterme en problemas? | Safe to Spend (FTR-009) |
| ¿Me estoy pasando en alguna categoría? | Presupuestos (FTR-014) y Spending Pace (FTR-015) |
| ¿Puedo permitirme esta compra? | Can I Afford It? (FTR-010) |
| ¿Qué pasa si cambia mi ingreso o sumo un gasto fijo? | What If? (FTR-011) |
| ¿Cómo estaré en 30, 60 y 90 días? | Financial Forecast (FTR-020) |
| ¿Cuándo llegaré a mi meta? | Goals y Goal Forecast (FTR-018, FTR-019) |
| ¿Cómo me fue esta semana y este mes? | Weekly Money Check-in (FTR-021) y Monthly Money Story (FTR-022) |

**Tagline:** *Your money. Mapped.*

## 3. Objetivos de la V1 y criterios de éxito

La V1 tiene éxito si un usuario nuevo entiende su situación financiera en su primera sesión y vuelve para tomar decisiones con ella.

| Criterio | Meta | Origen |
|---|---|---|
| Del registro a la primera transacción | Menos de 5 minutos | PRD §3 |
| Registrar una transacción con Quick Add | Menos de 10 segundos | PRD §12, FTR-004 |
| Registrar una transacción escaneando una factura | Menos de 15 segundos, de la foto a confirmar | FTR-030 (propuesta) |
| Explicación de Safe to Spend | El desglose del cálculo se ve con un clic | PRD §9.2 |
| North Star: usuarios que toman una acción financiera informada | Meta numérica por definir | PRD §38 |

En la V1 cuentan como acción informada: crear una meta o aportar a ella, crear o ajustar un presupuesto, analizar una compra con Can I Afford It?, simular un escenario con What If? y marcar un gasto como recurrente.

Todo cálculo sigue los principios del PRD: claridad antes que complejidad, cálculos transparentes y la decisión final siempre en manos del usuario.

## 4. Usuarios objetivo

La V1 se diseña para quien quiere control de su dinero sin herramientas complejas, y para quien ahorra con una meta concreta.

| Persona | Qué necesita | Qué usa en la V1 |
|---|---|---|
| The Organizer (principal) | Saber cuánto gana, gasta y puede ahorrar cada mes, sin armar un Excel | Quick Add, registro por voz, escaneo de facturas, Money Flow, Presupuestos, Spending Pace, Safe to Spend, Weekly Check-in |
| The Goal Setter (secundaria) | Alcanzar una meta: una computadora, un viaje, un fondo de emergencia, pagar una deuda o una vivienda | Goals, Goal Forecast, Can I Afford It?, What If?, Financial Forecast |

MoneyMap es solo para mayores de 18 años. La categoría de ingreso "mesada familiar" (FTR-031) se mantiene para jóvenes adultos que aún reciben apoyo de su familia.

## 5. Alcance de la V1

Entran a la V1 las 18 filas en verde de la matriz, las notificaciones (FTR-023) y 6 funcionalidades ampliadas para esta versión: 4 desde amarillo (FTR-014, FTR-015, FTR-020, FTR-030) y 2 desde rojo (FTR-011, FTR-021). Las 25 filas suman **10 días y 6 horas** de desarrollo; con preparación y QA, el total es de 15 días (ver sección 12).

Las estimaciones se redujeron respecto de la versión 1.3 porque el diseño de base de datos ya existe (48 tablas y la tabla de presupuestos escrita), y porque las funcionalidades nuevas reusan piezas ya planificadas: el motor de proyección de Safe to Spend, el agente de IA del registro por voz y las plantillas de Money Story.

| ID | Funcionalidad | Módulo | Prioridad PRD | Estimación | Nota de implementación |
|---|---|---|---|---|---|
| FTR-001 | Autenticación y plataforma SaaS multiplataforma | Core y SaaS | P0 | 3 horas | Registro por cualquier método; identifica el tipo de usuario |
| FTR-025 | Login visual y biometría | Identificación y seguridad | P0 | 3 horas | Google, Meta y usuario registrado; huella o rostro en móvil |
| Sin ID | Planes SaaS | Core y SaaS | P0 | 1 hora | Plan gratuito y 3 planes de pago; límites como datos |
| FTR-024 | Ajustes de cuenta, moneda y preferencias | Configuración | P0 | 4 horas | Incluye cambio de contraseña |
| FTR-002 | Onboarding guiado | Core y SaaS | P0 | 2 horas | Solo en el primer inicio, con los pasos esenciales |
| FTR-003 | Gestión multicuenta | Cuentas | P0 | 1 día y 2 horas | CRUD de monedas, cuentas, categorías, gastos e ingresos |
| FTR-004 | Registro rápido (Quick Add) | Transacciones | P0 | Incluido en FTR-003 | Formulario de menos de 10 s |
| FTR-005 | Categorización de transacciones | Transacciones | P0 | Incluido en FTR-003 | Con categorías iniciales |
| FTR-031 | Ingresos laborales y emprendimientos | Ingresos | P0 | 1 hora | Categorías iniciales de ingreso (datos semilla) |
| FTR-006 | Historial, filtros y búsqueda | Transacciones | P0 | 3 horas | Fechas, categorías y texto, con paginación |
| FTR-007 | Registro por voz con agente IA | Nuevo requerimiento | Nuevo | 1 día | Un proveedor por paso más un respaldo; el resto de respaldos en la V1.1 |
| FTR-030 | Escaneo de facturas con IA | Transacciones | Ampliada (amarillo) | 6 horas | Reusa el agente de extracción de FTR-007 con un modelo que lee imágenes |
| FTR-012 | Financial Position | Dashboard | P0 | 2 horas | UI frontend |
| FTR-013 | Money Flow | Dashboard | P0 | 4 horas | UI frontend; funciona como reporte |
| FTR-009 | Safe to Spend | GPS financiero | P0 Estrella | 6 horas | Motor financiero base |
| FTR-010 | Can I Afford It? | GPS financiero | P1 Estrella | 4 horas | Reusa el motor de Safe to Spend |
| FTR-011 | What If? | GPS financiero | Ampliada (rojo) | 6 horas | Simulación sobre el motor de proyección; no guarda escenarios |
| FTR-020 | Financial Forecast a 30, 60 y 90 días | GPS financiero | Ampliada (amarillo) | 4 horas | Reusa el motor de proyección |
| FTR-014 | Presupuestos por categoría | Presupuestos | Ampliada (amarillo) | 6 horas | La tabla ya está escrita (`future/110_budgets.sql`) |
| FTR-015 | Spending Pace | Presupuestos | Ampliada (amarillo) | 2 horas | Cálculo sobre los totales por categoría |
| FTR-018 | Metas de ahorro | Goals | P1 | 2 horas | CRUD de metas |
| FTR-019 | Goal Forecast | Goals | P1 | 1 hora | Reusa el motor de proyección |
| FTR-022 | Monthly Money Story | Reportes | P1 | 3 horas | Aviso push al cerrar el mes (FTR-023) |
| FTR-021 | Weekly Money Check-in | Reportes | Ampliada (rojo) | 2 horas | Reusa las plantillas de Money Story con periodo semanal |
| FTR-023 | Notificaciones orientadas a acción | Notificaciones | P1 | 3 horas | Incluye alertas de presupuesto |

## 6. Requerimientos funcionales

Cada módulo lista lo que la V1 debe hacer y cómo se comprueba. Lo marcado como **propuesta** sale de este PRD y debe validarlo el equipo.

### 6.1 Acceso, cuenta y ajustes (FTR-001, FTR-025, FTR-024)

- Registro e inicio de sesión con correo y contraseña, Google o Meta.
- Sesión con JWT, válida en web y en la app móvil híbrida con la misma cuenta.
- En móvil, desbloqueo con huella o rostro usando la biometría del dispositivo, después del primer inicio de sesión.
- Perfil con nombre, apellido, cómo quiere que lo llame la app y foto; opcionalmente teléfono, país, ciudad y ocupación (estudiante, empleado, independiente, emprendedor, sin empleo, jubilado u otra).
- Personalización guardada en el servidor, igual en todos los dispositivos: tema (del teléfono, claro u oscuro), color de acento, modo privado (oculta los montos) y día de inicio de semana.
- Ajustes: moneda principal (BOB, USD, EUR u otra del catálogo), cuenta por defecto, Mis monedas (las que aparecen primero al elegir moneda), periodo financiero (semanal, quincenal o mensual, desde el día que elija, por ejemplo su día de cobro), ahorro planificado por periodo, edición del perfil, personalización y cambio de contraseña.
- Al registrarse, el usuario indica nombre, apellido y fecha de nacimiento (solo mayores de 18 años) y acepta la versión vigente de los términos y la política de privacidad; el sistema identifica su plan.

**Criterios de aceptación:**

- [ ] Se crea una cuenta con cada uno de los tres métodos y se entra con ella desde web y móvil.
- [ ] Una fecha de nacimiento de menos de 18 años bloquea el registro, también con Google o Meta.
- [ ] La app no guarda datos biométricos; solo usa la validación del sistema operativo.
- [ ] Cambiar la moneda principal cambia qué moneda muestra primero el Map; ningún monto se convierte.
- [ ] El tema, el color de acento, el modo privado y el inicio de semana se ven iguales al entrar desde otro dispositivo.

### 6.2 Planes y suscripciones (sin ID)

- La V1 tiene un plan gratuito y tres planes de pago; sus nombres, límites y precios están por definir.
- Cada plan de pago se cobra mensual o anual, por App Store o Google Play.
- El usuario puede cambiar de plan o de periodo y cancelar. Al cancelar conserva el plan de pago hasta el último día pagado y después vuelve al gratuito sin perder datos; si tiene más tarjetas, metas o presupuestos que el límite gratuito, los conserva y los sigue usando, pero no puede agregar nuevos hasta bajar del límite.
- Si falla un cobro, la tienda reintenta durante un periodo de gracia en el que el usuario mantiene su plan; si no se logra cobrar, pasa al gratuito hasta que pague.
- Precios y límites viven en la base de datos, así que cambiarlos no exige desplegar código.
- Al iniciar sesión, la app lee el plan del usuario y habilita sus opciones.
- **Propuesta** de límites para diferenciar los planes: número de tarjetas, metas y presupuestos, dictados por voz y escaneos de facturas al mes, y usos de Can I Afford It? y What If?. Valores provisionales del gratuito: 1 tarjeta y 1 moneda (Bs o USD, la que elija), 2 metas, 3 presupuestos, 30 dictados, 10 escaneos y 10 consultas al mes entre Can I Afford It? y What If?. Los planes de pago permiten varias tarjetas y monedas (sin tope hasta que el equipo fije cuántas por plan).

**Criterios de aceptación:**

- [ ] Un usuario sin suscripción tiene los límites del plan gratuito.
- [ ] Al cancelar, conserva el plan de pago hasta el fin del periodo y después vuelve al gratuito con todos sus datos.
- [ ] Si vuelve al gratuito con 4 tarjetas y cuentas en 2 monedas (límites 1 y 1), las sigue usando para registrar, pero no puede agregar ni desarchivar otra tarjeta ni abrir otra moneda.
- [ ] Al volver a un plan de pago, puede agregar tarjetas de nuevo hasta el límite de ese plan.

### 6.3 Onboarding guiado (FTR-002)

El onboarding aparece una sola vez, en el primer inicio de sesión, y solo pide lo esencial para calcular Safe to Spend:

1. Bienvenida y moneda principal: *Let's map your money.*
2. Su efectivo y su tarjeta (el gratuito permite una), con su saldo actual. La primera cuenta queda como cuenta por defecto.
3. Ingreso mensual.
4. Gastos recurrentes (alquiler, servicios, transporte).
5. Resultado: *Your MoneyMap is ready*, con Ingresos, Comprometido y Safe to Spend.

La primera meta, los presupuestos y el ahorro planificado se agregan después, desde Goals, el Map y Ajustes. El paso "¿Qué quieres lograr?" queda fuera, como indica el PRD §31.

**Criterios de aceptación:**

- [ ] Un usuario nuevo termina el onboarding y registra su primera transacción en menos de 5 minutos.

### 6.4 Cuentas y monedas (FTR-003)

- Tipos de cuenta: efectivo y tarjeta, las dos con saldo. No se distingue débito de crédito ni se lleva cupo. No hay cuentas bancarias, billeteras ni pagos con QR en la V1.
- Cada cuenta tiene nombre, tipo, una sola moneda y saldo inicial. Los datos propios de las tarjetas (banco emisor y últimos 4 dígitos) se guardan aparte. El banco se elige de una lista de instituciones financieras del país del usuario (bancos, cooperativas, microfinancieras y billeteras), que el equipo mantiene sin desplegar código. Para tener efectivo en Bs y en dólares se crean dos cuentas de efectivo.
- Tarjetas y monedas según el plan: el plan gratuito permite 1 tarjeta y cuentas en 1 sola moneda; los planes de pago permiten varias tarjetas y varias monedas. Cuántas permite cada plan está por definir (6.2) y se cambia en la base de datos sin desplegar código. El efectivo no tiene límite.
- Si el usuario baja a un plan con menos tarjetas, conserva las que tiene y las sigue usando; solo no puede agregar otra. Archivar una tarjeta libera su lugar.
- El saldo de una tarjeta sube y baja con sus movimientos, como el efectivo. Pasar dinero entre efectivo y tarjeta es una transferencia de la misma moneda.
- Cuenta por defecto: la que la app propone primero en Quick Add, voz y escaneo, sea efectivo o tarjeta. Hay una sola por usuario aunque tenga varias tarjetas y monedas. La primera cuenta queda por defecto y el usuario la cambia en Ajustes; si la archiva, pasa a la siguiente.
- MoneyMap no tiene tipos de cambio ni convierte monedas. Cada cuenta tiene una moneda y todo lo que pasa en ella queda en esa moneda; solo se transfiere entre cuentas de la misma moneda.
- La moneda es configurable en tres niveles: el equipo define qué monedas ofrece la app y puede agregar o desactivar una sin desplegar código (12 al inicio: BOB, USD, EUR, GBP, ARS, BRL, CLP, COP, MXN, PEN, PYG y UYU); el usuario elige su moneda principal y arma Mis monedas en Ajustes; y elige la moneda de cada cuenta. Cada movimiento queda en la moneda de su cuenta.
- Mis monedas aparece primero en el selector de moneda. Se llena sola con la moneda principal y las de sus cuentas; el usuario agrega o quita otras, salvo la principal y las de sus cuentas activas.
- Las cuentas son personales: solo su dueño las ve. No hay cuentas compartidas ni roles entre usuarios.
- Se muestra el saldo de cada cuenta y un total por moneda (total, en efectivo y en tarjetas), con la moneda principal primero. Nunca se suman bolivianos con dólares.
- CRUD de cuentas (efectivo y tarjetas), Mis monedas, categorías de gasto e ingreso, gastos e ingresos.

**Criterios de aceptación:**

- [ ] Un gasto se registra en la moneda de su cuenta; un gasto en USD en una tarjeta en Bs se rechaza y la app propone una cuenta en USD.
- [ ] Una transferencia entre cuentas de distinta moneda se rechaza.
- [ ] Solo hay dos métodos de pago: efectivo, desde una cuenta de efectivo, y tarjeta, desde una tarjeta. La app no ofrece QR.
- [ ] En el plan gratuito la app no deja agregar una tarjeta y muestra los planes; con un plan de pago deja agregar tarjetas hasta el límite de ese plan.
- [ ] El selector de moneda muestra primero Mis monedas y no ofrece monedas desactivadas; lo ya registrado en una moneda desactivada se conserva.
- [ ] Con cuentas en Bs y en USD, el Map muestra un total en Bs y otro en USD, con la moneda principal primero.
- [ ] La primera cuenta queda como cuenta por defecto; marcar otra desmarca la anterior y siempre hay una sola.
- [ ] En el plan gratuito la app deja agregar una tarjeta, pero no una segunda tarjeta ni una cuenta en otra moneda, y muestra los planes.
- [ ] Ningún otro usuario puede ver ni modificar las cuentas de un usuario.

### 6.5 Registro rápido: Quick Add (FTR-004)

- Campos: tipo (ingreso o gasto), monto, categoría, cuenta (efectivo o una de sus tarjetas), fecha, descripción y recurrente (sí/no). Lo que pasó ("Netflix", "Almuerzo") va en la descripción; no hay campos aparte de comercio, hora ni notas. La moneda y si pagó en efectivo o con tarjeta salen del tipo de la cuenta.
- **Propuesta:** solo tipo, monto y categoría son obligatorios. La fecha es hoy, la cuenta es la cuenta por defecto y la moneda es la de la cuenta.
- Si el usuario tiene varias cuentas, la app preselecciona la que usó la última vez con esa descripción; si no hay historial, su cuenta por defecto.
- Si pagó en dólares con una tarjeta en Bs, registra lo que le cobró el banco, en Bs. La app no convierte.
- En móvil, el botón **+** es la acción principal de la app; desde él se elige escribir, dictar (FTR-007) o escanear una factura (FTR-030).
- Al guardar, se actualizan el saldo, el Money Flow, Safe to Spend, los presupuestos, Spending Pace, el Forecast y las metas.

**Criterios de aceptación:**

- [ ] Registrar un gasto de $35 en Comida toma menos de 10 segundos.

### 6.6 Categorías de gasto e ingreso (FTR-005, FTR-031)

- La app trae categorías iniciales con ícono y color; el usuario puede crear, editar y borrar las suyas.
- Cada categoría de gasto pertenece a un grupo del Money Flow: Necesidades o Estilo de vida. Es una lista fija en la base de datos; el nombre y el color de cada grupo los define la app.
- Las categorías de ingreso distinguen salario, trabajo freelance o emprendimiento y mesada familiar.
- Sugerencia por reglas, sin IA: si la descripción coincide con una transacción anterior, se propone su categoría ("Netflix" → Entretenimiento / Suscripción). El usuario la acepta o la cambia.
- El aprendizaje automático de categorías queda en el backlog.

**Criterios de aceptación:**

- [ ] Un usuario nuevo encuentra las categorías iniciales de gasto e ingreso, con ícono y color.
- [ ] Si registra "Netflix" en una categoría, la próxima vez que escriba "Netflix" la app le propone esa categoría.
- [ ] Solo hay categorías, sin subcategorías; un gasto no se puede registrar en una categoría de ingreso.

### 6.7 Registro por voz con agente IA (FTR-007)

El usuario dice lo que gastó o recibió, como se lo diría a una persona, y un agente con LLM lo convierte en un movimiento listo para confirmar.

> 🖼️ *[Diagrama: registro por voz · 2 pasos con principal y respaldos — imagen no incluida en el texto original]*

Si los proveedores de un paso fallan, el usuario no pierde el registro: lo escribe en Quick Add.

- Ejemplos de frases: "Gasté 50 en comida", "Registra 10 Bs de taxi en efectivo", "Me pagaron 3.000 de sueldo", "Pagué 15 dólares de Netflix con la Visa".
- El LLM extrae tipo (ingreso o gasto), monto, moneda, categoría (de las del usuario), cuenta (efectivo o cuál tarjeta), descripción ("Netflix") y fecha ("ayer", "el lunes"). Efectivo o tarjeta sale de la cuenta. Lo que la frase no dice toma los valores por defecto de Quick Add: hoy, la última cuenta usada y su moneda. Si dice "con tarjeta" y el usuario tiene varias, la app preselecciona la que usó la última vez con esa descripción o, si no hay historial, su cuenta por defecto, y la deja cambiar al confirmar. Si la frase nombra una moneda ("15 dólares"), la app propone una cuenta en esa moneda; si no tiene ninguna, le pide elegir o crear una, sin convertir el monto.
- Si falta el monto o el LLM no está seguro de un dato, la app lo pide en lugar de adivinarlo.
- **Propuesta:** la app siempre muestra el movimiento prellenado y el usuario lo confirma o corrige con un toque antes de guardar.
- **Propuesta:** una frase registra un movimiento; si el usuario dicta dos, la app le pide registrarlos por separado.
- **Propuesta:** la frase también se puede escribir en lugar de dictarla; usa el mismo agente, sin el paso de voz a texto.
- Cada paso (voz a texto y LLM) tiene un proveedor principal y respaldos. Si el principal no responde a tiempo, devuelve un error o un resultado inválido, el sistema pasa al siguiente sin que el usuario lo note. Si fallan todos, la app abre Quick Add y el dictado no descuenta la cuota.
- **Ajuste por plazo:** la V1 sale con un principal y un respaldo por paso, los dos modelos propios. Otro modelo se suma después como una fila nueva de AIRoute, sin cambiar código.
- El principal de cada paso se elige con la prueba de concepto y se cambia desde la base de datos, sin publicar una versión de la app ni desplegar el backend.
- Privacidad: el audio y la frase se procesan en nuestro propio servidor y no salen de él. Al LLM van solo la frase y los nombres de las categorías, cuentas y monedas del usuario, nunca saldos ni historial. El audio no se guarda salvo que el usuario lo acepte.
- Cada plan tiene una cuota de dictados al mes (30 en el gratuito, provisional).

**Criterios de aceptación:**

- [ ] Una frase con monto y concepto produce un movimiento correcto listo para confirmar.
- [ ] "Pagué 15 dólares de Netflix con la Visa", con una Visa en USD, llega con 15 USD, la categoría de suscripciones, la cuenta Visa y el pago con tarjeta; si su Visa es en Bs, la app le pide elegir una cuenta en USD o registrar lo que le cobró el banco.
- [ ] Si el proveedor principal no responde en el tiempo límite, el respaldo completa el registro y el usuario no ve un error.
- [ ] Cambiar el proveedor principal no requiere publicar la app ni desplegar el backend.

#### Modelos propios, sin API paga

Los dos pasos corren en nuestro propio servidor con modelos abiertos: no hay API paga ni costo por dictado, y ni el audio ni la frase salen del servidor. El costo es fijo, el del VPS.

**Paso 1 · Voz a texto** (servicio `stt`, propio)

| Modelo | Papel | A favor | En contra |
|---|---|---|---|
| NVIDIA Parakeet TDT 0.6B v3 (ONNX, int8) | Principal | Muy rápido en CPU (menos de 1 s por frase); licencia CC-BY-4.0, uso comercial citando la fuente | Entrenado sobre todo con español de España: hay que medirlo con frases bolivianas |
| Whisper large-v3-turbo con faster-whisper (int8) | Respaldo | Mejor con ruido y acentos; licencia MIT | Más lento en CPU (2 a 5 s por frase) |
| Reconocimiento del teléfono (iOS y Android) | Alternativa | El audio no sale del teléfono | La precisión cambia según el dispositivo; no es un respaldo del servidor |

**Paso 2 · LLM que extrae el movimiento** (servicio `llm`, Ollama)

| Modelo | Papel | A favor | En contra |
|---|---|---|---|
| Qwen 3.5 4B (Q4_K_M) | Principal | Más nuevo que Qwen3 y del mismo tamaño; muy bueno en español y en salidas estructuradas; licencia Apache 2.0. Se usa sin "pensar" (`think: false`) | En la laptop de pruebas tarda unos 10 s por frase (20 s con el modelo frío); pensando no termina a tiempo |
| Gemma 3 4B (Q4_K_M) | Respaldo | Otra familia (Google): no comete los mismos errores que el principal; su licencia permite uso comercial | Un poco menos preciso con fechas relativas |

Ollama obliga a que la respuesta siga el esquema JSON del movimiento, así el modelo no puede devolver algo mal armado. Las instrucciones fijas quedan en caché y en cada dictado solo se procesa lo que cambia.

**Dónde corren:** en `docker-compose.ai.yml`, un compose independiente del de la API, para reiniciarlo o actualizarlo sin tocarla y poder llevarlo a otro servidor. En el mismo servidor, el worker lo llama por la red interna `moneymap-ai`; en otro, por la red privada entre los dos (`AI_STT_URL`, `AI_LLM_URL`) y los puertos se publican solo en esa IP privada (`AI_BIND`), nunca hacia afuera. En el VPS (12 núcleos y 48 GB de RAM, sin GPU) se usa CPU: `stt` necesita unos 4 a 6 GB y `llm` unos 6 a 7 GB con los dos modelos cargados, y un dictado tarda de 4 a 8 s de punta a punta. Cada servicio atiende un dictado a la vez, para no quitarle CPU a la API. Los modelos (unos 8 GB) se descargan al primer arranque en volúmenes de Docker, no en el repositorio. En desarrollo, el LLM puede ser Ollama de escritorio: el worker lo apunta con `LLM_BASE_URL`.

Se descartan las APIs pagas (GPT-Transcribe, Whisper en Groq, Deepgram, GPT-6 Luna, Claude Haiku, DeepSeek y Gemini): no hay costo por dictado y ningún dato sale del servidor. Como todo corre en la misma máquina, una caída del servidor apaga los dos pasos: en ese caso la app ofrece Quick Add, como cuando fallan todos los modelos.

**Recomendación:** por el plazo de 15 días, la prueba de concepto se reduce a unas 50 frases reales en español de Bolivia (montos en bolivianos y dólares, comercios locales, "ayer", métodos de pago), midiendo precisión y latencia p95 en cada paso. Orden provisional en la base de datos: transcribir con Parakeet y, si falla, con Whisper; extraer con Qwen 3.5 y, si falla, con Gemma 3. Si la prueba muestra que el respaldo acierta más, se invierte el orden con `ai.set_route_order`, sin desplegar. La cuota de voz por plan sirve para evitar abusos y para no saturar el servidor.

**Fuentes:** Parakeet TDT 0.6B v3 (NVIDIA, Hugging Face), Whisper large-v3-turbo (OpenAI, código abierto), Qwen 3.5 (Alibaba, Ollama), Gemma 3 (Google), Ollama.

### 6.8 Historial, filtros y búsqueda (FTR-006)

- Lista cronológica de transacciones, la más reciente primero, con paginación.
- Búsqueda por texto ("Amazon"), monto ("$100"), categoría, método de pago, moneda y rango de fechas.
- Filtros combinables, por ejemplo: Comida + septiembre + más de $50.
- Cada transacción se puede editar o borrar desde la lista.

**Criterios de aceptación:**

- [ ] Buscar "Amazon" muestra solo las transacciones cuya descripción contiene esa palabra.
- [ ] El filtro Comida + septiembre + más de $50 muestra solo las transacciones que cumplen las tres condiciones.
- [ ] Editar o borrar una transacción desde la lista actualiza el saldo de su cuenta y el presupuesto de su categoría.

### 6.9 Map: Financial Position (FTR-012)

- Es la pantalla principal de la app.
- Muestra el mes en curso: saldo disponible, ingresos (+), gastos (−) y ahorrado, por moneda, con la principal primero.
- El dato destacado es Safe to Spend, no el saldo.
- **Propuesta:** debajo, dos tarjetas compactas: Presupuestos con su Spending Pace (6.16 y 6.17) y Forecast a 30 días (6.18), cada una con acceso a su detalle.

**Criterios de aceptación:**

- [ ] Al abrir la app, el Map muestra Safe to Spend como dato principal, junto con los ingresos, los gastos y lo ahorrado en el mes.

### 6.10 Safe to Spend (FTR-009)

Safe to Spend dice cuánto dinero queda libre después de las obligaciones del periodo (semana, quincena o mes, según lo que eligió el usuario).

```
Safe to Spend = Saldo actual − Pagos recurrentes pendientes − Ahorro planificado − Aportes a metas
```

| Concepto | Ejemplo del PRD |
|---|---|
| Saldo actual | $2,500 |
| Pagos recurrentes pendientes | −$700 |
| Ahorro planificado | −$500 |
| Aportes a metas | −$300 |
| **Safe to Spend** | **$1,000** |

- Un clic sobre el valor muestra este desglose. El ahorro planificado lo define el usuario como monto por periodo, en Ajustes o desde este desglose; vale 0 hasta que lo defina.
- Se presenta como estimación basada en los datos del usuario, nunca como recomendación financiera.
- Se calcula por moneda, solo con las cuentas, recurrentes y metas de esa moneda. El ahorro planificado está en la moneda principal y solo se resta ahí.
- Se recalcula con cada transacción, cuenta, gasto recurrente, meta o presupuesto nuevo.
- **Propuesta:** los presupuestos no restan de Safe to Spend; son límites por categoría dentro de lo que se puede gastar. Su avance se ve en Spending Pace (6.17). Así la fórmula queda igual y el número no cambia al crear un presupuesto.
- Este cálculo es el **motor financiero** de la V1: Can I Afford It?, What If?, Financial Forecast y Goal Forecast lo reusan.

**Criterios de aceptación:**

- [ ] Con un saldo de $2,500, pagos recurrentes pendientes de $700, ahorro planificado de $500 y aportes a metas de $300, Safe to Spend muestra $1,000, y un clic muestra ese desglose.
- [ ] Registrar un gasto cambia Safe to Spend en el momento.

### 6.11 Money Flow (FTR-013)

- Muestra el recorrido del dinero: Ingresos → Necesidades, Estilo de vida y Metas → Disponible.
- Cada nodo muestra su monto; Necesidades y Estilo de vida se abren en sus categorías.
- Se actualiza con cada registro y cumple el rol del reporte "¿Dónde se fue mi dinero?".
- El tipo de visual (por ejemplo, un diagrama Sankey) se define en los mockups, como pide el PRD §9.4.

**Criterios de aceptación:**

- [ ] Necesidades, Estilo de vida, Metas y Disponible suman los ingresos del mes.
- [ ] Abrir Necesidades o Estilo de vida muestra sus categorías con sus montos.

### 6.12 Metas y Goal Forecast (FTR-018, FTR-019)

- Cada meta tiene nombre, monto objetivo, monto actual, fecha objetivo y prioridad.
- El usuario registra aportes a cada meta.
- Cada meta muestra su avance, por ejemplo: Fondo de emergencia $2,500 / $5,000 (50%).
- Goal Forecast estima la fecha de logro: `meses restantes = (monto objetivo − monto actual) ÷ aporte mensual promedio`.
- Mensaje de ejemplo: *Al ritmo actual, alcanzarás tu Fondo de emergencia en marzo de 2027.*
- La proyección reusa el motor financiero.

**Criterios de aceptación:**

- [ ] Una meta de $5,000 con $2,500 ahorrados muestra 50% de avance.
- [ ] Con un aporte promedio de $500 al mes, Goal Forecast estima 5 meses para esa meta.

### 6.13 Can I Afford It? (FTR-010)

- El usuario escribe el monto de una compra posible, opcionalmente su categoría, y pulsa Analizar.
- La app calcula el impacto en Safe to Spend, pagos próximos, ahorro, metas y, si indicó categoría, en el presupuesto de esa categoría.
- Usa reglas financieras simples, sin IA.
- Muestra el impacto y los supuestos usados; no decide por el usuario.

**Reglas propuestas:**

1. El dinero disponible para la compra es el Safe to Spend más los ingresos recurrentes que todavía faltan llegar en el periodo, menos el gasto variable que falta gastar. Si el monto es menor o igual: "Te alcanza" y lo que queda después de todo (ej. $1,000 → $200).
2. Si lo supera: "Todavía no te alcanza", cuánto falta y, como información, de dónde saldría si se usaran los aportes a metas y cuántos meses se atrasaría cada una. Las metas no son una forma de pagar.
3. El tiempo para juntarlo sale del sobrante mensual real: ingresos recurrentes menos gastos recurrentes, gasto variable promedio, aportes a metas y ahorro planificado. Si el sobrante es positivo, se muestra el mes estimado; si es cero o negativo, se explica que con los ingresos y gastos actuales no se junta.
4. Si la categoría tiene presupuesto: se muestra cuánto quedaría de él, o cuánto se pasaría (V1.1).

**Criterios de aceptación:**

- [ ] Con Safe to Spend de $1,000 y sin ingresos pendientes ni gasto variable, una compra de $800 responde "Te alcanza" y muestra que quedan $200.
- [ ] Un sueldo que falta llegar en el periodo suma al disponible y puede convertir un "todavía no" en "te alcanza".
- [ ] Sin metas, una compra mayor al disponible muestra el mes en que se junta al ritmo del sobrante mensual.
- [ ] El impacto en metas se muestra como información, nunca como la forma de pagar.
- [ ] El resultado muestra los supuestos usados (periodo, ingresos, gastos, metas, ahorro y sobrante) y no decide por el usuario.

### 6.14 Monthly Money Story (FTR-022)

- Al cerrar cada mes, la app avisa con una notificación y muestra cuánto ganó, gastó y ahorró el usuario, y su tasa de ahorro.
- Luego compara con el mes anterior: ingresos, mayor categoría de gasto, ahorro, avance de metas y presupuestos cumplidos.
- **Propuesta:** textos generados con plantillas y reglas, sin IA.
- El primer mes solo muestra totales, porque no hay mes anterior para comparar.
- El tono nunca juzga al usuario: *Here's something you may want to look at*, no *You're wasting money*.

**Criterios de aceptación:**

- [ ] Al cerrar el mes llega una notificación, y la historia muestra cuánto ganó, gastó y ahorró el usuario.
- [ ] El primer mes muestra solo totales; desde el segundo compara con el mes anterior.

### 6.15 Notificaciones (FTR-023)

- Notificaciones push en iOS y Android; el usuario elige en Ajustes qué avisos recibe.
- Avisos de la V1:
  - Tu Money Story de septiembre está lista.
  - Tu resumen de la semana está listo (FTR-021).
  - Mañana se espera tu pago de alquiler de $700.
  - Te faltan $200 para el próximo hito de tu Fondo de emergencia.
  - Usaste el 80% de tu presupuesto de Comida (FTR-014).
  - Superaste tu presupuesto de Comida.
- **Propuesta:** cada alerta de presupuesto se envía una sola vez por umbral y por mes.

**Criterios de aceptación:**

- [ ] Desactivar un tipo de aviso en Ajustes detiene ese aviso en todos los dispositivos del usuario.
- [ ] Al pasar el 80% de un presupuesto llega un solo aviso, aunque se registren más gastos en esa categoría.

### 6.16 Presupuestos por categoría (FTR-014)

- El usuario define un presupuesto mensual por categoría de gasto y moneda (por defecto, la principal).
- Cada presupuesto muestra gastado, restante y porcentaje usado, por ejemplo: Comida $240 / $400 (60%).
- Solo cuentan los gastos en la moneda del presupuesto; no hay conversión.
- **Propuesta:** el presupuesto se repite cada mes hasta que el usuario lo cambie o lo borre; lo no gastado no se acumula al mes siguiente.
- Umbrales de aviso: 80% y 100% (FTR-023).
- El número de presupuestos depende del plan (6.2).
- La tabla ya está escrita en `future/110_budgets.sql` y pasa a las migraciones de la V1.

**Criterios de aceptación:**

- [ ] Con un presupuesto de $400 en Comida y $240 gastados, la app muestra $160 restantes y 60% usado.
- [ ] Un gasto de 10 USD en Comida no suma al presupuesto de Comida en Bs.
- [ ] Al empezar un mes nuevo, el presupuesto vuelve a $0 gastado con el mismo monto.

### 6.17 Spending Pace (FTR-015)

Spending Pace compara lo gastado en cada presupuesto con lo que va del mes.

```
Ritmo = (gastado ÷ presupuesto) − (días transcurridos ÷ días del mes)
Proyección al cierre = gastado ÷ días transcurridos × días del mes
```

- Tres estados: **En ritmo** (ritmo ≤ 0), **Un poco rápido** (hasta 10 puntos por encima) y **Muy rápido** (más de 10 puntos).
- Mensaje de ejemplo: *Llevas el 60% de Comida y va el 40% del mes. A este ritmo cerrarías en $600.*
- **Propuesta:** los primeros 3 días del mes no se muestra estado, porque la proyección aún no es útil.
- El tono nunca juzga: describe el ritmo y deja la decisión al usuario.

**Criterios de aceptación:**

- [ ] El día 12 de un mes de 30 días, con $240 gastados de $400, Spending Pace muestra "Muy rápido" (60% contra 40%) y una proyección al cierre de $600.

### 6.18 Financial Forecast a 30, 60 y 90 días (FTR-020)

Proyecta el saldo del usuario en cada moneda a 30, 60 y 90 días con el motor financiero.

```
Saldo proyectado = Saldo actual + Ingresos recurrentes esperados − Gastos recurrentes esperados − Aportes a metas − Gasto variable promedio
```

- El gasto variable promedio sale de los gastos no recurrentes de los últimos 3 meses (o de los meses que existan).
- Muestra un gráfico simple y el detalle de los supuestos.
- Si el saldo proyectado baja de 0, la app indica en qué fecha aproximada ocurriría.
- Se presenta como estimación, nunca como recomendación.

**Criterios de aceptación:**

- [ ] Con saldo $2,500, ingreso recurrente de $3,000 al mes, gastos recurrentes de $700, aportes de $300 y gasto variable promedio de $1,500, el Forecast a 30 días muestra $3,000.
- [ ] Un usuario con menos de un mes de datos ve el Forecast con el aviso de que la estimación mejora con más historial.

### 6.19 What If? (FTR-011)

El usuario simula un cambio antes de hacerlo y ve su efecto, sin modificar sus datos.

- Escenarios de la V1:
  1. Mi ingreso mensual sube o baja X.
  2. Agrego o quito un gasto recurrente de X.
  3. Cambio el aporte mensual a una meta.
  4. Cambio mi ahorro planificado.
- Para cada escenario muestra antes y después de: Safe to Spend, Forecast a 30, 60 y 90 días y fecha estimada de cada meta.
- Se pueden combinar hasta 2 cambios en una simulación.
- Usa el mismo motor financiero, sin IA.
- **Propuesta:** las simulaciones no se guardan en la V1; se calculan en el momento.
- Vive en la sección Scenarios, junto a Can I Afford It?.

**Criterios de aceptación:**

- [ ] Simular un gasto recurrente nuevo de $200 baja Safe to Spend en $200 y muestra cuántos meses se retrasa cada meta afectada.
- [ ] Ninguna simulación cambia los datos reales del usuario.
- [ ] El resultado muestra los supuestos usados y no decide por el usuario.

### 6.20 Weekly Money Check-in (FTR-021)

- Cada lunes, la app avisa (FTR-023) y muestra el resumen de la semana anterior: cuánto gastó, la mayor categoría, comparación con la semana previa, presupuestos que van "Muy rápido" y avance de metas.
- Reusa las plantillas y reglas de Monthly Money Story, con periodo semanal; sin IA.
- La primera semana solo muestra totales.
- El tono nunca juzga al usuario.

**Criterios de aceptación:**

- [ ] Cada lunes llega una notificación y el resumen muestra lo gastado la semana anterior.
- [ ] Un presupuesto en estado "Muy rápido" aparece en el resumen.

### 6.21 Escaneo de facturas con IA (FTR-030)

El usuario toma una foto de una factura o recibo y la app la convierte en un movimiento listo para confirmar.

- Desde el botón **+**, el usuario toma una foto o elige una de la galería.
- Un modelo que lee imágenes extrae monto total, moneda, descripción (el nombre del comercio), fecha y una categoría sugerida (de las del usuario). La cuenta toma los valores por defecto de Quick Add; si la moneda de la factura no es la de esa cuenta, la app propone una cuenta en esa moneda.
- Reusa la capa de IA de FTR-007: mismo formato de salida, mismas reglas de confirmación y la misma tabla de principal y respaldos, con un tipo nuevo de paso (lectura de imagen).
- Proveedor provisional: Claude Haiku 5.5 como principal y GPT-6 Luna como respaldo, si acepta imágenes; se confirma en la prueba de concepto con unas 30 facturas bolivianas reales.
- Si no se puede leer el total, la app lo pide en lugar de adivinarlo. Si fallan todos los proveedores, abre Quick Add y el escaneo no descuenta la cuota.
- Privacidad: al proveedor solo va la imagen y los nombres de las categorías del usuario. **Propuesta:** la foto no se guarda salvo que el usuario quiera adjuntarla al movimiento.
- Cada plan tiene una cuota de escaneos al mes (10 en el gratuito, provisional).

**Criterios de aceptación:**

- [ ] La foto de una factura legible produce un movimiento con monto, descripción y fecha correctos, listo para confirmar.
- [ ] Una factura ilegible no crea un movimiento con datos inventados: la app pide los datos que faltan.

## 7. Requerimientos no funcionales

Lo que la V1 debe cumplir en todas sus funciones. La última columna dice dónde se detalla cada punto.

| Requisito | Cómo se cumple | Detalle |
|---|---|---|
| Datos personales | Cada dato financiero pertenece a un usuario y solo él lo ve. La base de datos lo impone con Row-Level Security aunque la API tenga un error. No hay cuentas compartidas | Pestaña Base de datos |
| Seguridad de acceso | Tokens de acceso cortos con refresh rotativo, biometría del sistema operativo (la app no guarda datos biométricos), secretos en Secret Manager y cifrado en tránsito y en reposo | 6.1 y 10.2 |
| Solo mayores de 18 | La fecha de nacimiento se valida al registrarse, con cualquier método | 6.1 |
| Dinero exacto | Montos decimales exactos, saldos que mantiene la base de datos y conciliación nocturna | Pestaña Base de datos |
| Velocidad | Quick Add en menos de 10 segundos; escaneo de factura en menos de 15; las consultas medidas en la base de datos respondieron en menos de 10 ms con 300.000 transacciones | 3 y pestaña Base de datos |
| Continuidad de la IA | Voz y escaneo tienen principal y respaldo; si fallan, el usuario lo escribe en Quick Add | 6.7 y 6.21 |
| Privacidad de voz e imágenes | El audio y las fotos no se guardan salvo que el usuario lo acepte; a la IA no van saldos ni historial | 6.7 y 6.21 |
| Trazabilidad | Logs de solo inserción, incidentes con severidad de sev1 a sev4 y su línea de tiempo, y auditoría de cambios | Pestaña Base de datos |
| Escala | API sin estado en Cloud Run con autoescalado, workers aparte y transacciones particionadas por usuario | 10.2 |
| Plataformas | iOS y Android con Flutter, y web responsive, con la misma cuenta | 6.1 y 10.1 |
| Estimaciones, no consejos | Safe to Spend, Can I Afford It?, What If?, Financial Forecast y Spending Pace se presentan como estimaciones con sus supuestos, nunca como recomendación financiera | 6.10, 6.13, 6.17, 6.18 y 6.19 |

## 8. Modelo de datos

La V1 necesita 24 entidades. Insights y Scenarios del PRD original no se crean: Financial Insights quedó fuera, y What If? y Can I Afford It? calculan en el momento.

El diseño completo, con 48 tablas en 11 módulos, está en la pestaña **Base de datos**. Para esta versión hay que mover `future/110_budgets.sql` a las migraciones de la V1, agregar la tabla de escaneos y el periodo en MoneyStory.

Cada tabla y cada campo, con su tipo, si es obligatorio, qué guarda y a qué tabla apunta, están en **Diccionario de campos**.

| Entidad | Campos clave | La usan |
|---|---|---|
| User | id, nombre, apellido, cómo llamarlo, email, fecha de nacimiento, teléfono, país, ciudad, ocupación, foto, versión de términos aceptada, método de login, moneda principal, periodo financiero (tipo y día de inicio), ahorro planificado por periodo, plan | FTR-001, FTR-025, FTR-024 |
| UserPreferences | user_id, tema, color de acento, modo privado, día de inicio de semana | FTR-024 |
| TermsVersion | versión, URL de términos y de privacidad, vigente | FTR-001 |
| Plan | id, nombre, nivel, precio mensual y anual, límites por funcionalidad (tarjetas, metas, presupuestos, dictados, escaneos y consultas); un gratuito y 3 de pago | Planes SaaS |
| Subscription | id, user_id, plan, precio, mensual o anual, estado (prueba, activa, en gracia, vencida y otros), renovación automática, fin del periodo pagado, tienda | Planes SaaS |
| Currency | código (USD, EUR, BOB), símbolo, decimales, activa (si la app la ofrece) y orden en el selector | FTR-003, FTR-024 |
| UserCurrency | user_id, moneda, orden: Mis monedas; siempre incluye la moneda principal y las de sus cuentas | FTR-003, FTR-024 |
| AccountType | código (efectivo o tarjeta), nombre, ícono, si es tarjeta (de aquí sale "pagó con tarjeta") | FTR-003, FTR-004 |
| Account | id, user_id, nombre, tipo (efectivo o tarjeta), moneda, saldo inicial y actual, cuenta por defecto | FTR-003 |
| Card | cuenta, banco emisor (del catálogo) y últimos 4 dígitos | FTR-003 |
| Country | código ISO, nombre, moneda local | FTR-001, FTR-003 |
| FinancialInstitution | código, país, nombre, nombre corto, tipo (banco, cooperativa, microfinanciera o billetera) | FTR-003 |
| Category | id, user_id, nombre, tipo (ingreso o gasto), grupo del Money Flow (solo en gastos), ícono, color; copia editable de las categorías iniciales, sin subcategorías | FTR-005, FTR-031, FTR-013 |
| Transaction | id, user_id, account_id, category_id, tipo, monto, moneda (la de la cuenta), fecha, descripción, notas, recurrente, origen (manual, voz, escaneo o recurrente); en transferencias, cuenta destino de la misma moneda | FTR-004, FTR-006, FTR-007, FTR-030 |
| RecurringTransaction | id, user_id, account_id, category_id, monto, moneda, descripción, frecuencia, próxima fecha | FTR-002, FTR-009, FTR-020 |
| Budget | id, user_id, category_id, moneda, monto mensual, activo, umbrales avisados en el mes | FTR-014, FTR-015, FTR-023 |
| Goal | id, user_id, nombre, moneda, monto objetivo, monto actual, fecha objetivo, prioridad, aporte planeado por periodo (sin cuenta vinculada) | FTR-018, FTR-019 |
| GoalContribution | id, goal_id, monto, fecha | FTR-019, FTR-010, FTR-011 |
| MoneyStory | id, user_id, periodo (mes o semana), fecha de inicio, totales, textos generados | FTR-022, FTR-021 |
| Device | id, user_id, token push, plataforma (iOS, Android, web) | FTR-023 |
| NotificationSetting | user_id, tipo de aviso, activo | FTR-023 |
| VoiceEntry | id, user_id, transcripción, movimiento extraído, modelos que respondieron, intentos, si usó un respaldo, costo, transacción creada | FTR-007 |
| ReceiptScan | id, user_id, imagen (solo si el usuario la adjunta), movimiento extraído, modelos que respondieron, intentos, si usó un respaldo, costo, transacción creada | FTR-030 |
| AIModel y AIRoute | proveedor, modelo, tipo (voz a texto, LLM o lectura de imagen), precios; por cada paso, el orden de principal y respaldos con su tiempo límite | FTR-007, FTR-030 |

**Propuesta:** Can I Afford It? y What If? calculan en el momento y no guardan escenarios en la V1. Como el diseño ya existe, su actualización se estima en 3 horas.

## 9. Navegación y experiencia principal

La navegación de la V1 sigue la del PRD, sin la pestaña Insights, porque Financial Insights (FTR-017) quedó en rojo.

> 🖼️ *[Diagrama: navegación móvil de la V1 · 5 pestañas — imagen no incluida en el texto original]*

En web, las mismas secciones van en un menú lateral: Map, Transactions, Goals y Scenarios, con Accounts y Settings debajo. En la V1:

- **Map** incluye Safe to Spend, las tarjetas de Presupuestos con Spending Pace y el Forecast; el detalle de presupuestos se abre desde ahí.
- **Scenarios** contiene Can I Afford It? y What If?.
- Weekly Check-in y Money Story se abren desde su notificación y desde el Map.
- Registro, login, onboarding y planes quedan fuera de las pestañas.

## 10. Stack técnico y arquitectura

La V1 se construye con Flutter en la app y Python con FastAPI en el backend, como un monolito modular sin estado que escala en contenedores. El equipo ya domina Dart y Python, así que el stack no suma curva de aprendizaje al plazo de 15 días.

> 🖼️ *[Diagrama: arquitectura de la V1 · Google Cloud — imagen no incluida en el texto original]*

La app solo habla con la API; la API encola en Redis lo que tarda, y los workers llaman a la IA y escriben en PostgreSQL.

### 10.1 Stack por capa

| Capa | Tecnología | Por qué |
|---|---|---|
| App iOS, Android y web | Flutter (Dart), con flavors dev, staging y prod | Un solo código para las tres plataformas |
| Arquitectura de la app | Riverpod, go_router, dio, freezed | Estado predecible, navegación declarativa y renovación automática del JWT |
| Cliente de la API | Cliente Dart generado desde el OpenAPI de FastAPI | La app y el backend no se desincronizan |
| Gráficos y Money Flow | fl_chart y CustomPainter | El mapa del dinero (FTR-013), el Forecast (FTR-020) y los presupuestos (FTR-014) |
| Sesión y biometría | flutter_secure_storage + local_auth | JWT cifrado en el dispositivo; huella y rostro (FTR-025) |
| Login social | google_sign_in y flutter_facebook_auth, con el token verificado en el backend | Google y Meta (FTR-025) |
| Grabación de voz | record | Registro por voz (FTR-007) |
| Cámara y galería | image_picker | Escaneo de facturas (FTR-030) |
| API | Python + FastAPI asíncrono + Pydantic | Rápida, tipada y con OpenAPI automático |
| Base de datos | PostgreSQL + SQLAlchemy 2 (asíncrono) + Alembic | Datos financieros relacionales y migraciones versionadas |
| Dinero | NUMERIC en PostgreSQL, Decimal en Python, monedas ISO 4217 | Sin errores de redondeo |
| Motor financiero | Módulo propio en Python, sin IA | Un solo cálculo para Safe to Spend, Can I Afford It?, What If?, Forecast y Goal Forecast |
| Cola y caché | Redis + Celery, con Celery Beat para tareas periódicas | Voz, escaneo, Money Story semanal y mensual y alertas de presupuesto fuera de la petición |
| IA | Modelos propios en `docker-compose.ai.yml`: voz a texto en el servicio `stt` (Parakeet y Whisper) y LLM en Ollama (Qwen 3.5 4B y Gemma 3 4B). El principal y el respaldo de cada paso se guardan en la base de datos | Si un proveedor falla responde otro, y cambiar el principal no exige desplegar |
| Archivos | Cloud Storage con URLs firmadas | Fotos de perfil y facturas adjuntas no pasan por la API |
| Nube | Google Cloud: Cloud Run, Cloud SQL, Memorystore y Secret Manager | Contenedores con autoescalado, sin administrar servidores |
| Infraestructura | Docker + Terraform | Entornos dev, staging y prod idénticos y portables a otra nube |
| CI/CD | GitHub Actions para el backend; Codemagic para los builds de iOS y Android | Despliegues automáticos; builds de iOS sin Mac propia |
| Calidad | pytest, flutter_test, integration_test y Maestro | Pruebas unitarias, de integración y de punta a punta |
| Observabilidad | Sentry, Cloud Logging y PostHog | Errores, logs y medición de la North Star |
| Notificaciones push | Firebase Cloud Messaging + firebase_messaging | Un solo servicio para Android e iOS (FTR-023) |

### 10.2 Escalabilidad y SaaS

Estas decisiones dejan crecer la app en usuarios, planes y funcionalidades sin reescribir la V1.

- **Monolito modular.** Un solo backend con módulos separados: acceso, cuentas, transacciones, presupuestos, metas, motor financiero, IA y reportes. Un módulo pasa a servicio propio solo cuando su carga lo justifique.
- **API sin estado.** La sesión vive en el JWT y la caché en Redis. Así Cloud Run suma o quita instancias según el tráfico.
- **Trabajo pesado en workers.** Transcripción, LLM, lectura de facturas, Money Story y Weekly Check-in corren en Celery, fuera de la petición. Los workers escalan aparte de la API.
- **Aislamiento por usuario.** Toda tabla lleva user_id y PostgreSQL aplica Row-Level Security como segunda barrera.
- **Planes como datos.** Los límites de cada plan viven en una tabla de permisos que un middleware aplica.
- **Costo de IA por plan.** Cada plan tiene cuotas de dictados y escaneos, y se mide el consumo de tokens por usuario.
- **IA con respaldo.** Cada paso de la IA tiene principal y respaldo con tiempo límite, reintentos y un circuito que deja de llamar unos minutos al proveedor que falla seguido. Cada llamada queda registrada con su costo.
- **Base de datos lista para crecer.** Índices por usuario y fecha, pool de conexiones y réplicas de lectura cuando hagan falta. La tabla de transacciones ya está dividida en 16 particiones por usuario.
- **API versionada.** Rutas `/api/v1`, para que las versiones viejas de la app sigan funcionando mientras los usuarios actualizan.
- **Seguridad.** Tokens de acceso cortos con refresh rotativo, secretos en Secret Manager, llaves de IA solo en el backend y cifrado en tránsito y en reposo.
- **Cobro en las tiendas.** Si el plan de pago se vende dentro de la app, Apple y Google suelen exigir su sistema de compras. Antes de activar cobros conviene revisar sus reglas vigentes y evaluar RevenueCat.

## 11. Fuera del alcance de la V1

Quedan fuera 8 funcionalidades: 1 en amarillo y 7 en rojo. Tampoco entran los P2 del PRD (integración bancaria, importación automática, asistente IA, inversiones, deudas, cuentas familiares).

| ID | Funcionalidad | Consenso | Efecto en la V1 |
|---|---|---|---|
| FTR-008 | Temas y fondos estilo WhatsApp | Amarillo | Un solo tema visual |
| FTR-017 | Financial Insights accionables | Rojo | Era P0 en el PRD; Insights sale de la navegación |
| FTR-016 | Financial Leaks | Rojo | Sin detección de gastos hormiga ni suscripciones |
| Sin ID | Sugerencias de cambios de hábitos | Rojo | La app informa y no sugiere recortes |
| FTR-026 | Interfaz adaptativa según edad | Rojo | No aplica: los usuarios son mayores de 18 años |
| FTR-027 | Temas y colores personalizables | Rojo | Un solo tema visual |
| FTR-028 | Mascota virtual | Rojo | Era P0 Estrella / UX en la matriz |
| FTR-029 | Bonos y recompensas al ahorro | Rojo | Requiere decisiones administrativas y de negociación |

Pasan a la V1.1, además: el aprendizaje automático de categorías, guardar escenarios de What If? y el equivalente informativo en la moneda principal ("980 USD ≈ 6.820 Bs"), que necesita un proveedor de tipo de cambio y no cambia saldos ni reportes.

## 12. Plan y estimaciones

El plan total es de **15 días hábiles (120 horas)**, con QA incluido. Las estimaciones bajaron de 49 días y 4 horas (sin QA) a 15 días con QA por tres razones: el diseño de base de datos ya está hecho, las 6 funcionalidades nuevas reusan el motor financiero, la capa de IA y las plantillas de reportes, y la IA sale con un respaldo por paso en lugar de dos.

| Bloque | Esfuerzo estimado |
|---|---|
| Actualización del diseño de base de datos | 3 horas |
| Mockups | 6 horas |
| Mapa de navegación | 1 hora |
| Funcionalidades de la versión 1.3 (verde, FTR-031 y FTR-023) | 7 días y 4 horas |
| Funcionalidades ampliadas (FTR-014, FTR-015, FTR-020, FTR-030, FTR-011, FTR-021) | 3 días y 2 horas |
| QA de toda la V1 | 3 días |
| **Total** | **15 días** |

Cronograma con dependencias (una persona a tiempo completo, 8 horas por día):

| Días | Bloque | Funcionalidades | Horas |
|---|---|---|---|
| 1–2 | 1. Preparación | Base de datos, mapa de navegación y mockups | 10 |
| 2–3 | 2. Acceso, planes y ajustes | FTR-001, FTR-025, Planes SaaS, FTR-024 | 11 |
| 3–5 | 3. Cuentas, categorías y transacciones | FTR-003, FTR-004, FTR-005, FTR-031, FTR-006 | 14 |
| 5–6 | 4. Onboarding y Map | FTR-002, FTR-012, FTR-013 | 8 |
| 6–7 | 5. Motor financiero y metas | FTR-009, FTR-018, FTR-019, FTR-010 | 13 |
| 8–10 | 6. Presupuestos y proyecciones | FTR-014, FTR-015, FTR-020, FTR-011 | 18 |
| 10–11 | 7. Registro con IA | FTR-007, FTR-030 | 14 |
| 12 | 8. Reportes y avisos | FTR-022, FTR-021, FTR-023 | 8 |
| 13–15 | 9. QA | Pruebas de punta a punta, corrección de errores y builds de tiendas | 24 |
| | **Total** | | **120** |

Con dos personas en paralelo, el bloque 7 (IA) puede empezar el día 3, después de las transacciones, y libera unos 2 días de margen para QA o imprevistos. Es la configuración recomendada.

## 13. Riesgos y decisiones abiertas

Quedan 5 decisiones abiertas; la más urgente sigue siendo definir los 3 planes de pago, porque afecta el modelo de datos y el cobro en las tiendas.

- [ ] **Planes de pago.** Hay un plan gratuito y tres de pago: faltan sus nombres, límites y precios, y cómo se cobra en App Store y Play Store. Decidido: el gratuito permite 1 tarjeta y 1 moneda y los de pago varias; falta fijar cuántas tarjetas, monedas, presupuestos y escaneos da cada plan de pago.
- [x] **Tipo de cambio.** Resuelto: la V1 no convierte monedas. Cada cuenta tiene una moneda y los totales se muestran por moneda. Ver el equivalente en la moneda principal queda para la V1.1.
- [ ] **Registro con IA.** Elegir con la prueba de concepto el principal de cada paso (voz a texto, LLM y lectura de facturas) y si siempre se confirma antes de guardar.
- [ ] **Presupuestos y Safe to Spend.** Confirmar que los presupuestos no restan de Safe to Spend (6.10) y que lo no gastado no pasa al mes siguiente (6.16).
- [ ] **Umbrales de Spending Pace.** Validar los cortes de 0 y 10 puntos y los 3 días iniciales sin estado.
- [ ] **Metas de éxito.** Falta el número objetivo de la North Star.
- [x] **Estimaciones faltantes.** Resuelto: FTR-031, FTR-023 y QA ya tienen estimación (sección 12).
- [x] **Alcance ampliado.** Resuelto: entran FTR-014, FTR-015, FTR-020, FTR-030, FTR-011 y FTR-021, con plazo de 15 días.
- [x] **Edad de los usuarios.** Resuelto: solo mayores de 18 años, validado con la fecha de nacimiento al registrarse.
- [x] **Plataforma móvil.** Resuelto: app para iOS y Android con Flutter, publicada en ambas tiendas, más la web responsive.
- [x] **Ahorro planificado y periodos.** Resuelto: el usuario elige su periodo (semanal, quincenal o mensual, desde el día que quiera) y define el ahorro planificado por periodo.
- [x] **Notificaciones.** Resuelto: entran a la V1 como notificaciones push (FTR-023), con alertas de presupuesto.
- [x] **Onboarding.** Resuelto: solo en el primer inicio, con los pasos esenciales.
- [x] **Cuentas compartidas.** Resuelto: no hay. Las cuentas y todos los datos financieros son personales.
- [x] **Moneda y método de pago.** Resuelto: cada movimiento se registra en la moneda de su cuenta; efectivo o tarjeta sale del tipo de la cuenta (sin QR). Cada cuenta tiene una sola moneda; el usuario tiene una moneda principal, una sola cuenta por defecto y arma Mis monedas.

**Riesgos:**

- **Plazo sin margen:** el plan pasa de más de 49 días de esfuerzo a 15 días con 6 funcionalidades más. Con una persona, el esfuerzo iguala el plazo y cualquier retraso mueve la entrega. Mitigación: dos personas en paralelo (sección 12) y, si hace falta recortar, sacar primero FTR-021 y FTR-030, que no bloquean a otras funcionalidades.
- **Estimaciones comprimidas:** dependen de reusar el motor financiero y la capa de IA. Si el motor de Safe to Spend se retrasa, arrastra a FTR-010, FTR-011, FTR-019 y FTR-020.
- **IA:** voz y escaneo dependen de proveedores externos. La prueba de concepto se redujo (50 frases y 30 facturas) y salen con un solo respaldo por paso; la precisión con montos, monedas y comercios bolivianos debe medirse antes del día 10.
- **Biometría y login social en Flutter:** dependen de plugins nativos; conviene probarlos el día 2.
- **Publicación en tiendas:** la revisión de App Store y Google Play puede tardar días y no entra en los 15; conviene enviar un build de prueba durante el QA.
- **Confianza:** Safe to Spend, Can I Afford It?, What If? y Forecast deben leerse como estimaciones, no como asesoría financiera.

## 14. Historial de cambios

| Versión | Fecha | Cambios |
|---|---|---|
| 1.0 | 12-10-2026 | Primera versión: alcance en verde de la matriz, requerimientos, stack técnico, plan y riesgos |
| 1.1 | 13-10-2026 | Desde la 1.0: decisiones del equipo (solo mayores de 18, notificaciones, onboarding y ahorro planificado); base de datos con suscripciones mensual y anual, logs e incidentes; datos personales sin cuentas compartidas; moneda y método de pago en cada movimiento; registro por voz con LLM y proveedores de respaldo; requerimientos no funcionales, criterios de aceptación por módulo, secciones numeradas e índice |
| 1.2 | 13-10-2026 | Diccionario de campos: las 45 tablas con cada campo, su tipo y sus relaciones, las 11 vistas y las tablas futuras, con el detalle de presupuestos (FTR-014 y FTR-015) |
| 1.3 | 13-10-2026 | Solo efectivo y tarjeta (débito o crédito), sin QR; el plan define cuántas tarjetas tiene el usuario (gratuito: solo efectivo); monedas configurables, con catálogo que el equipo activa o desactiva y Mis monedas por usuario; base de datos con 46 tablas y 67 pruebas |
| 1.4 | 13-10-2026 | Alcance ampliado con Presupuestos (FTR-014), Spending Pace (FTR-015), Financial Forecast (FTR-020), Escaneo de facturas con IA (FTR-030), What If? (FTR-011) y Weekly Money Check-in (FTR-021), con requerimientos y criterios de aceptación (6.16 a 6.21); alertas de presupuesto en notificaciones; entidades Budget y ReceiptScan; estimaciones reducidas y plan de 15 días hábiles con QA incluido |
| 1.5 | 14-10-2026 | Sin tipos de cambio: cada cuenta tiene una moneda, los movimientos y transferencias quedan en ella y los totales, Safe to Spend, Forecast y presupuestos van por moneda; moneda base pasa a llamarse moneda principal; una sola cuenta por defecto; datos de tarjeta en su propia tabla; efectivo o tarjeta sale del tipo de cuenta; gratuito con 1 tarjeta y 1 moneda; periodo financiero semanal, quincenal o mensual con ahorro por periodo; solo categorías, sin subcategorías; metas sin cuenta vinculada; uso de IA por usuario; tarjeta única sin débito/crédito ni cupo; catálogo de países e instituciones financieras; transacciones sin comercio, hora, notas ni estado; grupo del Money Flow como lista fija; perfil con apellido, teléfono, país, ciudad, ocupación y términos aceptados; personalización en el servidor (tema, color, modo privado, inicio de semana); equivalente en la moneda principal pasa a la V1.1; base de datos con 47 tablas |
| 1.5.1 | 23-10-2026 | Voz a texto en servidor propio, sin API paga: Parakeet TDT 0.6B v3 de principal y Whisper large-v3-turbo de respaldo, en un servicio `stt` con CPU dentro del mismo compose. El audio ya no sale del servidor. El LLM sigue con GPT-6 Luna y Claude Haiku 5.5. Se descartan GPT-Transcribe, Groq y Deepgram |
| 1.5.2 | 23-10-2026 | El LLM también es propio: Qwen3 4B Instruct 2507 de principal y Gemma 3 4B de respaldo, en Ollama. La IA va en `docker-compose.ai.yml`, aparte de la API. Sin APIs pagas: el dictado no tiene costo por uso y ningún dato sale del servidor |
| 1.5.3 | 24-10-2026 | Qwen 3.5 4B reemplaza a Qwen3 4B Instruct de principal, sin modo de pensar; Gemma 3 4B sigue de respaldo |
