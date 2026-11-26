-- =============================================================================
-- MoneyMap · 990 · comentarios de tablas y columnas
-- La descripción de cada tabla (para qué sirve, quién la escribe y un ejemplo)
-- y de cada columna. DBeaver las muestra, y DICCIONARIO_CAMPOS.md se genera
-- desde aquí con tools/dictionary.sql y tools/build_dictionary.py.
-- Al agregar una columna, agrega también su comentario en este archivo.
-- =============================================================================

-- ai.calls
COMMENT ON TABLE ai.calls IS
  'Cada llamada a un proveedor de IA, exitosa o no: estado, latencia, tokens o audio y costo. El detalle de un error va a ops.logs. Particionada por mes. Quién escribe: el worker (solo inserta). Ejemplo: DeepSeek extrajo en 1.400 ms con 800/100 tokens, 0,00036 USD.';
COMMENT ON COLUMN ai.calls.id IS 'Identificador; la clave primaria es (created_at, id)';
COMMENT ON COLUMN ai.calls.created_at IS 'Cuándo se hizo la llamada; define la partición mensual';
COMMENT ON COLUMN ai.calls.task IS 'Paso: voice.transcribe o voice.extract';
COMMENT ON COLUMN ai.calls.model_code IS 'Modelo llamado';
COMMENT ON COLUMN ai.calls.route_position IS 'Posición del modelo en la ruta: 1 = principal; 2 o más = respaldo';
COMMENT ON COLUMN ai.calls.attempt IS 'Número de intento con ese modelo (2 = primer reintento). Por defecto 1';
COMMENT ON COLUMN ai.calls.status IS 'ok, error, timeout, rate_limited, invalid_output o circuit_open (saltada porque el proveedor venía fallando). El mensaje del error va a ops.logs';
COMMENT ON COLUMN ai.calls.user_id IS 'Usuario del dictado (sin FK)';
COMMENT ON COLUMN ai.calls.voice_entry_id IS 'Dictado al que pertenece (sin FK)';
COMMENT ON COLUMN ai.calls.voice_entry_created_at IS 'Fecha del dictado, para encontrarlo en su partición; va junto con voice_entry_id';
COMMENT ON COLUMN ai.calls.latency_ms IS 'Cuánto tardó';
COMMENT ON COLUMN ai.calls.audio_seconds IS 'Segundos de audio enviados (voz a texto)';
COMMENT ON COLUMN ai.calls.input_tokens IS 'Tokens de entrada (LLM)';
COMMENT ON COLUMN ai.calls.cached_input_tokens IS 'De esos, cuántos venían de caché (más baratos)';
COMMENT ON COLUMN ai.calls.output_tokens IS 'Tokens de salida (LLM)';
COMMENT ON COLUMN ai.calls.cost_usd IS 'Costo en dólares. Si no se envía, lo calcula un trigger con el precio de ai.models; las llamadas que no llegaron al proveedor cuestan 0';

-- ai.models
COMMENT ON TABLE ai.models IS
  'Modelos de IA disponibles con su precio. Agregar un proveedor es un INSERT aquí y una ruta. Quién escribe: el equipo. Ejemplo: openai.gpt-transcribe, 0,0045 USD por minuto.';
COMMENT ON COLUMN ai.models.code IS 'Clave proveedor.modelo, por ejemplo openai.gpt-transcribe';
COMMENT ON COLUMN ai.models.provider IS 'Proveedor: openai, groq, deepgram, deepseek, anthropic, google';
COMMENT ON COLUMN ai.models.model IS 'Id del modelo que espera la API del proveedor; único por proveedor';
COMMENT ON COLUMN ai.models.kind IS 'stt, llm, audio_llm o vision_llm';
COMMENT ON COLUMN ai.models.price_per_minute_usd IS 'Precio por minuto de audio; obligatorio en stt';
COMMENT ON COLUMN ai.models.min_billed_seconds IS 'Mínimo que cobra el proveedor por llamada (Groq cobra 10 s). Por defecto 0';
COMMENT ON COLUMN ai.models.input_per_mtok_usd IS 'Precio por millón de tokens de entrada; obligatorio en LLM';
COMMENT ON COLUMN ai.models.cached_input_per_mtok_usd IS 'Precio por millón de tokens de entrada en caché';
COMMENT ON COLUMN ai.models.output_per_mtok_usd IS 'Precio por millón de tokens de salida; obligatorio en LLM';
COMMENT ON COLUMN ai.models.is_active IS 'false = no se usa aunque esté en una ruta (apagado de emergencia). Por defecto sí';
COMMENT ON COLUMN ai.models.shutdown_on IS 'Fecha de retiro anunciada por el proveedor; desde ese día sale solo de las rutas';
COMMENT ON COLUMN ai.models.prices_checked_on IS 'Cuándo se verificaron los precios';
COMMENT ON COLUMN ai.models.notes IS 'Notas para el equipo';
COMMENT ON COLUMN ai.models.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ai.models.updated_at IS 'Última modificación; la actualiza un trigger';

-- ai.route_changes
COMMENT ON TABLE ai.route_changes IS
  'Historial de cambios del orden de proveedores: quién, cuándo, el orden anterior, el nuevo y el motivo. Quién escribe: ai.set_route_order(). Ejemplo: Dana puso a DeepSeek de principal por timeouts de OpenAI.';
COMMENT ON COLUMN ai.route_changes.id IS 'Número correlativo del cambio';
COMMENT ON COLUMN ai.route_changes.task IS 'Paso que cambió';
COMMENT ON COLUMN ai.route_changes.changed_at IS 'Cuándo';
COMMENT ON COLUMN ai.route_changes.changed_by IS 'Quién (correo del equipo)';
COMMENT ON COLUMN ai.route_changes.old_order IS 'Orden anterior de modelos activos';
COMMENT ON COLUMN ai.route_changes.new_order IS 'Orden nuevo';
COMMENT ON COLUMN ai.route_changes.reason IS 'Motivo, por ejemplo "OpenAI con timeouts"';

-- ai.routes
COMMENT ON TABLE ai.routes IS
  'Orden de proveedores por tarea: posición 1 = principal, 2+ = respaldos, con tiempo límite y reintentos. Quién escribe: el equipo con ai.set_route_order(). Ejemplo: voice.extract → 1 GPT-6 Luna, 2 DeepSeek, 3 Claude Haiku.';
COMMENT ON COLUMN ai.routes.task IS 'Paso; parte de la clave primaria';
COMMENT ON COLUMN ai.routes.position IS '1 = principal, 2 = primer respaldo…; parte de la clave primaria';
COMMENT ON COLUMN ai.routes.model_code IS 'Modelo que se usa en esa posición';
COMMENT ON COLUMN ai.routes.is_active IS 'Si la posición se usa. Por defecto sí';
COMMENT ON COLUMN ai.routes.timeout_ms IS 'Tiempo máximo de espera (500 a 60.000 ms) antes de pasar al siguiente. Por defecto 8.000';
COMMENT ON COLUMN ai.routes.max_retries IS 'Reintentos con el mismo modelo antes de pasar al siguiente (0 a 3). Por defecto 1';
COMMENT ON COLUMN ai.routes.updated_at IS 'Última modificación; la actualiza un trigger';

-- ai.tasks
COMMENT ON TABLE ai.tasks IS
  'Pasos que hace la IA. Una tarea nueva (por ejemplo leer facturas) es una fila más. Quién escribe: el equipo. Ejemplo: voice.transcribe (voz a texto) y voice.extract (frase a movimiento).';
COMMENT ON COLUMN ai.tasks.key IS 'Clave del paso, por ejemplo voice.transcribe';
COMMENT ON COLUMN ai.tasks.model_kind IS 'Tipo de modelo que necesita: stt (voz a texto), llm, audio_llm o vision_llm';
COMMENT ON COLUMN ai.tasks.description IS 'Qué hace el paso';

-- ai.usage_monthly
COMMENT ON TABLE ai.usage_monthly IS
  'Uso de IA por usuario, mes y tarea: llamadas, fallas, audio, tokens y costo. Permite contar cuánto usa y cuánto cuesta cada usuario sin recorrer ai.calls. Quién escribe: un trigger de ai.calls. Ejemplo: María, octubre, voice.extract: 24 llamadas, 1 fallida, 0,0086 USD.';
COMMENT ON COLUMN ai.usage_monthly.user_id IS 'Usuario (sin FK: el registro de costos sobrevive aunque se borre el usuario); parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.period IS 'Mes (siempre el día 1); parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.task IS 'Tarea: voice.transcribe o voice.extract; parte de la clave primaria';
COMMENT ON COLUMN ai.usage_monthly.calls IS 'Llamadas hechas en el mes, sumando reintentos y respaldos';
COMMENT ON COLUMN ai.usage_monthly.failed_calls IS 'De esas, cuántas no respondieron bien (status distinto de ok)';
COMMENT ON COLUMN ai.usage_monthly.audio_seconds IS 'Segundos de audio enviados (voz a texto)';
COMMENT ON COLUMN ai.usage_monthly.input_tokens IS 'Tokens de entrada enviados al LLM';
COMMENT ON COLUMN ai.usage_monthly.output_tokens IS 'Tokens de salida recibidos del LLM';
COMMENT ON COLUMN ai.usage_monthly.cost_usd IS 'Costo total en dólares, incluidas las llamadas fallidas que se cobraron';
COMMENT ON COLUMN ai.usage_monthly.updated_at IS 'Última vez que se sumó una llamada';

-- ai.voice_entries
COMMENT ON TABLE ai.voice_entries IS
  'Cada dictado (o frase escrita) y su resultado: transcripción, movimiento extraído, modelos que respondieron, intentos y costo. Particionada por mes. Quién escribe: la API lo crea; el worker y los triggers de ai.calls lo completan. Ejemplo: ''gasté 50 en comida'' → gasto de 50 BOB en Restaurantes, confirmado.';
