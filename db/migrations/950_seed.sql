-- =============================================================================
-- MoneyMap · 950 · datos iniciales
-- Monedas, tipos de cuenta, grupos del Money Flow, categorías iniciales, catálogo de
-- funcionalidades, planes, tipos de notificación, proveedores de IA y primeras
-- particiones mensuales. Idempotente.
-- =============================================================================

-- Términos y política de privacidad vigentes (las URL son PROVISIONALES)
INSERT INTO iam.terms_versions (version, terms_url, privacy_url, is_current) VALUES
  ('2026-10', 'https://moneymap.app/legal/terminos', 'https://moneymap.app/legal/privacidad', true)
ON CONFLICT (version) DO NOTHING;

-- Monedas (ISO 4217). Para ofrecer otra: INSERT con is_active = true.
-- Para dejar de ofrecer una: is_active = false (los datos existentes se conservan).
INSERT INTO catalog.currencies (code, name, symbol, decimals, sort_order) VALUES
  ('BOB', 'Boliviano',              'Bs',  2, 10),
  ('USD', 'Dólar estadounidense',   '$',   2, 20),
  ('EUR', 'Euro',                   '€',   2, 30),
  ('GBP', 'Libra esterlina',        '£',   2, 40),
  ('ARS', 'Peso argentino',         '$',   2, 50),
  ('BRL', 'Real brasileño',         'R$',  2, 50),
  ('CLP', 'Peso chileno',           '$',   0, 50),
  ('COP', 'Peso colombiano',        '$',   2, 50),
  ('MXN', 'Peso mexicano',          '$',   2, 50),
  ('PEN', 'Sol peruano',            'S/',  2, 50),
  ('PYG', 'Guaraní paraguayo',      '₲',   0, 50),
  ('UYU', 'Peso uruguayo',          '$U',  2, 50)
ON CONFLICT (code) DO NOTHING;

-- Tipos de cuenta: efectivo y tarjeta (sin distinguir débito de crédito).
-- is_card cuenta para el límite de tarjetas y responde "¿pagó con tarjeta?".
INSERT INTO catalog.account_types (code, names, icon, is_card, sort_order) VALUES
  ('cash', '{"es": "Efectivo", "en": "Cash"}', 'payments',    false, 10),
  ('card', '{"es": "Tarjeta", "en": "Card"}',  'credit_card', true,  20)
ON CONFLICT (code) DO NOTHING;

-- Países: los de las monedas del catálogo. Agregar otro es un INSERT.
INSERT INTO catalog.countries (code, name, currency, sort_order) VALUES
  ('BO', 'Bolivia',         'BOB', 10),
  ('AR', 'Argentina',       'ARS', 20),
  ('BR', 'Brasil',          'BRL', 20),
  ('CL', 'Chile',           'CLP', 20),
  ('CO', 'Colombia',        'COP', 20),
  ('MX', 'México',          'MXN', 20),
  ('PE', 'Perú',            'PEN', 20),
  ('PY', 'Paraguay',        'PYG', 20),
  ('UY', 'Uruguay',         'UYU', 20),
  ('US', 'Estados Unidos',  'USD', 30),
  ('ES', 'España',          'EUR', 30),
  ('GB', 'Reino Unido',     'GBP', 30)
ON CONFLICT (code) DO NOTHING;