COMMENT ON COLUMN ai.voice_entries.id IS 'Identificador; la clave primaria es (created_at, id)';
COMMENT ON COLUMN ai.voice_entries.created_at IS 'Cuándo se recibió; define la partición mensual';
COMMENT ON COLUMN ai.voice_entries.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN ai.voice_entries.input_type IS 'voice (dictado) o text (frase escrita). Por defecto voice';
COMMENT ON COLUMN ai.voice_entries.status IS 'received, transcribed, extracted, confirmed, discarded o failed. Por defecto received';
COMMENT ON COLUMN ai.voice_entries.audio_seconds IS 'Duración del audio; solo en dictados';
COMMENT ON COLUMN ai.voice_entries.audio_object_key IS 'Ruta del audio en Cloud Storage, solo si el usuario acepta guardarlo';
COMMENT ON COLUMN ai.voice_entries.transcript IS 'Texto transcrito o escrito (hasta 2.000 caracteres)';
COMMENT ON COLUMN ai.voice_entries.stt_model_code IS 'Modelo de voz a texto que respondió; lo completa la base de datos';
COMMENT ON COLUMN ai.voice_entries.llm_model_code IS 'LLM que respondió; lo completa la base de datos';
COMMENT ON COLUMN ai.voice_entries.prompt_version IS 'Versión del prompt, para comparar precisión entre versiones';
COMMENT ON COLUMN ai.voice_entries.extraction IS 'Movimiento extraído en JSON: tipo, monto, moneda, categoría, cuenta, descripción, fecha y lo que falta';
COMMENT ON COLUMN ai.voice_entries.confidence IS 'Confianza del LLM entre 0 y 1';
COMMENT ON COLUMN ai.voice_entries.attempts IS 'Llamadas hechas sumando respaldos. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.fallback_used IS 'true si algún paso lo resolvió un respaldo. Por defecto no';
COMMENT ON COLUMN ai.voice_entries.input_tokens IS 'Tokens de entrada sumados. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.output_tokens IS 'Tokens de salida sumados. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.cost_usd IS 'Costo total del dictado, incluidas las llamadas fallidas. Por defecto 0';
COMMENT ON COLUMN ai.voice_entries.latency_ms IS 'Tiempo de punta a punta; lo escribe el worker';
COMMENT ON COLUMN ai.voice_entries.transaction_id IS 'Transacción creada al confirmar; si se borra, queda vacío y el dictado se conserva';
COMMENT ON COLUMN ai.voice_entries.error IS 'Error, si falló';
COMMENT ON COLUMN ai.voice_entries.confirmed_at IS 'Cuándo lo confirmó el usuario';

-- billing.features
COMMENT ON TABLE billing.features IS
  'Funcionalidades que un plan habilita o limita. total = recursos vivos (tarjetas, monedas, metas); month = usos en el mes (dictados, consultas). Quién escribe: el equipo. Ejemplo: finance.cards (límite total), ai.voice_entries (límite al mes).';
COMMENT ON COLUMN billing.features.key IS 'Clave, por ejemplo finance.cards o ai.voice_entries';
COMMENT ON COLUMN billing.features.description IS 'Qué significa, para el equipo';
COMMENT ON COLUMN billing.features.value_type IS 'boolean (sí o no) o limit (con un número máximo)';
COMMENT ON COLUMN billing.features.limit_period IS 'Solo en limit: total (por ejemplo, tarjetas activas) o month (por ejemplo, dictados al mes)';

-- billing.payments
COMMENT ON TABLE billing.payments IS
  'Cada cobro, renovación o reembolso informado por las tiendas. La clave (provider, provider_transaction_id) evita registrar dos veces el mismo cobro. Quién escribe: los workers. Ejemplo: App Store, renovación, 4,99 USD.';
COMMENT ON COLUMN billing.payments.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.payments.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.payments.subscription_id IS 'Suscripción cobrada; si se borra, queda vacío';
COMMENT ON COLUMN billing.payments.plan_price_id IS 'Precio cobrado';
COMMENT ON COLUMN billing.payments.provider IS 'app_store, play_store, web o internal';
COMMENT ON COLUMN billing.payments.provider_transaction_id IS 'Id del cobro en la tienda';
COMMENT ON COLUMN billing.payments.kind IS 'initial, renewal, upgrade, refund o chargeback';
COMMENT ON COLUMN billing.payments.status IS 'pending, succeeded, failed o refunded';
COMMENT ON COLUMN billing.payments.amount IS 'Monto cobrado; negativo en reembolsos';
COMMENT ON COLUMN billing.payments.currency IS 'Moneda local que cobró la tienda';
COMMENT ON COLUMN billing.payments.billing_period IS 'month o year';
COMMENT ON COLUMN billing.payments.period_start IS 'Inicio del periodo pagado';
COMMENT ON COLUMN billing.payments.period_end IS 'Fin del periodo pagado';
COMMENT ON COLUMN billing.payments.store_fee IS 'Comisión de la tienda, si se conoce';
COMMENT ON COLUMN billing.payments.occurred_at IS 'Cuándo ocurrió el cobro';
COMMENT ON COLUMN billing.payments.created_at IS 'Cuándo se creó la fila';

-- billing.plan_features
COMMENT ON TABLE billing.plan_features IS
  'Cuánto permite cada plan de cada funcionalidad. Cambiar un límite es un UPDATE, sin desplegar. Quién escribe: el equipo. Ejemplo: free → finance.cards 1, finance.currencies 1, ai.voice_entries 30.';
COMMENT ON COLUMN billing.plan_features.plan_id IS 'Plan; parte de la clave primaria. Si se borra el plan, se borran sus filas';
COMMENT ON COLUMN billing.plan_features.feature_key IS 'Funcionalidad; parte de la clave primaria';
COMMENT ON COLUMN billing.plan_features.is_enabled IS 'Si el plan la incluye. Por defecto sí';
COMMENT ON COLUMN billing.plan_features.limit_value IS 'Máximo permitido; vacío = ilimitado. 0 = nada (el plan gratuito tiene 0 tarjetas)';

-- billing.plan_prices
COMMENT ON TABLE billing.plan_prices IS
  'Precio mensual y anual de cada plan de pago, con el producto de App Store y de Google Play. Un cambio de precio es una fila nueva: quien ya pagaba conserva su precio. Quién escribe: el equipo. Ejemplo: paid_1 mensual 4,99 USD, mm.plus.monthly.';
COMMENT ON COLUMN billing.plan_prices.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.plan_prices.plan_id IS 'Plan al que pertenece';
COMMENT ON COLUMN billing.plan_prices.billing_period IS 'month o year';
COMMENT ON COLUMN billing.plan_prices.currency IS 'Moneda del precio';
COMMENT ON COLUMN billing.plan_prices.amount IS 'Precio por periodo, mayor que 0';
COMMENT ON COLUMN billing.plan_prices.trial_days IS 'Días de prueba gratis (0 a 90). Por defecto 0';
COMMENT ON COLUMN billing.plan_prices.app_store_product_id IS 'Id del producto en App Store';
COMMENT ON COLUMN billing.plan_prices.play_store_product_id IS 'Id del producto y plan base en Google Play';
COMMENT ON COLUMN billing.plan_prices.web_price_id IS 'Id en una pasarela web, si algún día se cobra fuera de las tiendas';
COMMENT ON COLUMN billing.plan_prices.is_active IS 'Si se ofrece a suscriptores nuevos. Por defecto sí';
COMMENT ON COLUMN billing.plan_prices.valid_from IS 'Desde cuándo rige el precio';
COMMENT ON COLUMN billing.plan_prices.valid_until IS 'Hasta cuándo rige; vacío = vigente';
COMMENT ON COLUMN billing.plan_prices.created_at IS 'Cuándo se creó la fila';

-- billing.plans
COMMENT ON TABLE billing.plans IS
  'Planes de la app: uno gratuito (tier 0) y tres de pago. Quién escribe: el equipo. Ejemplo: free, paid_1, paid_2, paid_3.';
COMMENT ON COLUMN billing.plans.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.plans.code IS 'Código interno: free, paid_1, paid_2, paid_3; único';
COMMENT ON COLUMN billing.plans.name IS 'Nombre comercial';
COMMENT ON COLUMN billing.plans.description IS 'Descripción para la pantalla de planes';
COMMENT ON COLUMN billing.plans.tier IS 'Nivel: 0 = gratuito, mayor = plan superior; único. Sirve para saber si un cambio es subida o bajada';
COMMENT ON COLUMN billing.plans.is_public IS 'Si se muestra en la pantalla de planes. Por defecto sí';
COMMENT ON COLUMN billing.plans.is_active IS 'Si se puede contratar. Por defecto sí';
COMMENT ON COLUMN billing.plans.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN billing.plans.updated_at IS 'Última modificación; la actualiza un trigger';

-- billing.subscription_changes
COMMENT ON TABLE billing.subscription_changes IS
  'Historial de cada cambio de suscripción: alta, renovación, subida o bajada de plan, cancelación, expiración, vuelta a gratuito. Quién escribe: un trigger de billing.subscriptions; nadie lo edita. Ejemplo: 14-10 started; 20-10 period_changed (mensual → anual).';
COMMENT ON COLUMN billing.subscription_changes.seq IS 'Número correlativo del cambio';
COMMENT ON COLUMN billing.subscription_changes.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.subscription_changes.subscription_id IS 'Suscripción que cambió; si se borra, queda vacío y el historial se conserva';
COMMENT ON COLUMN billing.subscription_changes.change_type IS 'Qué pasó: started, renewed, upgraded, downgraded, period_changed, auto_renew_disabled, expired, reverted_to_free y otros 13 tipos';
COMMENT ON COLUMN billing.subscription_changes.from_plan_id IS 'Plan anterior';
COMMENT ON COLUMN billing.subscription_changes.to_plan_id IS 'Plan nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_price_id IS 'Precio anterior';
COMMENT ON COLUMN billing.subscription_changes.to_price_id IS 'Precio nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_period IS 'Periodo anterior (month o year)';
COMMENT ON COLUMN billing.subscription_changes.to_period IS 'Periodo nuevo';
COMMENT ON COLUMN billing.subscription_changes.from_status IS 'Estado anterior';
COMMENT ON COLUMN billing.subscription_changes.to_status IS 'Estado nuevo';
COMMENT ON COLUMN billing.subscription_changes.source IS 'Quién lo originó: store_webhook, user, admin, job o system. Por defecto system';
COMMENT ON COLUMN billing.subscription_changes.effective_at IS 'Cuándo tuvo efecto';

-- billing.subscription_events
COMMENT ON TABLE billing.subscription_events IS
  'Avisos crudos recibidos de App Store y Google Play, para procesarlos una sola vez y poder reintentarlos. Quién escribe: el worker de webhooks. Ejemplo: DID_RENEW recibido a las 10:02, procesado a las 10:02.';
COMMENT ON COLUMN billing.subscription_events.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.subscription_events.subscription_id IS 'Suscripción a la que se refiere, una vez identificada';
COMMENT ON COLUMN billing.subscription_events.provider IS 'Tienda que la envió';
COMMENT ON COLUMN billing.subscription_events.provider_event_id IS 'Id del aviso en la tienda';
COMMENT ON COLUMN billing.subscription_events.event_type IS 'Tipo de aviso según la tienda';
COMMENT ON COLUMN billing.subscription_events.payload IS 'Contenido completo del aviso, en JSON';
COMMENT ON COLUMN billing.subscription_events.received_at IS 'Cuándo llegó';
COMMENT ON COLUMN billing.subscription_events.processed_at IS 'Cuándo lo procesó el worker; vacío = pendiente';
COMMENT ON COLUMN billing.subscription_events.error IS 'Error al procesarlo, si lo hubo';

-- billing.subscriptions
COMMENT ON TABLE billing.subscriptions IS
  'Suscripción de un usuario a un plan de pago, mensual o anual, con su estado. Sin suscripción con acceso, el usuario está en el plan gratuito. Quién escribe: los workers que procesan los avisos de App Store y Google Play. Ejemplo: María en paid_1 mensual, activa hasta el 14-11.';
COMMENT ON COLUMN billing.subscriptions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN billing.subscriptions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN billing.subscriptions.plan_id IS 'Plan contratado';
COMMENT ON COLUMN billing.subscriptions.plan_price_id IS 'Precio contratado; la FK (plan_price_id, plan_id, billing_period) exige que sea de ese plan y ese periodo';
COMMENT ON COLUMN billing.subscriptions.billing_period IS 'month o year';
COMMENT ON COLUMN billing.subscriptions.status IS 'trialing, active, grace_period, on_hold, paused, expired o revoked. Los tres primeros dan acceso al plan de pago';
COMMENT ON COLUMN billing.subscriptions.provider IS 'Dónde se pagó: app_store, play_store, web o internal';
COMMENT ON COLUMN billing.subscriptions.provider_subscription_id IS 'Id en la tienda (original_transaction_id en App Store, purchase token en Google Play); único por tienda';
COMMENT ON COLUMN billing.subscriptions.auto_renew IS 'false = el usuario canceló; conserva el acceso hasta current_period_end. Por defecto sí';
COMMENT ON COLUMN billing.subscriptions.started_at IS 'Cuándo empezó la suscripción';
COMMENT ON COLUMN billing.subscriptions.trial_ends_at IS 'Fin de la prueba gratis';
COMMENT ON COLUMN billing.subscriptions.current_period_start IS 'Inicio del periodo pagado actual';
COMMENT ON COLUMN billing.subscriptions.current_period_end IS 'Hasta cuándo tiene acceso pagado';
COMMENT ON COLUMN billing.subscriptions.grace_period_ends_at IS 'Fin del periodo de gracia tras un cobro fallido';
COMMENT ON COLUMN billing.subscriptions.pending_plan_price_id IS 'Cambio programado para el fin del periodo (por ejemplo, de mensual a anual)';
COMMENT ON COLUMN billing.subscriptions.pending_change_at IS 'Cuándo se aplica el cambio programado; existe solo junto con pending_plan_price_id';
COMMENT ON COLUMN billing.subscriptions.canceled_at IS 'Cuándo apagó la renovación';
COMMENT ON COLUMN billing.subscriptions.cancel_reason IS 'user, billing_error, refund, price_increase_declined, replaced u other';
COMMENT ON COLUMN billing.subscriptions.ended_at IS 'Cuándo perdió el acceso; existe solo si status es expired o revoked';
COMMENT ON COLUMN billing.subscriptions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN billing.subscriptions.updated_at IS 'Última modificación; la actualiza un trigger';

-- billing.usage_counters
COMMENT ON TABLE billing.usage_counters IS
  'Usos del mes de las funcionalidades con límite mensual. Se descuentan con billing.try_consume() y se devuelven con billing.release(). Quién escribe: esas funciones. Ejemplo: María, ai.voice_entries, octubre: 12 usados.';
COMMENT ON COLUMN billing.usage_counters.user_id IS 'Usuario; parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.feature_key IS 'Funcionalidad; parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.period_start IS 'Mes (día 1); parte de la clave primaria';
COMMENT ON COLUMN billing.usage_counters.used IS 'Usos en el mes. billing.release() lo devuelve si la acción falló por nosotros. Por defecto 0';
COMMENT ON COLUMN billing.usage_counters.updated_at IS 'Última vez que se sumó o devolvió un uso';

-- catalog.account_types
COMMENT ON TABLE catalog.account_types IS
  'Tipos de cuenta: efectivo y tarjeta (sin distinguir débito de crédito). De aquí sale si un movimiento se pagó en efectivo o con tarjeta (is_card). Quién escribe: el equipo. Ejemplo: card, Tarjeta, es tarjeta.';
COMMENT ON COLUMN catalog.account_types.code IS 'Clave: cash (efectivo) o card (tarjeta)';
COMMENT ON COLUMN catalog.account_types.names IS 'Nombre por idioma en JSON; el español es obligatorio';
COMMENT ON COLUMN catalog.account_types.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN catalog.account_types.is_card IS 'true = es una tarjeta: cuenta para el límite de tarjetas del plan y sus movimientos se pagan "con tarjeta". false = efectivo';
COMMENT ON COLUMN catalog.account_types.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN catalog.account_types.is_active IS 'Si se puede usar; desactivar no borra nada. Por defecto sí';

-- catalog.category_templates
COMMENT ON TABLE catalog.category_templates IS
  'Categorías iniciales que recibe cada usuario nuevo. Solo categorías, sin subcategorías. Quién escribe: el equipo. Ejemplo: groceries (Supermercado), gasto, grupo Necesidades.';
COMMENT ON COLUMN catalog.category_templates.key IS 'Clave en minúsculas, por ejemplo groceries';
COMMENT ON COLUMN catalog.category_templates.kind IS 'income (ingreso) o expense (gasto). Lista fija catalog.money_kind';
COMMENT ON COLUMN catalog.category_templates.flow_group IS 'Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos';
COMMENT ON COLUMN catalog.category_templates.names IS 'Nombre por idioma en JSON, por ejemplo {"es": "Comida", "en": "Food"}; el español es obligatorio';
COMMENT ON COLUMN catalog.category_templates.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN catalog.category_templates.color IS 'Color en hexadecimal (#RRGGBB)';
COMMENT ON COLUMN catalog.category_templates.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN catalog.category_templates.is_active IS 'Si se puede usar; desactivar no borra nada. Por defecto sí';

-- catalog.countries
COMMENT ON TABLE catalog.countries IS
  'Países (ISO 3166-1) con su moneda local. Sirve para el país del perfil y para mostrar los bancos de cada país. Quién escribe: el equipo; agregar un país es un INSERT. Ejemplo: BO, Bolivia, BOB.';
COMMENT ON COLUMN catalog.countries.code IS 'Código ISO 3166-1 de 2 letras, por ejemplo BO';
COMMENT ON COLUMN catalog.countries.name IS 'Nombre del país en español';
COMMENT ON COLUMN catalog.countries.currency IS 'Moneda local del país (opcional); la app la propone como moneda principal';
COMMENT ON COLUMN catalog.countries.is_active IS 'Si se ofrece en la app. Por defecto sí';
COMMENT ON COLUMN catalog.countries.sort_order IS 'Orden en el selector. Por defecto 100';

-- catalog.currencies
COMMENT ON TABLE catalog.currencies IS
  'Monedas que ofrece la app (ISO 4217). Agregar una es un INSERT; desactivarla la oculta para cuentas nuevas sin tocar lo existente. Quién escribe: el equipo. Ejemplo: BOB, Boliviano, Bs, 2 decimales.';
COMMENT ON COLUMN catalog.currencies.code IS 'Código ISO de 3 letras, por ejemplo BOB';
COMMENT ON COLUMN catalog.currencies.name IS 'Nombre de la moneda';
COMMENT ON COLUMN catalog.currencies.symbol IS 'Símbolo, por ejemplo Bs o $';
COMMENT ON COLUMN catalog.currencies.decimals IS 'Cuántos decimales acepta un monto en esta moneda: BOB y USD 2, CLP y PYG 0 (0 a 4). Por defecto 2. 1000,5 pesos chilenos se rechaza (invalid_amount)';
COMMENT ON COLUMN catalog.currencies.is_active IS 'Si se ofrece en la app. Inactiva = no se acepta en cuentas, metas, moneda principal ni Mis monedas nuevos; las cuentas que ya existen siguen registrando. Por defecto sí';
COMMENT ON COLUMN catalog.currencies.sort_order IS 'Orden en el selector, después de Mis monedas. Por defecto 100';

-- catalog.financial_institutions
COMMENT ON TABLE catalog.financial_institutions IS
  'Bancos, cooperativas, microfinancieras y billeteras de cada país que emiten tarjetas. La app muestra la lista del país del usuario en vez de pedir el nombre como texto. Quién escribe: el equipo. Ejemplo: bo.bnb, Banco Nacional de Bolivia (BNB), banco.';