-- Instituciones financieras que emiten tarjetas. PROVISIONAL: lista inicial
-- para revisar con el equipo (bancos de Bolivia regulados por ASFI y los
-- principales de los países vecinos). Agregar o desactivar una es un INSERT o UPDATE.
INSERT INTO catalog.financial_institutions (code, country_code, name, short_name, kind, sort_order) VALUES
  -- Bolivia
  ('bo.bnb',        'BO', 'Banco Nacional de Bolivia',              'BNB',            'bank',         10),
  ('bo.bmsc',       'BO', 'Banco Mercantil Santa Cruz',             'Mercantil',      'bank',         10),
  ('bo.union',      'BO', 'Banco Unión',                            'Banco Unión',    'bank',         10),
  ('bo.bcp',        'BO', 'Banco de Crédito de Bolivia',            'BCP',            'bank',         10),
  ('bo.bisa',       'BO', 'Banco BISA',                             'BISA',           'bank',         10),
  ('bo.economico',  'BO', 'Banco Económico',                        'Económico',      'bank',         20),
  ('bo.ganadero',   'BO', 'Banco Ganadero',                         'Ganadero',       'bank',         20),
  ('bo.sol',        'BO', 'Banco Solidario',                        'BancoSol',       'microfinance', 20),
  ('bo.fie',        'BO', 'Banco para el Fomento a Iniciativas Económicas', 'Banco FIE', 'microfinance', 20),
  ('bo.fortaleza',  'BO', 'Banco Fortaleza',                        'Fortaleza',      'bank',         20),
  ('bo.prodem',     'BO', 'Banco Prodem',                           'Prodem',         'microfinance', 30),
  ('bo.ecofuturo',  'BO', 'Banco Pyme Ecofuturo',                   'Ecofuturo',      'microfinance', 30),
  ('bo.comunidad',  'BO', 'Banco Pyme de la Comunidad',             'Banco Comunidad','microfinance', 30),
  -- Argentina
  ('ar.nacion',     'AR', 'Banco de la Nación Argentina',           'Banco Nación',   'bank',    10),
  ('ar.galicia',    'AR', 'Banco Galicia',                          'Galicia',        'bank',    10),
  ('ar.santander',  'AR', 'Banco Santander Argentina',              'Santander',      'bank',    10),
  ('ar.bbva',       'AR', 'BBVA Argentina',                         'BBVA',           'bank',    10),
  ('ar.macro',      'AR', 'Banco Macro',                            'Macro',          'bank',    10),
  ('ar.provincia',  'AR', 'Banco de la Provincia de Buenos Aires',  'Banco Provincia','bank',    20),
  ('ar.mercadopago','AR', 'Mercado Pago',                           'Mercado Pago',   'fintech', 20),
  ('ar.uala',       'AR', 'Ualá',                                   'Ualá',           'fintech', 20),
  ('ar.brubank',    'AR', 'Brubank',                                'Brubank',        'bank',    30),
  -- Brasil
  ('br.itau',       'BR', 'Itaú Unibanco',                          'Itaú',           'bank',    10),
  ('br.bb',         'BR', 'Banco do Brasil',                        'Banco do Brasil','bank',    10),
  ('br.bradesco',   'BR', 'Banco Bradesco',                         'Bradesco',       'bank',    10),
  ('br.caixa',      'BR', 'Caixa Econômica Federal',                'Caixa',          'bank',    10),
  ('br.santander',  'BR', 'Banco Santander Brasil',                 'Santander',      'bank',    10),
  ('br.nubank',     'BR', 'Nu Pagamentos',                          'Nubank',         'fintech', 20),
  ('br.inter',      'BR', 'Banco Inter',                            'Inter',          'bank',    20),
  -- Chile
  ('cl.bancochile', 'CL', 'Banco de Chile',                         'Banco de Chile', 'bank',    10),
  ('cl.estado',     'CL', 'BancoEstado',                            'BancoEstado',    'bank',    10),
  ('cl.santander',  'CL', 'Banco Santander Chile',                  'Santander',      'bank',    10),
  ('cl.bci',        'CL', 'Banco de Crédito e Inversiones',         'BCI',            'bank',    10),
  ('cl.scotiabank', 'CL', 'Scotiabank Chile',                       'Scotiabank',     'bank',    20),
  ('cl.itau',       'CL', 'Banco Itaú Chile',                       'Itaú',           'bank',    20),
  -- Colombia
  ('co.bancolombia','CO', 'Bancolombia',                            'Bancolombia',    'bank',    10),
  ('co.bogota',     'CO', 'Banco de Bogotá',                        'Banco de Bogotá','bank',    10),
  ('co.davivienda', 'CO', 'Davivienda',                             'Davivienda',     'bank',    10),
  ('co.bbva',       'CO', 'BBVA Colombia',                          'BBVA',           'bank',    20),
  ('co.nequi',      'CO', 'Nequi',                                  'Nequi',          'fintech', 20),
  ('co.nu',         'CO', 'Nu Colombia',                            'Nu',             'fintech', 20),
  -- México
  ('mx.bbva',       'MX', 'BBVA México',                            'BBVA',           'bank',    10),
  ('mx.banorte',    'MX', 'Banorte',                                'Banorte',        'bank',    10),
  ('mx.santander',  'MX', 'Banco Santander México',                 'Santander',      'bank',    10),
  ('mx.banamex',    'MX', 'Banamex',                                'Banamex',        'bank',    10),
  ('mx.hsbc',       'MX', 'HSBC México',                            'HSBC',           'bank',    20),
  ('mx.nu',         'MX', 'Nu México',                              'Nu',             'fintech', 20),
  -- Perú
  ('pe.bcp',        'PE', 'Banco de Crédito del Perú',              'BCP',            'bank',    10),
  ('pe.bbva',       'PE', 'BBVA Perú',                              'BBVA',           'bank',    10),
  ('pe.interbank',  'PE', 'Interbank',                              'Interbank',      'bank',    10),
  ('pe.scotiabank', 'PE', 'Scotiabank Perú',                        'Scotiabank',     'bank',    10),
  ('pe.nacion',     'PE', 'Banco de la Nación',                     'Banco de la Nación', 'bank', 20),
  -- Paraguay
  ('py.itau',       'PY', 'Banco Itaú Paraguay',                    'Itaú',           'bank',    10),
  ('py.continental','PY', 'Banco Continental',                      'Continental',    'bank',    10),
  ('py.basa',       'PY', 'Banco Basa',                             'Basa',           'bank',    10),
  ('py.ueno',       'PY', 'ueno bank',                              'ueno',           'bank',    20),
  ('py.bnf',        'PY', 'Banco Nacional de Fomento',              'BNF',            'bank',    20),
  -- Uruguay
  ('uy.brou',       'UY', 'Banco de la República Oriental del Uruguay', 'BROU',       'bank',    10),
  ('uy.itau',       'UY', 'Banco Itaú Uruguay',                     'Itaú',           'bank',    10),
  ('uy.santander',  'UY', 'Banco Santander Uruguay',                'Santander',      'bank',    10),
  ('uy.bbva',       'UY', 'BBVA Uruguay',                           'BBVA',           'bank',    20),
  ('uy.scotiabank', 'UY', 'Scotiabank Uruguay',                     'Scotiabank',     'bank',    20)