COMMENT ON COLUMN catalog.financial_institutions.code IS 'Clave: país en minúsculas, punto y nombre corto, por ejemplo bo.bnb';
COMMENT ON COLUMN catalog.financial_institutions.country_code IS 'País de la institución';
COMMENT ON COLUMN catalog.financial_institutions.name IS 'Nombre completo, por ejemplo Banco Nacional de Bolivia';
COMMENT ON COLUMN catalog.financial_institutions.short_name IS 'Nombre corto que muestra la app, por ejemplo BNB; único dentro del país';
COMMENT ON COLUMN catalog.financial_institutions.kind IS 'bank (banco), cooperative (cooperativa), microfinance (microfinanciera) o fintech (billetera o banco digital). Por defecto bank';
COMMENT ON COLUMN catalog.financial_institutions.is_active IS 'Si se ofrece en la app; desactivarla no afecta las tarjetas que ya la usan. Por defecto sí';
COMMENT ON COLUMN catalog.financial_institutions.sort_order IS 'Orden en la lista: los más usados primero. Por defecto 100';

-- core.audit_log
COMMENT ON TABLE core.audit_log IS
  'Historial de quién cambió qué dato sensible (cuentas, configuración, metas, suscripciones), solo con las columnas que cambiaron. Particionada por mes. Quién escribe: triggers de auditoría. Ejemplo: María cambió el nombre de su cuenta de ''Efectivo'' a ''Billetera''.';
COMMENT ON COLUMN core.audit_log.id IS 'Identificador; la clave primaria es (occurred_at, id)';
COMMENT ON COLUMN core.audit_log.occurred_at IS 'Cuándo; define la partición mensual';
COMMENT ON COLUMN core.audit_log.actor_user_id IS 'Quién hizo el cambio';
COMMENT ON COLUMN core.audit_log.owner_user_id IS 'De quién es el dato cambiado';
COMMENT ON COLUMN core.audit_log.entity IS 'Tabla, por ejemplo finance.accounts';
COMMENT ON COLUMN core.audit_log.entity_id IS 'Id de la fila';
COMMENT ON COLUMN core.audit_log.action IS 'insert, update, delete, login, export o plan_change';
COMMENT ON COLUMN core.audit_log.changes IS 'Columnas cambiadas con su valor antes y después, en JSON';
COMMENT ON COLUMN core.audit_log.ip IS 'IP de origen';

-- core.outbox_events
COMMENT ON TABLE core.outbox_events IS
  'Eventos de dominio pendientes de publicar (patrón outbox): se escriben en la misma transacción que el cambio y un worker los envía a Celery. Quién escribe: la API y los workers; el worker los marca publicados. Ejemplo: transaction.created de María.';
COMMENT ON COLUMN core.outbox_events.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN core.outbox_events.aggregate_type IS 'Tipo de entidad: transaction, goal, subscription…';
COMMENT ON COLUMN core.outbox_events.aggregate_id IS 'Id de la entidad';
COMMENT ON COLUMN core.outbox_events.user_id IS 'Dueño del dato, si aplica';
COMMENT ON COLUMN core.outbox_events.event_type IS 'Evento, por ejemplo transaction.created';
COMMENT ON COLUMN core.outbox_events.payload IS 'Datos del evento en JSON';
COMMENT ON COLUMN core.outbox_events.occurred_at IS 'Cuándo ocurrió';
COMMENT ON COLUMN core.outbox_events.published_at IS 'Cuándo se publicó; vacío = pendiente';
COMMENT ON COLUMN core.outbox_events.attempts IS 'Intentos de publicación. Por defecto 0';

-- finance.accounts
COMMENT ON TABLE finance.accounts IS
  'Dónde está el dinero del usuario: su efectivo y sus tarjetas, cada una con su saldo. Una moneda por cuenta y una sola cuenta por defecto. Quién escribe: la API (crear, renombrar, archivar); los triggers (saldo, cuenta por defecto, límites del plan). Ejemplo: ''Tarjeta BNB Bs'', tarjeta, BOB, saldo 1.525,40.';
COMMENT ON COLUMN finance.accounts.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.accounts.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.accounts.name IS 'Nombre que le da el usuario (1 a 80 caracteres)';
COMMENT ON COLUMN finance.accounts.type IS 'cash (efectivo) o card (tarjeta). Las dos tienen saldo. Crear una tarjeta, desarchivarla o convertir una cuenta en tarjeta cuenta para el límite de tarjetas del plan. No cambia si la cuenta ya tiene movimientos';
COMMENT ON COLUMN finance.accounts.currency IS 'Moneda de la cuenta; debe estar activa. Todo lo que pasa en la cuenta queda en esta moneda. Para tener Bs y USD se crean dos cuentas; una moneda nueva cuenta para el límite de monedas del plan. Solo se corrige mientras la cuenta no tenga movimientos ni recurrentes (account_currency_locked)';
COMMENT ON COLUMN finance.accounts.opening_balance IS 'Saldo con el que se creó la cuenta. Por defecto 0';
COMMENT ON COLUMN finance.accounts.current_balance IS 'Saldo actual. Lo mantiene un trigger con cada movimiento; la API no lo escribe. En tarjetas de crédito es negativo (deuda). Por defecto 0';
COMMENT ON COLUMN finance.accounts.is_default IS 'Cuenta por defecto: la que la app propone primero en Quick Add, voz y escaneo. Una sola por usuario. La primera cuenta lo es sola; marcar otra desmarca la anterior; si se archiva, pasa a la siguiente cuenta activa';
COMMENT ON COLUMN finance.accounts.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN finance.accounts.archived_at IS 'Archivada: se oculta en la app y conserva su historial. Una cuenta archivada no cuenta para los límites del plan ni puede ser la cuenta por defecto';
COMMENT ON COLUMN finance.accounts.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.accounts.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.accounts.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.cards
COMMENT ON TABLE finance.cards IS
  'Datos que solo tienen las tarjetas (1 a 1 con su cuenta): banco emisor del catálogo y últimos 4 dígitos. El saldo y la moneda están en finance.accounts. Quién escribe: la API al crear o editar una tarjeta. Ejemplo: Visa del BNB ••9012.';
COMMENT ON COLUMN finance.cards.account_id IS 'Cuenta de tipo tarjeta a la que pertenecen estos datos; es también la clave primaria (1 a 1)';
COMMENT ON COLUMN finance.cards.user_id IS 'Usuario dueño; junto con account_id y account_type asegura que la tarjeta sea suya';
COMMENT ON COLUMN finance.cards.account_type IS 'Siempre card: junto con account_id asegura que la cuenta sea una tarjeta. El efectivo no puede tener fila aquí';
COMMENT ON COLUMN finance.cards.institution_code IS 'Banco emisor, elegido de catalog.financial_institutions (opcional)';
COMMENT ON COLUMN finance.cards.last4 IS 'Últimos 4 dígitos para reconocer la tarjeta (opcional). Nunca se guarda el número completo';
COMMENT ON COLUMN finance.cards.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.cards.updated_at IS 'Última modificación; la actualiza un trigger';

-- finance.categories
COMMENT ON TABLE finance.categories IS
  'Categorías de cada usuario: copia editable de las iniciales más las que cree. kind dice si es ingreso o gasto; flow_group, a qué nodo del Money Flow va un gasto. Quién escribe: finance.setup_user() al registrarse; la API cuando el usuario crea, renombra o borra. Ejemplo: ''Supermercado'', gasto, Necesidades.';
COMMENT ON COLUMN finance.categories.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.categories.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.categories.template_key IS 'Plantilla de la que salió; se conserva aunque el usuario la renombre';
COMMENT ON COLUMN finance.categories.kind IS 'income (ingreso) o expense (gasto). Decide si un movimiento suma o resta, y no deja registrar un gasto en una categoría de ingreso';
COMMENT ON COLUMN finance.categories.flow_group IS 'Grupo del Money Flow (lista fija catalog.flow_group: needs o lifestyle); obligatorio en gastos y vacío en ingresos';
COMMENT ON COLUMN finance.categories.name IS 'Nombre que ve el usuario (1 a 60 caracteres)';
COMMENT ON COLUMN finance.categories.icon IS 'Nombre del ícono. Por defecto label';
COMMENT ON COLUMN finance.categories.color IS 'Color en hexadecimal. Por defecto #6B7280';
COMMENT ON COLUMN finance.categories.sort_order IS 'Orden en que se muestra en la app. Por defecto 0';
COMMENT ON COLUMN finance.categories.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.categories.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.categories.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.recurring_rules
COMMENT ON TABLE finance.recurring_rules IS
  'Gastos e ingresos que se repiten: alquiler, sueldo, Netflix. Sirven para recordatorios, para registrarse solos (auto_post) y para restarse en Safe to Spend (is_committed). Ingreso o gasto sale de su categoría. Quién escribe: la API (onboarding y Ajustes); el worker avanza next_due_on. Ejemplo: Alquiler, 1.500 Bs desde Efectivo, mensual desde el 31-01.';
COMMENT ON COLUMN finance.recurring_rules.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.recurring_rules.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.recurring_rules.account_id IS 'Cuenta de la que sale o a la que entra; debe ser del mismo usuario';
COMMENT ON COLUMN finance.recurring_rules.category_id IS 'Categoría del mismo usuario. De ella sale si la regla es un ingreso o un gasto';
COMMENT ON COLUMN finance.recurring_rules.amount IS 'Monto de cada repetición, mayor que 0';
COMMENT ON COLUMN finance.recurring_rules.currency IS 'Moneda de la cuenta; si no se envía, la completa la base de datos y otra se rechaza (currency_mismatch)';
COMMENT ON COLUMN finance.recurring_rules.description IS 'Texto que ve el usuario (1 a 120 caracteres)';
COMMENT ON COLUMN finance.recurring_rules.frequency IS 'weekly (cada semana), biweekly (cada 2 semanas), monthly (cada mes) o yearly (cada año). Las fechas se cuentan desde start_date: un pago del 31 cae el 28 o 29 en febrero y vuelve al 31';
COMMENT ON COLUMN finance.recurring_rules.start_date IS 'Desde cuándo rige';
COMMENT ON COLUMN finance.recurring_rules.end_date IS 'Hasta cuándo rige; vacío = sin fin';
COMMENT ON COLUMN finance.recurring_rules.next_due_on IS 'Próximo vencimiento; si no se envía, es start_date. De aquí salen los recordatorios y lo comprometido del periodo. El worker lo avanza con finance.next_occurrence()';
COMMENT ON COLUMN finance.recurring_rules.is_committed IS 'Si Safe to Spend lo resta como gasto comprometido. Por defecto sí';
COMMENT ON COLUMN finance.recurring_rules.auto_post IS 'Si al vencer se registra solo como transacción. Por defecto no';
COMMENT ON COLUMN finance.recurring_rules.remind_days_before IS 'Días de anticipación del recordatorio (0 a 14). Por defecto 1';
COMMENT ON COLUMN finance.recurring_rules.is_active IS 'Si la regla sigue vigente. Por defecto sí';
COMMENT ON COLUMN finance.recurring_rules.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.recurring_rules.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.recurring_rules.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.transactions
COMMENT ON TABLE finance.transactions IS
  'Cada ingreso, gasto o transferencia, en la moneda de su cuenta. Es la tabla más grande: está dividida en 16 particiones por usuario. Guarda la moneda (copia de la de su cuenta) para sumar por moneda sin unir tablas. Quién escribe: la API (Quick Add, voz, escaneo) y el worker (recurrentes); los triggers ajustan los saldos. Ejemplo: gasto de 105 Bs, ''Netflix'', con la tarjeta BNB el 14-10.';
COMMENT ON COLUMN finance.transactions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN finance.transactions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN finance.transactions.kind IS 'income (ingreso, suma al saldo), expense (gasto, resta) o transfer (transferencia entre dos cuentas propias). Debe coincidir con el tipo de su categoría';
COMMENT ON COLUMN finance.transactions.account_id IS 'Cuenta de origen. La FK compuesta (user_id, account_id, currency) exige que sea del mismo usuario y que currency sea su moneda';
COMMENT ON COLUMN finance.transactions.category_id IS 'Categoría del mismo usuario y del mismo tipo; vacía solo en transferencias';
COMMENT ON COLUMN finance.transactions.amount IS 'Monto en la moneda de la cuenta, mayor que 0 y con los decimales de esa moneda; de aquí sale el saldo';
COMMENT ON COLUMN finance.transactions.currency IS 'Moneda de la cuenta, copiada aquí para sumar por moneda sin unir con accounts. Si no se envía, la completa la base de datos; otra se rechaza (currency_mismatch)';
COMMENT ON COLUMN finance.transactions.transfer_account_id IS 'Cuenta de destino; solo en transferencias, activa, del mismo usuario y en la misma moneda (transfer_currency_mismatch)';
COMMENT ON COLUMN finance.transactions.occurred_on IS 'Fecha del movimiento';
COMMENT ON COLUMN finance.transactions.description IS 'Qué fue, en palabras del usuario (hasta 200 caracteres): ''Netflix'', ''Almuerzo''. Se busca por texto y sirve para sugerir categoría y cuenta en Quick Add (finance.suggest_from_history)';
COMMENT ON COLUMN finance.transactions.source IS 'Cómo se registró: manual, quick_add, voice (dictado), scan (factura), recurring (lo registró un recurrente), onboarding o adjustment (corrección de saldo). Por defecto manual';
COMMENT ON COLUMN finance.transactions.recurring_rule_id IS 'Regla recurrente que lo generó; si se borra la regla, queda vacío';
COMMENT ON COLUMN finance.transactions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN finance.transactions.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN finance.transactions.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- finance.user_currencies
COMMENT ON TABLE finance.user_currencies IS
  'Mis monedas: las que el usuario ve primero al elegir moneda. Se llena sola con la moneda principal y las de sus cuentas. Quién escribe: triggers, y la API cuando el usuario agrega o quita una. Ejemplo: María tiene BOB y USD.';
COMMENT ON COLUMN finance.user_currencies.user_id IS 'Usuario dueño; parte de la clave primaria';
COMMENT ON COLUMN finance.user_currencies.currency IS 'Moneda; debe estar activa al agregarla. No se puede quitar la moneda principal ni la de una cuenta activa';
COMMENT ON COLUMN finance.user_currencies.sort_order IS 'Orden en el selector de monedas. Por defecto 0';
COMMENT ON COLUMN finance.user_currencies.created_at IS 'Cuándo se creó la fila';

-- finance.user_settings
COMMENT ON TABLE finance.user_settings IS
  'Configuración financiera de cada usuario (una fila): moneda principal, periodo financiero y ahorro planificado. Quién escribe: finance.setup_user() en el onboarding y la API desde Ajustes. Ejemplo: moneda principal BOB, periodo mensual desde el día 25 (su día de cobro), ahorra 500 Bs por periodo.';
COMMENT ON COLUMN finance.user_settings.user_id IS 'Usuario dueño; es también la clave primaria (una fila por usuario)';
COMMENT ON COLUMN finance.user_settings.main_currency IS 'Moneda principal: la que la app muestra primero. Se elige en el onboarding y se cambia en Ajustes; cambiarla no convierte ningún monto. Debe estar activa y entra sola a Mis monedas';
COMMENT ON COLUMN finance.user_settings.period_type IS 'Cómo agrupa su dinero: weekly (semanal), semi_monthly (quincenal: dos por mes) o monthly (mensual). Por defecto monthly. Lo usan Safe to Spend, Money Flow y Money Story';
COMMENT ON COLUMN finance.user_settings.period_start_day IS 'Día en que empieza el periodo. weekly: día de la semana (0 domingo … 6 sábado). semi_monthly: día d del mes (1 a 13); la segunda quincena empieza el d + 15. monthly: día del mes (1 a 28), por ejemplo su día de cobro. Por defecto 1';
COMMENT ON COLUMN finance.user_settings.planned_savings IS 'Cuánto quiere ahorrar en cada periodo, en la moneda principal. Safe to Spend de esa moneda lo resta. Por defecto 0';
COMMENT ON COLUMN finance.user_settings.updated_at IS 'Última modificación; la actualiza un trigger';

-- goals.goal_contributions
COMMENT ON TABLE goals.goal_contributions IS
  'Aportes y retiros de cada meta, en la moneda de la meta. Su ritmo alimenta el Goal Forecast. Quién escribe: la API. Ejemplo: +300 Bs el 01-10; −50 Bs el 10-10.';
COMMENT ON COLUMN goals.goal_contributions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN goals.goal_contributions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN goals.goal_contributions.goal_id IS 'Meta; la FK (user_id, goal_id) exige que sea del mismo usuario';
COMMENT ON COLUMN goals.goal_contributions.amount IS 'Monto del aporte; negativo = retiro. No puede ser 0';
COMMENT ON COLUMN goals.goal_contributions.contributed_on IS 'Fecha del aporte. Por defecto hoy';
COMMENT ON COLUMN goals.goal_contributions.source IS 'manual, transaction o adjustment. Por defecto manual';
COMMENT ON COLUMN goals.goal_contributions.transaction_id IS 'Transferencia que lo originó; evita contar dos veces el mismo dinero';
COMMENT ON COLUMN goals.goal_contributions.note IS 'Nota opcional (hasta 500 caracteres)';
COMMENT ON COLUMN goals.goal_contributions.created_at IS 'Cuándo se creó la fila';

-- goals.goals
COMMENT ON TABLE goals.goals IS
  'Metas de ahorro: fondo de emergencia, laptop, viaje. Cada meta tiene su moneda y no se vincula a una cuenta. Quién escribe: la API; current_amount lo mantiene un trigger con los aportes. Ejemplo: Fondo de emergencia, 5.000 Bs, lleva 450, aporta 300 por periodo.';
COMMENT ON COLUMN goals.goals.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN goals.goals.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN goals.goals.name IS 'Nombre de la meta (1 a 80 caracteres)';
COMMENT ON COLUMN goals.goals.target_amount IS 'Monto objetivo, mayor que 0';
COMMENT ON COLUMN goals.goals.currency IS 'Moneda de la meta y de sus aportes; debe estar activa al crearla';
COMMENT ON COLUMN goals.goals.current_amount IS 'Monto ahorrado; lo suma un trigger con cada aporte o retiro. Por defecto 0';
COMMENT ON COLUMN goals.goals.target_date IS 'Fecha objetivo (opcional)';
COMMENT ON COLUMN goals.goals.priority IS 'Prioridad de 1 (más alta) a 5. Por defecto 3; Can I Afford It? la usa para decidir qué meta se retrasa';
COMMENT ON COLUMN goals.goals.planned_contribution IS 'Cuánto piensa aportar en cada periodo (semana, quincena o mes), opcional. Safe to Spend lo resta';
COMMENT ON COLUMN goals.goals.status IS 'active, paused, achieved o archived. Por defecto active';
COMMENT ON COLUMN goals.goals.achieved_at IS 'Cuándo se alcanzó; existe solo si status es achieved';
COMMENT ON COLUMN goals.goals.icon IS 'Nombre del ícono que muestra la app';
COMMENT ON COLUMN goals.goals.color IS 'Color en hexadecimal (#RRGGBB)';
COMMENT ON COLUMN goals.goals.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN goals.goals.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN goals.goals.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- iam.auth_identities
COMMENT ON TABLE iam.auth_identities IS
  'Formas de entrar de cada usuario: correo y contraseña, Google, Meta o Apple. Un usuario puede tener varias; cada una identifica a un solo usuario. Quién escribe: la API al registrarse o vincular un método. Ejemplo: María entra con Google (sub 1093…) y con su contraseña.';
COMMENT ON COLUMN iam.auth_identities.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.auth_identities.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.auth_identities.provider IS 'password, google, meta o apple. Un usuario tiene como máximo una identidad por proveedor';
COMMENT ON COLUMN iam.auth_identities.provider_subject IS 'El correo para password; el id que entrega el proveedor en los demás. La pareja (provider, provider_subject) es única: una cuenta de Google no se liga a dos usuarios';
COMMENT ON COLUMN iam.auth_identities.password_hash IS 'Contraseña cifrada con argon2id; solo existe cuando provider es password';
COMMENT ON COLUMN iam.auth_identities.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.auth_identities.last_used_at IS 'Último inicio de sesión con este método';