ON CONFLICT (code) DO NOTHING;

-- Categorías iniciales. Cada gasto lleva su grupo del Money Flow; los ingresos, ninguno.
INSERT INTO catalog.category_templates (key, kind, flow_group, names, icon, color, sort_order) VALUES
  -- Ingresos (FTR-031)
  ('salary',            'income',  NULL,        '{"es": "Salario", "en": "Salary"}',                          'payments',          '#16A34A', 10),
  ('freelance',         'income',  NULL,        '{"es": "Trabajo independiente", "en": "Freelance"}',         'work',              '#059669', 20),
  ('business',          'income',  NULL,        '{"es": "Emprendimiento", "en": "Business"}',                 'storefront',        '#0D9488', 30),
  ('family_support',    'income',  NULL,        '{"es": "Mesada familiar", "en": "Family support"}',          'family_restroom',   '#0891B2', 40),
  ('investment_income', 'income',  NULL,        '{"es": "Inversiones e intereses", "en": "Investments"}',     'trending_up',       '#2563EB', 50),
  ('other_income',      'income',  NULL,        '{"es": "Otros ingresos", "en": "Other income"}',             'add_card',          '#64748B', 90),
  -- Necesidades
  ('housing',           'expense', 'needs',     '{"es": "Vivienda y alquiler", "en": "Housing"}',             'home',              '#7C3AED', 10),
  ('utilities',         'expense', 'needs',     '{"es": "Servicios básicos", "en": "Utilities"}',             'bolt',              '#6D28D9', 20),
  ('groceries',         'expense', 'needs',     '{"es": "Supermercado", "en": "Groceries"}',                  'shopping_cart',     '#4F46E5', 30),
  ('transport',         'expense', 'needs',     '{"es": "Transporte", "en": "Transport"}',                    'directions_bus',    '#2563EB', 40),
  ('health',            'expense', 'needs',     '{"es": "Salud", "en": "Health"}',                            'medical_services',  '#DC2626', 50),
  ('education',         'expense', 'needs',     '{"es": "Educación", "en": "Education"}',                     'school',            '#0284C7', 60),
  ('debt_payments',     'expense', 'needs',     '{"es": "Deudas y créditos", "en": "Debt payments"}',         'credit_card',       '#B91C1C', 70),
  ('insurance',         'expense', 'needs',     '{"es": "Seguros", "en": "Insurance"}',                       'shield',            '#475569', 80),
  -- Estilo de vida
  ('restaurants',       'expense', 'lifestyle', '{"es": "Restaurantes", "en": "Restaurants"}',                'restaurant',        '#EA580C', 10),
  ('food_delivery',     'expense', 'lifestyle', '{"es": "Delivery de comida", "en": "Food delivery"}',        'delivery_dining',   '#F97316', 20),
  ('entertainment',     'expense', 'lifestyle', '{"es": "Entretenimiento", "en": "Entertainment"}',           'movie',             '#DB2777', 30),
  ('subscriptions',     'expense', 'lifestyle', '{"es": "Suscripciones", "en": "Subscriptions"}',             'subscriptions',     '#C026D3', 40),
  ('shopping',          'expense', 'lifestyle', '{"es": "Compras", "en": "Shopping"}',                        'shopping_bag',      '#E11D48', 50),
  ('travel',            'expense', 'lifestyle', '{"es": "Viajes", "en": "Travel"}',                           'flight',            '#0EA5E9', 60),
  ('personal_care',     'expense', 'lifestyle', '{"es": "Cuidado personal", "en": "Personal care"}',          'spa',               '#EC4899', 70),
  ('gifts',             'expense', 'lifestyle', '{"es": "Regalos", "en": "Gifts"}',                           'redeem',            '#F43F5E', 80),
  ('other_expense',     'expense', 'lifestyle', '{"es": "Otros gastos", "en": "Other expenses"}',             'more_horiz',        '#64748B', 90)