-- iam.devices
COMMENT ON TABLE iam.devices IS
  'Teléfonos y navegadores del usuario: token de notificaciones push y si activó huella o rostro. Quién escribe: la API al iniciar sesión o renovar el token push. Ejemplo: iPhone de María, iOS 19, biometría activada.';
COMMENT ON COLUMN iam.devices.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.devices.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.devices.platform IS 'ios, android o web';
COMMENT ON COLUMN iam.devices.push_token IS 'Token de Firebase Cloud Messaging para enviar notificaciones';
COMMENT ON COLUMN iam.devices.app_version IS 'Versión de la app instalada';
COMMENT ON COLUMN iam.devices.os_version IS 'Versión del sistema operativo';
COMMENT ON COLUMN iam.devices.biometric_enabled IS 'Si activó huella o rostro; la validación la hace el sistema operativo, no la app. Por defecto no';
COMMENT ON COLUMN iam.devices.last_seen_at IS 'Última vez que el dispositivo usó la app';
COMMENT ON COLUMN iam.devices.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.devices.revoked_at IS 'Cuándo se cerró la sesión en este dispositivo';

-- iam.sessions
COMMENT ON TABLE iam.sessions IS
  'Sesiones abiertas: cada refresh token (guardado como hash) y su dispositivo. Permite cerrar sesión en un dispositivo, ver dispositivos activos y detectar un token robado que se reusa. Quién escribe: la API al iniciar sesión y en cada renovación (rotación). Ejemplo: sesión del iPhone, vence en 30 días.';
COMMENT ON COLUMN iam.sessions.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.sessions.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.sessions.device_id IS 'Dispositivo de la sesión; si se borra el dispositivo, queda vacío';
COMMENT ON COLUMN iam.sessions.refresh_token_hash IS 'Hash del refresh token (nunca el token); único';
COMMENT ON COLUMN iam.sessions.replaced_by IS 'Sesión nueva creada al renovar. Si alguien usa un token ya reemplazado, se detecta un posible robo';
COMMENT ON COLUMN iam.sessions.ip IS 'IP desde la que se abrió';
COMMENT ON COLUMN iam.sessions.user_agent IS 'Navegador o app que la abrió';
COMMENT ON COLUMN iam.sessions.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.sessions.expires_at IS 'Vencimiento; debe ser posterior a created_at';
COMMENT ON COLUMN iam.sessions.revoked_at IS 'Cuándo se cerró la sesión';

-- iam.terms_versions
COMMENT ON TABLE iam.terms_versions IS
  'Versiones publicadas de los términos de uso y la política de privacidad; solo una es la vigente. Quién escribe: el equipo, al publicar una versión nueva. Ejemplo: 2026-10, vigente, con sus dos enlaces.';
COMMENT ON COLUMN iam.terms_versions.version IS 'Versión, por ejemplo 2026-10';
COMMENT ON COLUMN iam.terms_versions.terms_url IS 'Enlace a los términos';
COMMENT ON COLUMN iam.terms_versions.privacy_url IS 'Enlace a la política de privacidad';
COMMENT ON COLUMN iam.terms_versions.is_current IS 'Si es la vigente; solo una puede serlo';
COMMENT ON COLUMN iam.terms_versions.published_at IS 'Cuándo se publicó';

-- iam.user_preferences
COMMENT ON TABLE iam.user_preferences IS
  'Personalización de la app guardada en el servidor, para que sea igual en todos los dispositivos. Quién escribe: un trigger la crea al registrarse; después la API cuando el usuario cambia tema, color, modo privado o inicio de semana. Ejemplo: tema oscuro, acento verde, montos ocultos, semana desde el lunes.';
COMMENT ON COLUMN iam.user_preferences.user_id IS 'Usuario dueño; es también la clave primaria';
COMMENT ON COLUMN iam.user_preferences.theme IS 'system (del teléfono), light o dark. Por defecto system';
COMMENT ON COLUMN iam.user_preferences.accent_color IS 'Color de acento #RRGGBB; vacío = color de la marca';
COMMENT ON COLUMN iam.user_preferences.hide_amounts IS 'Modo privado: la app abre con los montos ocultos. Por defecto no';
COMMENT ON COLUMN iam.user_preferences.week_starts_on IS 'Día de inicio de semana: 0 domingo a 6 sábado. Por defecto 1 (lunes)';
COMMENT ON COLUMN iam.user_preferences.updated_at IS 'Última modificación; la actualiza un trigger';

-- iam.users
COMMENT ON TABLE iam.users IS
  'Una fila por persona registrada: es la cuenta que inicia sesión, paga y es dueña de todos sus datos financieros. Quién escribe: la API al registrarse y al editar el perfil; la base limpia nombres, teléfono y país y exige 18 años y los términos vigentes. Ejemplo: María José Rojas, maria@correo.com, nacida en 1995, estudiante en La Paz.';
COMMENT ON COLUMN iam.users.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.users.email IS 'Correo de la cuenta; único sin distinguir mayúsculas';
COMMENT ON COLUMN iam.users.email_verified_at IS 'Cuándo confirmó su correo; vacío si no lo confirmó';
COMMENT ON COLUMN iam.users.first_name IS 'Nombre (1 a 60 caracteres); se guarda sin espacios de más';
COMMENT ON COLUMN iam.users.last_name IS 'Apellido (1 a 60 caracteres); se guarda sin espacios de más';
COMMENT ON COLUMN iam.users.display_name IS 'Cómo quiere que lo llame la app (1 a 120 caracteres); vacío = su nombre';
COMMENT ON COLUMN iam.users.avatar_object_key IS 'Ruta de la foto de perfil en Cloud Storage';
COMMENT ON COLUMN iam.users.birth_date IS 'Fecha de nacimiento; la base de datos rechaza menores de 18 años';
COMMENT ON COLUMN iam.users.phone_e164 IS 'Teléfono en formato E.164 (+59171234567); se guarda sin espacios, guiones ni paréntesis';
COMMENT ON COLUMN iam.users.country_code IS 'País ISO 3166-1 en mayúsculas (BO)';
COMMENT ON COLUMN iam.users.city IS 'Ciudad (hasta 80 caracteres)';
COMMENT ON COLUMN iam.users.occupation IS 'student, employee, self_employed, entrepreneur, unemployed, retired u other';
COMMENT ON COLUMN iam.users.terms_version IS 'Versión de los términos que aceptó; al registrarse debe ser la vigente (terms_outdated)';
COMMENT ON COLUMN iam.users.terms_accepted_at IS 'Cuándo aceptó los términos';
COMMENT ON COLUMN iam.users.locale IS 'Idioma y región de la app. Por defecto es-BO';
COMMENT ON COLUMN iam.users.timezone IS 'Zona horaria para fechas y avisos. Por defecto America/La_Paz';
COMMENT ON COLUMN iam.users.status IS 'active, suspended, pending_deletion o deleted. Por defecto active';
COMMENT ON COLUMN iam.users.onboarding_completed_at IS 'Cuándo terminó el onboarding; con fecha, no se vuelve a mostrar';
COMMENT ON COLUMN iam.users.last_login_at IS 'Último inicio de sesión';
COMMENT ON COLUMN iam.users.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN iam.users.updated_at IS 'Última modificación; la actualiza un trigger';
COMMENT ON COLUMN iam.users.deleted_at IS 'Borrado lógico: con fecha, la fila está borrada pero se conserva para el historial';

-- iam.verification_tokens
COMMENT ON TABLE iam.verification_tokens IS
  'Códigos de un solo uso para verificar el correo, recuperar la contraseña o cambiar el correo, guardados como hash. Quién escribe: la API al enviar el correo; se marca usado al confirmarlo. Ejemplo: recuperación de contraseña, vence en 1 hora.';
COMMENT ON COLUMN iam.verification_tokens.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN iam.verification_tokens.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN iam.verification_tokens.purpose IS 'email_verification, password_reset o email_change';
COMMENT ON COLUMN iam.verification_tokens.token_hash IS 'Hash del código; único';
COMMENT ON COLUMN iam.verification_tokens.expires_at IS 'Hasta cuándo vale el código';
COMMENT ON COLUMN iam.verification_tokens.used_at IS 'Cuándo se usó; un código usado no vale otra vez';
COMMENT ON COLUMN iam.verification_tokens.created_at IS 'Cuándo se creó la fila';

-- notify.notification_types
COMMENT ON TABLE notify.notification_types IS
  'Tipos de aviso que existen y si el usuario los puede apagar (los de seguridad y suscripción no). Quién escribe: el equipo. Ejemplo: recurring.due_soon, activado por defecto.';
COMMENT ON COLUMN notify.notification_types.key IS 'Clave del aviso, por ejemplo recurring.due_soon';
COMMENT ON COLUMN notify.notification_types.description IS 'Qué avisa';
COMMENT ON COLUMN notify.notification_types.default_enabled IS 'Si está activo para quien no cambió sus preferencias. Por defecto sí';
COMMENT ON COLUMN notify.notification_types.is_transactional IS 'true = obligatorio (seguridad, suscripción): no se puede desactivar. Por defecto no';

-- notify.notifications
COMMENT ON TABLE notify.notifications IS
  'Bandeja y registro de envíos de cada aviso. Particionada por mes. Quién escribe: los workers al encolar y al enviar; la API marca read_at. Ejemplo: ''Mañana vence tu alquiler de 1.500 Bs'', enviada el 30-10.';