ON CONFLICT (key) DO NOTHING;

-- Funcionalidades que un plan puede habilitar o limitar
INSERT INTO billing.features (key, description, value_type, limit_period) VALUES
  ('finance.cards',                 'Tarjetas activas',                           'limit',   'total'),
  ('finance.currencies',            'Monedas distintas entre las cuentas activas', 'limit',   'total'),
  ('goals.active',                  'Metas activas',                              'limit',   'total'),
  ('ai.voice_entries',              'Registros por voz al mes',                   'limit',   'month'),
  ('planning.affordability_checks', 'Consultas de Can I Afford It? al mes',       'limit',   'month'),
  ('reports.money_story',           'Monthly Money Story',                        'boolean', NULL),
  ('notify.push',                   'Notificaciones push',                        'boolean', NULL)
ON CONFLICT (key) DO NOTHING;

-- Planes. PROVISIONAL: nombres, precios y límites están por definir (PRD, preguntas abiertas).
-- Los precios mensual y anual de cada plan de pago se cargan en billing.plan_prices
-- cuando el equipo los defina; hasta entonces los planes de pago quedan inactivos.
INSERT INTO billing.plans (code, name, tier, is_public, is_active) VALUES
  ('free',   'Gratuito',       0, true,  true),
  ('paid_1', 'Plan de pago 1', 1, false, false),
  ('paid_2', 'Plan de pago 2', 2, false, false),
  ('paid_3', 'Plan de pago 3', 3, false, false)
ON CONFLICT (code) DO NOTHING;

-- Límites PROVISIONALES (NULL = ilimitado). El gratuito permite 1 tarjeta y
-- 1 moneda (Bs o USD, la que elija); los planes de pago, sin límite.
-- Cambiar un número es un UPDATE, sin desplegar código.
INSERT INTO billing.plan_features (plan_id, feature_key, is_enabled, limit_value)
SELECT p.id, v.feature_key, v.is_enabled, v.limit_value
FROM billing.plans p
JOIN (VALUES
  ('free',   'finance.cards',                 true,  1),
  ('free',   'finance.currencies',            true,  1),
  ('free',   'goals.active',                  true,  2),
  ('free',   'ai.voice_entries',              true,  30),
  ('free',   'planning.affordability_checks', true,  10),
  ('free',   'reports.money_story',           true,  NULL),
  ('free',   'notify.push',                   true,  NULL),
  ('paid_1', 'finance.cards',                 true,  NULL),
  ('paid_1', 'finance.currencies',            true,  NULL),
  ('paid_1', 'goals.active',                  true,  NULL),
  ('paid_1', 'ai.voice_entries',              true,  NULL),
  ('paid_1', 'planning.affordability_checks', true,  NULL),
  ('paid_1', 'reports.money_story',           true,  NULL),
  ('paid_1', 'notify.push',                   true,  NULL),
  ('paid_2', 'finance.cards',                 true,  NULL),
  ('paid_2', 'finance.currencies',            true,  NULL),
  ('paid_2', 'goals.active',                  true,  NULL),
  ('paid_2', 'ai.voice_entries',              true,  NULL),
  ('paid_2', 'planning.affordability_checks', true,  NULL),
  ('paid_2', 'reports.money_story',           true,  NULL),
  ('paid_2', 'notify.push',                   true,  NULL),
  ('paid_3', 'finance.cards',                 true,  NULL),
  ('paid_3', 'finance.currencies',            true,  NULL),
  ('paid_3', 'goals.active',                  true,  NULL),
  ('paid_3', 'ai.voice_entries',              true,  NULL),
  ('paid_3', 'planning.affordability_checks', true,  NULL),
  ('paid_3', 'reports.money_story',           true,  NULL),
  ('paid_3', 'notify.push',                   true,  NULL)
) AS v (plan_code, feature_key, is_enabled, limit_value) ON v.plan_code = p.code
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Tipos de aviso de la V1 (FTR-023)
INSERT INTO notify.notification_types (key, description, default_enabled, is_transactional) VALUES
  ('money_story.ready',   'Tu Monthly Money Story está lista',                  true, false),
  ('recurring.due_soon',  'Se acerca un pago o ingreso recurrente',             true, false),
  ('goal.milestone',      'Te falta poco para el próximo hito de una meta',     true, false),
  ('goal.achieved',       'Alcanzaste una meta',                                true, false),
  ('security.new_login',  'Nuevo inicio de sesión en tu cuenta',                true, true),
  ('subscription.status', 'Cambios en tu suscripción',                          true, true),
  ('subscription.renewal_failed', 'No pudimos cobrar tu suscripción',           true, true),
  ('subscription.ending',  'Tu plan de pago termina pronto',                    true, false),
  ('subscription.reverted_to_free', 'Tu cuenta volvió al plan gratuito',       true, true)
ON CONFLICT (key) DO NOTHING;

-- IA: tareas, modelos y orden de proveedores (FTR-007)
-- Precios oficiales consultados el 13-10-2026, en USD. El orden de las rutas es
-- PROVISIONAL hasta que la prueba de concepto elija el principal:
--   SELECT ai.set_route_order('voice.extract', ARRAY['…principal…', '…respaldo…'], 'motivo');
INSERT INTO ai.tasks (key, model_kind, description) VALUES
  ('voice.transcribe', 'stt', 'Convierte el audio del dictado en texto'),
  ('voice.extract',    'llm', 'Convierte la frase en un movimiento: tipo, monto, moneda, categoría, cuenta, descripción y fecha')
ON CONFLICT (key) DO NOTHING;