COMMENT ON COLUMN notify.notifications.id IS 'Identificador; la clave primaria es (created_at, id) por estar particionada por mes';
COMMENT ON COLUMN notify.notifications.created_at IS 'Cuándo se creó; define la partición mensual';
COMMENT ON COLUMN notify.notifications.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN notify.notifications.type_key IS 'Tipo de aviso';
COMMENT ON COLUMN notify.notifications.channel IS 'push, email o in_app. Por defecto push';
COMMENT ON COLUMN notify.notifications.title IS 'Título (hasta 120 caracteres)';
COMMENT ON COLUMN notify.notifications.body IS 'Texto (hasta 500 caracteres)';
COMMENT ON COLUMN notify.notifications.data IS 'Enlace a la pantalla e ids relacionados, en JSON';
COMMENT ON COLUMN notify.notifications.dedupe_key IS 'Evita enviar el mismo aviso dos veces, por ejemplo recurring:<id>:2026-10';
COMMENT ON COLUMN notify.notifications.status IS 'queued, sent, failed, skipped o read. Por defecto queued';
COMMENT ON COLUMN notify.notifications.scheduled_for IS 'Cuándo debe enviarse';
COMMENT ON COLUMN notify.notifications.sent_at IS 'Cuándo se envió';
COMMENT ON COLUMN notify.notifications.read_at IS 'Cuándo lo leyó el usuario';
COMMENT ON COLUMN notify.notifications.error IS 'Error de envío, si lo hubo';

-- notify.preferences
COMMENT ON TABLE notify.preferences IS
  'Avisos que el usuario cambió en Ajustes; sin fila se usa el valor por defecto del tipo. Quién escribe: la API. Ejemplo: María apagó goal.milestone por push.';
COMMENT ON COLUMN notify.preferences.user_id IS 'Usuario; parte de la clave primaria';
COMMENT ON COLUMN notify.preferences.type_key IS 'Tipo de aviso; parte de la clave primaria';
COMMENT ON COLUMN notify.preferences.channel IS 'push, email o in_app; parte de la clave primaria. Por defecto push';
COMMENT ON COLUMN notify.preferences.is_enabled IS 'Si quiere recibirlo';
COMMENT ON COLUMN notify.preferences.updated_at IS 'Última vez que cambió la preferencia';

-- ops.incident_affected_users
COMMENT ON TABLE ops.incident_affected_users IS
  'Usuarios afectados por cada incidente, para avisarles o compensarlos. Quién escribe: ops.log() cuando el error tiene usuario. Ejemplo: INC-000012 afectó a María; avisada el 15-10.';
COMMENT ON COLUMN ops.incident_affected_users.incident_id IS 'Incidente; parte de la clave primaria';
COMMENT ON COLUMN ops.incident_affected_users.user_id IS 'Usuario afectado (sin FK); parte de la clave primaria';
COMMENT ON COLUMN ops.incident_affected_users.first_seen_at IS 'Cuándo lo afectó por primera vez';
COMMENT ON COLUMN ops.incident_affected_users.notified_at IS 'Cuándo se le avisó';

-- ops.incident_updates
COMMENT ON TABLE ops.incident_updates IS
  'Línea de tiempo de cada incidente: cambios de estado y severidad, y notas del equipo. Quién escribe: triggers de ops.incidents y el equipo. Ejemplo: 10:05 open → investigating, por dana@moneymap.team.';
COMMENT ON COLUMN ops.incident_updates.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN ops.incident_updates.incident_id IS 'Incidente';
COMMENT ON COLUMN ops.incident_updates.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ops.incident_updates.author IS 'Quién hizo el cambio (correo del equipo o system). Por defecto system';
COMMENT ON COLUMN ops.incident_updates.status_from IS 'Estado anterior';
COMMENT ON COLUMN ops.incident_updates.status_to IS 'Estado nuevo';
COMMENT ON COLUMN ops.incident_updates.severity_from IS 'Severidad anterior';
COMMENT ON COLUMN ops.incident_updates.severity_to IS 'Severidad nueva';
COMMENT ON COLUMN ops.incident_updates.note IS 'Nota del equipo';
COMMENT ON COLUMN ops.incident_updates.is_public IS 'Si se puede comunicar a los usuarios. Por defecto no';

-- ops.incidents
COMMENT ON TABLE ops.incidents IS
  'Agrupa errores repetidos con la misma huella y sigue su ciclo: abierto → investigando → identificado → monitoreo → resuelto → cerrado, con responsable y causa raíz. Quién escribe: ops.log() abre o suma; el equipo cambia el estado. Ejemplo: INC-000012, sev3, push.fcm.timeout, 37 ocurrencias.';
COMMENT ON COLUMN ops.incidents.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN ops.incidents.number IS 'Número correlativo; único';
COMMENT ON COLUMN ops.incidents.code IS 'INC- más el número con 6 dígitos (INC-000123)';
COMMENT ON COLUMN ops.incidents.title IS 'Título (1 a 200 caracteres)';
COMMENT ON COLUMN ops.incidents.description IS 'Descripción';
COMMENT ON COLUMN ops.incidents.severity IS 'sev1 (caída total o datos incorrectos) a sev4 (menor)';
COMMENT ON COLUMN ops.incidents.status IS 'open, investigating, identified, monitoring, resolved o closed. Por defecto open';
COMMENT ON COLUMN ops.incidents.category IS 'Categoría del log que lo abrió';
COMMENT ON COLUMN ops.incidents.fingerprint IS 'Huella de los errores agrupados; solo un incidente abierto por huella';
COMMENT ON COLUMN ops.incidents.detected_by IS 'automatic, monitoring, user_report o manual. Por defecto automatic';
COMMENT ON COLUMN ops.incidents.previous_incident_id IS 'Incidente resuelto del que este es una regresión';
COMMENT ON COLUMN ops.incidents.first_seen_at IS 'Primera ocurrencia';
COMMENT ON COLUMN ops.incidents.last_seen_at IS 'Última ocurrencia';
COMMENT ON COLUMN ops.incidents.occurrences IS 'Veces que ocurrió. Por defecto 1';
COMMENT ON COLUMN ops.incidents.affected_users IS 'Usuarios distintos afectados. Por defecto 0';
COMMENT ON COLUMN ops.incidents.assigned_to IS 'Persona del equipo a cargo';
COMMENT ON COLUMN ops.incidents.acknowledged_at IS 'Cuándo el equipo lo tomó';
COMMENT ON COLUMN ops.incidents.resolved_at IS 'Cuándo se resolvió; existe solo en resolved o closed';
COMMENT ON COLUMN ops.incidents.closed_at IS 'Cuándo se cerró';
COMMENT ON COLUMN ops.incidents.impact IS 'Impacto en los usuarios';
COMMENT ON COLUMN ops.incidents.root_cause IS 'Causa raíz';
COMMENT ON COLUMN ops.incidents.resolution IS 'Cómo se resolvió';
COMMENT ON COLUMN ops.incidents.postmortem_url IS 'Enlace al análisis posterior';
COMMENT ON COLUMN ops.incidents.created_at IS 'Cuándo se creó la fila';
COMMENT ON COLUMN ops.incidents.updated_at IS 'Última modificación; la actualiza un trigger';

-- ops.logs
COMMENT ON TABLE ops.logs IS
  'Eventos importantes del sistema, de solo inserción: errores, fallos de integraciones (tiendas, IA, push), eventos de seguridad y jobs. Nadie puede editar ni borrar un log. Particionada por mes. Quién escribe: la API y los workers con ops.log(). Ejemplo: warning ai.call.timeout de GPT-6 Luna.';
COMMENT ON COLUMN ops.logs.id IS 'Identificador; la clave primaria es (occurred_at, id)';
COMMENT ON COLUMN ops.logs.occurred_at IS 'Cuándo ocurrió; define la partición mensual';
COMMENT ON COLUMN ops.logs.level IS 'debug, info, notice, warning, error o critical';
COMMENT ON COLUMN ops.logs.severity IS 'Se calcula desde level (10 a 60) para ordenar y filtrar';
COMMENT ON COLUMN ops.logs.category IS 'api, auth, security, billing, finance, ai, notify, integration, job, database, client o system';
COMMENT ON COLUMN ops.logs.event_code IS 'Código estable del evento, por ejemplo billing.webhook.invalid_signature';
COMMENT ON COLUMN ops.logs.message IS 'Descripción legible';
COMMENT ON COLUMN ops.logs.service IS 'Quién lo escribió: api, worker, scheduler, ios, android, web o database';
COMMENT ON COLUMN ops.logs.environment IS 'prod, staging o dev';
COMMENT ON COLUMN ops.logs.release IS 'Versión de la app o commit desplegado';
COMMENT ON COLUMN ops.logs.user_id IS 'Usuario afectado (sin FK)';
COMMENT ON COLUMN ops.logs.device_id IS 'Dispositivo afectado';
COMMENT ON COLUMN ops.logs.request_id IS 'Id de la petición';
COMMENT ON COLUMN ops.logs.trace_id IS 'Id de traza, para seguir una petición entre servicios';
COMMENT ON COLUMN ops.logs.http_method IS 'Método HTTP';
COMMENT ON COLUMN ops.logs.http_path IS 'Ruta de la API';
COMMENT ON COLUMN ops.logs.http_status IS 'Código HTTP';
COMMENT ON COLUMN ops.logs.duration_ms IS 'Duración';
COMMENT ON COLUMN ops.logs.error_type IS 'Tipo de excepción, por ejemplo TimeoutError';
COMMENT ON COLUMN ops.logs.error_message IS 'Mensaje del error';
COMMENT ON COLUMN ops.logs.stack_trace IS 'Traza del error';
COMMENT ON COLUMN ops.logs.fingerprint IS 'Huella que agrupa errores iguales en un incidente';
COMMENT ON COLUMN ops.logs.incident_id IS 'Incidente al que se sumó (errores y critical); sin FK';
COMMENT ON COLUMN ops.logs.context IS 'Datos extra en JSON; nunca contraseñas, tokens ni números de tarjeta';
COMMENT ON COLUMN ops.logs.ip IS 'IP de origen';

-- planning.affordability_checks
COMMENT ON TABLE planning.affordability_checks IS
  'Historial de Can I Afford It?: qué consultó el usuario, el veredicto, el impacto en sus metas y lo que decidió. Cuenta para la North Star. Quién escribe: la API. Ejemplo: Laptop 4.000 Bs → affordable_with_impact, retrasa el Fondo 2 meses; decidió esperar.';