INSERT INTO ai.models (code, provider, model, kind, price_per_minute_usd, min_billed_seconds,
                       input_per_mtok_usd, cached_input_per_mtok_usd, output_per_mtok_usd,
                       is_active, shutdown_on, prices_checked_on, notes) VALUES
  -- Voz a texto
  ('openai.gpt-transcribe',        'openai',   'gpt-transcribe',        'stt', 0.004500,  0, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Reemplazo de whisper-1 en la API de OpenAI. Acepta pistas de palabras (comercios, categorías)'),
  ('groq.whisper-large-v3-turbo',  'groq',     'whisper-large-v3-turbo','stt', 0.000667, 10, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Whisper (modelo abierto de OpenAI) servido por Groq: 0,04 USD por hora; cobra mínimo 10 s por llamada'),
  ('groq.whisper-large-v3',        'groq',     'whisper-large-v3',      'stt', 0.001850, 10, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Whisper large v3 completo en Groq: 0,111 USD por hora; cobra mínimo 10 s'),
  ('deepgram.nova-3',              'deepgram', 'nova-3',                'stt', 0.004300,  0, NULL, NULL, NULL, true,  NULL, '2026-10-13',
   'Audio pregrabado, un idioma. 200 USD de crédito inicial'),
  ('openai.whisper-1',             'openai',   'whisper-1',             'stt', 0.006000,  0, NULL, NULL, NULL, false, '2027-02-26', '2026-10-13',
   'Retirado: OpenAI lo apaga el 26-02-2027 y recomienda gpt-transcribe. Precio histórico'),
  -- LLM para extraer el movimiento
  ('openai.gpt-6-luna',            'openai',   'gpt-6-luna',            'llm', NULL, 0, 0.100000, 0.010000, 0.500000, true, NULL, '2026-10-13',
   'Usar reasoning.effort = none y salidas estructuradas (JSON con esquema)'),
  ('deepseek.deepseek-flash',      'deepseek', 'deepseek-flash',        'llm', NULL, 0, 0.300000, 0.006000, 1.200000, true, NULL, '2026-10-13',
   'Precio en hora pico (01-04 y 06-10 UTC, lunes a viernes); fuera de pico cuesta la mitad. Usar modo sin razonamiento. Datos procesados en China'),
  ('anthropic.claude-haiku-5-5',   'anthropic','claude-haiku-5-5',      'llm', NULL, 0, 0.100000, 0.010000, 0.500000, true, NULL, '2026-10-13',
   'Precio para prompts de hasta 100.000 tokens. Anthropic no ofrece voz a texto'),
  ('google.gemini-3.1-flash-lite', 'google',   'gemini-3.1-flash-lite', 'llm', NULL, 0, 0.250000, NULL,     1.500000, true, NULL, '2026-10-13',
   'Corre en Google Cloud, la misma nube del backend')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ai.routes (task, position, model_code, timeout_ms, max_retries) VALUES
  ('voice.transcribe', 1, 'openai.gpt-transcribe',       10000, 1),
  ('voice.transcribe', 2, 'groq.whisper-large-v3-turbo', 10000, 1),
  ('voice.transcribe', 3, 'deepgram.nova-3',             10000, 0),
  ('voice.extract',    1, 'openai.gpt-6-luna',            6000, 1),
  ('voice.extract',    2, 'deepseek.deepseek-flash',      6000, 1),
  ('voice.extract',    3, 'anthropic.claude-haiku-5-5',   6000, 0)
ON CONFLICT DO NOTHING;

-- Primeras particiones mensuales (luego las crea un job mensual de Celery Beat)
SELECT core.ensure_monthly_partitions('core.audit_log',       current_date, 4);
SELECT core.ensure_monthly_partitions('notify.notifications', current_date, 4);
SELECT core.ensure_monthly_partitions('ai.voice_entries',     current_date, 4);
SELECT core.ensure_monthly_partitions('ai.calls',             current_date, 4);
SELECT core.ensure_monthly_partitions('ops.logs',             current_date, 4);

-- Las particiones nuevas solo se acceden a través de la tabla padre
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS part
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('core', 'notify', 'ai', 'ops') AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format('REVOKE ALL ON %s FROM moneymap_app, moneymap_worker, moneymap_ops', r.part);
  END LOOP;
END $$;