COMMENT ON COLUMN planning.affordability_checks.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN planning.affordability_checks.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN planning.affordability_checks.description IS 'Qué quería comprar (opcional, hasta 120 caracteres)';
COMMENT ON COLUMN planning.affordability_checks.amount IS 'Monto de la compra, mayor que 0';
COMMENT ON COLUMN planning.affordability_checks.currency IS 'Moneda del monto';
COMMENT ON COLUMN planning.affordability_checks.verdict IS 'affordable (alcanza), affordable_with_impact (alcanza retrasando metas) o not_now (todavía no)';
COMMENT ON COLUMN planning.affordability_checks.safe_to_spend_before IS 'Safe to Spend antes de la compra';
COMMENT ON COLUMN planning.affordability_checks.safe_to_spend_after IS 'Safe to Spend si hace la compra';
COMMENT ON COLUMN planning.affordability_checks.earliest_affordable_on IS 'Desde cuándo podría comprarlo, cuando el veredicto es not_now';
COMMENT ON COLUMN planning.affordability_checks.impacts IS 'Metas afectadas y cuántos meses se retrasa cada una, en JSON';
COMMENT ON COLUMN planning.affordability_checks.assumptions IS 'Supuestos que se mostraron al usuario, en JSON';
COMMENT ON COLUMN planning.affordability_checks.algorithm_version IS 'Versión del cálculo, para explicar resultados pasados';
COMMENT ON COLUMN planning.affordability_checks.decision IS 'Lo que hizo el usuario: bought, postponed o dismissed (opcional)';
COMMENT ON COLUMN planning.affordability_checks.created_at IS 'Cuándo se creó la fila';

-- reports.money_stories
COMMENT ON TABLE reports.money_stories IS
  'Resumen semanal (Weekly Check-in) o mensual (Monthly Money Story) por moneda: cuánto ganó, gastó y ahorró, y frases destacadas guardadas como claves. Quién escribe: el worker al cerrar la semana o el mes; la API marca viewed_at. Ejemplo: octubre en BOB: ingresó 5.000, gastó 3.800, ahorró 24 %.';
COMMENT ON COLUMN reports.money_stories.id IS 'Identificador único (UUID v7, ordenado por fecha de creación)';
COMMENT ON COLUMN reports.money_stories.user_id IS 'Usuario dueño de la fila';
COMMENT ON COLUMN reports.money_stories.period_type IS 'week (Weekly Check-in) o month (Monthly Money Story)';
COMMENT ON COLUMN reports.money_stories.period_start IS 'Primer día del periodo resumido';
COMMENT ON COLUMN reports.money_stories.period_end IS 'Último día del periodo resumido';
COMMENT ON COLUMN reports.money_stories.status IS 'pending, ready o failed. Por defecto pending';
COMMENT ON COLUMN reports.money_stories.currency IS 'Moneda de los totales: hay una historia por moneda con movimientos';
COMMENT ON COLUMN reports.money_stories.income_total IS 'Ingresos del periodo';
COMMENT ON COLUMN reports.money_stories.expense_total IS 'Gastos del periodo';
COMMENT ON COLUMN reports.money_stories.savings_total IS 'Ahorro del periodo (ingresos − gastos)';
COMMENT ON COLUMN reports.money_stories.savings_rate IS 'Tasa de ahorro (ahorro ÷ ingresos)';
COMMENT ON COLUMN reports.money_stories.highlights IS 'Frases destacadas como claves y parámetros en JSON, no texto final: se pueden traducir o redactar distinto sin recalcular';
COMMENT ON COLUMN reports.money_stories.template_version IS 'Versión de las plantillas de texto';
COMMENT ON COLUMN reports.money_stories.generated_at IS 'Cuándo se generó';
COMMENT ON COLUMN reports.money_stories.viewed_at IS 'Cuándo la abrió el usuario';
COMMENT ON COLUMN reports.money_stories.created_at IS 'Cuándo se creó la fila';

-- -----------------------------------------------------------------------------
-- Lo que la base hace sola (funciones de los triggers)
-- -----------------------------------------------------------------------------
COMMENT ON FUNCTION core.set_updated_at() IS 'updated_at se actualiza solo en cada cambio.';
COMMENT ON FUNCTION core.audit_row_change() IS 'Cada alta, cambio o baja queda en core.audit_log con las columnas que cambiaron (sin los saldos).';
COMMENT ON FUNCTION iam.users_before_write() IS 'Limpia nombre, apellido, teléfono, país y ciudad; display_name vacío toma el nombre; al registrarse exige los términos vigentes (terms_outdated).';
COMMENT ON FUNCTION iam.users_create_preferences() IS 'Crea las preferencias por defecto de cada usuario nuevo.';
COMMENT ON FUNCTION billing.subscriptions_before_write() IS 'Mantiene canceled_at, cancel_reason y ended_at según el estado y la renovación automática.';
COMMENT ON FUNCTION billing.log_subscription_change() IS 'Escribe cada cambio de la suscripción en billing.subscription_changes.';
COMMENT ON FUNCTION finance.user_currencies_guard() IS 'Solo monedas activas; no deja quitar la moneda principal ni la de una cuenta activa (currency_in_use).';
COMMENT ON FUNCTION finance.user_settings_before_write() IS 'La moneda principal debe estar activa.';
COMMENT ON FUNCTION finance.user_settings_after_write() IS 'La moneda principal entra sola a Mis monedas.';
COMMENT ON FUNCTION finance.sync_opening_balance() IS 'El saldo actual arranca en el saldo inicial y se corrige si este cambia.';
COMMENT ON FUNCTION finance.accounts_before_write() IS 'Valida tipo y moneda, bloquea la moneda de una cuenta usada, aplica los límites de tarjetas y monedas del plan (MM001) y deja por defecto la primera cuenta.';
COMMENT ON FUNCTION finance.accounts_after_write() IS 'Agrega la moneda a Mis monedas y mantiene una sola cuenta por defecto (marcar otra desmarca la anterior; si se archiva, pasa a la siguiente).';
COMMENT ON FUNCTION finance.recurring_rules_before_write() IS 'Toma la moneda de la cuenta (currency_mismatch si se envía otra) y usa start_date como primer vencimiento.';
COMMENT ON FUNCTION finance.transactions_before_write() IS 'Toma la moneda de la cuenta, valida los decimales y que una transferencia vaya a otra cuenta activa de la misma moneda.';
COMMENT ON FUNCTION finance.apply_transaction_to_balances() IS 'Ajusta el saldo de las cuentas con cada alta, edición o borrado de un movimiento.';
COMMENT ON FUNCTION goals.goals_before_write() IS 'La moneda de la meta debe estar activa.';
COMMENT ON FUNCTION goals.apply_contribution() IS 'Suma o resta cada aporte al monto ahorrado de la meta.';
COMMENT ON FUNCTION ai.routes_check_kind() IS 'El modelo debe ser del tipo que pide la tarea (no se pone un LLM a transcribir).';
COMMENT ON FUNCTION ai.calls_before_insert() IS 'Calcula el costo de la llamada con el precio del modelo; una llamada que no llegó al proveedor cuesta 0.';
COMMENT ON FUNCTION ai.calls_after_insert() IS 'Suma la llamada al dictado (intentos, tokens, costo, modelo que respondió) y al uso mensual del usuario.';
COMMENT ON FUNCTION ops.logs_append_only() IS 'Impide editar o borrar un log.';
COMMENT ON FUNCTION ops.incidents_on_change() IS 'Al cambiar estado o severidad, completa las fechas y escribe la línea de tiempo.';
COMMENT ON FUNCTION ops.incidents_after_insert() IS 'Escribe la primera entrada de la línea de tiempo.';

-- Listas fijas
COMMENT ON TYPE finance.period_type IS 'weekly (semanal), semi_monthly (quincenal: dos por mes, desde el día d y el d + 15) o monthly (mensual).';
COMMENT ON TYPE finance.frequency IS 'Cada cuánto se repite un recurrente: weekly (semana), biweekly (2 semanas), monthly (mes) o yearly (año).';
COMMENT ON TYPE finance.transaction_source IS 'Cómo se registró un movimiento: manual, quick_add, voice, scan, recurring, onboarding o adjustment.';

-- Vistas
COMMENT ON VIEW billing.price_catalog IS 'Pantalla de planes: precio mensual, anual, precio por mes pagando el año y porcentaje de ahorro.';
COMMENT ON VIEW ai.provider_health_24h IS 'Salud de cada proveedor de IA en las últimas 24 horas: llamadas, fallas, tasa de error, veces que salvó como respaldo, latencia p50/p95 y costo.';
COMMENT ON VIEW ai.monthly_cost_by_model IS 'Costo real de IA por modelo, tarea y mes, incluidas las llamadas fallidas.';
COMMENT ON VIEW ai.monthly_cost_by_user IS 'Dictados por usuario y mes: cuántos, confirmados, con respaldo, confianza promedio y costo.';
COMMENT ON VIEW ops.open_incidents IS 'Tablero del equipo: incidentes abiertos por severidad y última vez que ocurrieron.';
COMMENT ON VIEW ops.error_summary_24h IS 'Errores y advertencias de las últimas 24 horas agrupados por código, con usuarios afectados.';

-- Funciones que usa la API o los workers
COMMENT ON FUNCTION catalog.assert_currency_active(char) IS 'Falla con currency_unavailable si la moneda no existe o está desactivada.';
COMMENT ON FUNCTION billing.resource_usage(uuid, text) IS 'Cuántos recursos vivos tiene el usuario de una funcionalidad: tarjetas, monedas o metas activas.';
COMMENT ON FUNCTION billing.limit_status(uuid, text) IS 'Para mostrar "1 de 1 tarjetas": límite, usado, restante y si puede agregar otra.';
COMMENT ON FUNCTION finance.recalculate_account_balance(uuid, uuid) IS 'Recalcula el saldo de una cuenta desde cero (conciliación nocturna o soporte) y lo devuelve.';
COMMENT ON FUNCTION ai.route(text) IS 'Orden vigente de proveedores de una tarea (activos y no retirados). El worker lo lee y puede cachearlo 60 s.';
