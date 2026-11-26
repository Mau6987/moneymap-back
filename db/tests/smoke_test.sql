-- =============================================================================
-- MoneyMap · pruebas de humo del esquema
-- Uso: psql -d <base> -v ON_ERROR_STOP=1 -f tests/smoke_test.sql
-- Todo corre dentro de una transacción y se revierte al final.
-- Cada bloque lanza una excepción si la regla no se cumple.
-- Los precios usados aquí son valores de PRUEBA.
-- =============================================================================
\set ON_ERROR_STOP 1
\set QUIET 1
BEGIN;

\set ana      '''00000000-0000-7000-8000-00000000000a'''
\set beto     '''00000000-0000-7000-8000-00000000000b'''
\set cash_a   '''00000000-0000-7000-8000-00000000ac01'''
\set usd_a    '''00000000-0000-7000-8000-00000000ac02'''
\set bob_a    '''00000000-0000-7000-8000-00000000ac03'''
\set card_a   '''00000000-0000-7000-8000-00000000ac04'''
\set cash_b   '''00000000-0000-7000-8000-00000000bc01'''
\set tx1      '''00000000-0000-7000-8000-000000000101'''
\set tx2      '''00000000-0000-7000-8000-000000000102'''
\set tx3      '''00000000-0000-7000-8000-000000000103'''
\set goal_a   '''00000000-0000-7000-8000-00000000a0a1'''

-- 1. Identidad -------------------------------------------------------------------
DO $$ BEGIN
  IF substring(core.uuid_v7()::text, 15, 1) <> '7' THEN RAISE EXCEPTION 'uuid_v7 no genera versión 7'; END IF;
  RAISE NOTICE 'OK 1  uuid_v7 genera UUID versión 7';
END $$;

INSERT INTO iam.users (id, email, first_name, last_name, terms_version) VALUES
  (:ana,  'ana@example.com',  'Ana',  'Rojas', '2026-10'),
  (:beto, 'beto@example.com', 'Beto', 'Vaca',  '2026-10');

DO $$ BEGIN
  INSERT INTO iam.users (email, first_name, last_name, terms_version) VALUES (' ANA@example.com ', 'Otra', 'Ana', '2026-10');
  RAISE EXCEPTION 'FALLO: email duplicado con otras mayúsculas';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'OK 3  el email es único sin distinguir mayúsculas ni espacios alrededor';
END $$;

-- Perfil (spec 001): se guarda limpio, con los términos vigentes y preferencias por defecto
DO $$ DECLARE u record; p record; h text; BEGIN
  UPDATE iam.users
     SET first_name = '  María   José ', display_name = '  ',
         country_code = 'bo', city = ' La Paz ', occupation = 'student'
   WHERE id = '00000000-0000-7000-8000-00000000000a'
  RETURNING * INTO u;
  SELECT * INTO p FROM iam.user_preferences WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  IF u.first_name <> 'María José' OR u.display_name <> 'María José'
  OR u.country_code <> 'BO' OR u.city <> 'La Paz' OR u.terms_accepted_at IS NULL
  OR p.theme <> 'system' OR p.hide_amounts OR p.week_starts_on <> 1 OR p.accent_color IS NOT NULL THEN
    RAISE EXCEPTION 'perfil: %, %', row_to_json(u), row_to_json(p);
  END IF;
  BEGIN
    UPDATE iam.users SET occupation = 'astronaut' WHERE id = '00000000-0000-7000-8000-00000000000a';
    RAISE EXCEPTION 'FALLO: ocupación inválida';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO iam.terms_versions (version, terms_url, privacy_url) VALUES ('2025-01', 'x', 'y');
    INSERT INTO iam.users (email, first_name, last_name, terms_version)
    VALUES ('vieja@example.com', 'Vieja', 'Versión', '2025-01');
    RAISE EXCEPTION 'FALLO: aceptó términos viejos';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h = PG_EXCEPTION_HINT;
  END;
  IF h IS DISTINCT FROM 'terms_outdated' THEN RAISE EXCEPTION 'términos: hint %', h; END IF;
  UPDATE iam.users SET first_name = 'Ana', display_name = 'Ana' WHERE id = '00000000-0000-7000-8000-00000000000a';
  RAISE NOTICE 'OK 3b perfil limpio (nombre, teléfono E.164, país), ocupación de la lista, términos vigentes y preferencias por defecto';
END $$;

-- 2. Alta financiera: Ana con moneda principal Bs, Beto USD -------------------------------
DO $$ DECLARE n int; BEGIN
  n := finance.setup_user('00000000-0000-7000-8000-00000000000a', 'BOB');
  PERFORM finance.setup_user('00000000-0000-7000-8000-00000000000b', 'USD', 'en');
  IF n <> 23 OR finance.setup_user('00000000-0000-7000-8000-00000000000a', 'BOB') <> 23 THEN
    RAISE EXCEPTION 'setup_user creó % categorías o no es idempotente', n;
  END IF;
  RAISE NOTICE 'OK 4  setup_user copia 23 categorías iniciales (sin subcategorías) y es idempotente';
END $$;

-- Planes de pago con precios de PRUEBA (valores ficticios, solo para el test)
\set p1m   '''00000000-0000-7000-8000-00000000f101'''
\set p1y   '''00000000-0000-7000-8000-00000000f102'''
\set p2m   '''00000000-0000-7000-8000-00000000f201'''
\set sub_b '''00000000-0000-7000-8000-00000000e00b'''
\set sub_a '''00000000-0000-7000-8000-00000000e00a'''
\set carla '''00000000-0000-7000-8000-00000000000c'''

UPDATE billing.plans SET is_active = true, is_public = true WHERE code IN ('paid_1', 'paid_2');
INSERT INTO billing.plan_prices (id, plan_id, billing_period, currency, amount, trial_days, app_store_product_id, play_store_product_id)
SELECT v.id::uuid, p.id, v.period, 'USD', v.amount, v.trial, v.apple, v.google
FROM billing.plans p
JOIN (VALUES
  ('00000000-0000-7000-8000-00000000f101', 'paid_1', 'month',  4.99, 7, 'mm.plus.monthly',  'mm_plus:monthly'),
  ('00000000-0000-7000-8000-00000000f102', 'paid_1', 'year',  49.99, 7, 'mm.plus.yearly',   'mm_plus:yearly'),
  ('00000000-0000-7000-8000-00000000f201', 'paid_2', 'month',  9.99, 0, 'mm.pro.monthly',   'mm_pro:monthly')
) AS v (id, plan_code, period, amount, trial, apple, google) ON v.plan_code = p.code;
\set sub_a0 '''00000000-0000-7000-8000-00000000e0a0'''

-- Ana tiene un plan de pago (promoción interna) cuando agrega sus tarjetas
SELECT set_config('app.change_source', 'admin', true) \g /dev/null
INSERT INTO billing.subscriptions (id, user_id, plan_id, plan_price_id, billing_period, status, provider, current_period_end)
SELECT :sub_a0, :ana, p.id, :p1m, 'month', 'active', 'internal', now() + INTERVAL '1 month'
FROM billing.plans p WHERE p.code = 'paid_1';

INSERT INTO finance.accounts (id, user_id, name, type, currency, opening_balance) VALUES
  (:cash_a, :ana,  'Efectivo',        'cash',        'BOB',  500),
  (:usd_a,  :ana,  'Tarjeta BNB USD', 'card',        'USD', 1000),
  (:bob_a,  :ana,  'Tarjeta BNB Bs',  'card',        'BOB', 2000),
  (:card_a, :ana,  'Visa Mercantil',  'card',        'BOB',    0),
  (:cash_b, :beto, 'Cash',            'cash',        'USD',  200);
-- Datos de cada tarjeta (1 a 1 con su cuenta)
INSERT INTO finance.cards (account_id, user_id, institution_code, last4) VALUES
  (:usd_a,  :ana, 'bo.bnb',  '1234'),
  (:bob_a,  :ana, 'bo.bnb',  '5678'),
  (:card_a, :ana, 'bo.bmsc', '9012');

-- Termina la promoción: Ana vuelve al plan gratuito (1 tarjeta, 1 moneda) y conserva sus 3 tarjetas y 2 monedas
UPDATE billing.subscriptions SET status = 'expired' WHERE id = :sub_a0;
SELECT set_config('app.change_source', '', true) \g /dev/null

DO $$ DECLARE n int := 0; BEGIN
  BEGIN   -- el efectivo no tiene datos de tarjeta
    INSERT INTO finance.cards (account_id, user_id, institution_code)
    VALUES ('00000000-0000-7000-8000-00000000ac01', '00000000-0000-7000-8000-00000000000a', 'bo.bnb');
  EXCEPTION WHEN foreign_key_violation THEN n := n + 1;
  END;
  BEGIN   -- el banco debe estar en el catálogo
    UPDATE finance.cards SET institution_code = 'bo.no_existe' WHERE account_id = '00000000-0000-7000-8000-00000000ac02';
  EXCEPTION WHEN foreign_key_violation THEN n := n + 1;
  END;
  IF n <> 2 OR (SELECT count(*) FROM catalog.financial_institutions WHERE country_code = 'BO') < 10 THEN
    RAISE EXCEPTION 'datos de tarjeta: % de 2 rechazos', n;
  END IF;
  RAISE NOTICE 'OK 5  una tarjeta guarda su banco del catálogo (BNB, Mercantil…) y sus últimos 4; el efectivo no tiene datos de tarjeta';
END $$;

-- 3. Movimientos en la moneda de la cuenta ------------------------------------------------
INSERT INTO finance.transactions (id, user_id, kind, account_id, category_id, amount, currency, occurred_on, description, source)
SELECT :tx1, :ana, 'expense', :cash_a, c.id, 35, 'BOB', current_date, 'Almuerzo', 'voice'
FROM finance.categories c WHERE c.user_id = :ana AND c.template_key = 'restaurants';
-- Sin moneda: toma la de la cuenta
INSERT INTO finance.transactions (id, user_id, kind, account_id, category_id, amount, occurred_on, description)
SELECT :tx2, :ana, 'income', :cash_a, c.id, 3000, current_date, 'Sueldo'
FROM finance.categories c WHERE c.user_id = :ana AND c.template_key = 'salary';

DO $$ DECLARE t record; BEGIN
  SELECT * INTO t FROM finance.transactions WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND id = '00000000-0000-7000-8000-000000000101';
  IF t.currency <> 'BOB'
  OR (SELECT currency FROM finance.transactions WHERE id = '00000000-0000-7000-8000-000000000102') <> 'BOB'
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01') <> 3465 THEN
    RAISE EXCEPTION 'gasto en Bs: %', row_to_json(t);
  END IF;
  RAISE NOTICE 'OK 6  gasto en Bs desde efectivo, con la moneda de la cuenta por defecto; 500 − 35 + 3000 = 3465';
END $$;

UPDATE finance.transactions SET amount = 50 WHERE user_id = :ana AND id = :tx1;
UPDATE finance.transactions SET deleted_at = now() WHERE user_id = :ana AND id = :tx2;
DO $$ BEGIN
  IF (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01') <> 450 THEN
    RAISE EXCEPTION 'saldo tras editar y borrar incorrecto';
  END IF;
  RAISE NOTICE 'OK 7  editar el gasto a 50 y borrar el ingreso deja 450';
END $$;

-- 4. Tarjetas: cada una en su moneda ---------------------------------------------------------
-- (Ana ya está en el plan gratuito: sus tarjetas se siguen usando)
INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
SELECT :ana, 'expense', :bob_a, c.id, 69.6, current_date, 'Amazon'
FROM finance.categories c WHERE c.user_id = :ana AND c.template_key = 'shopping';

DO $$ DECLARE t record; BEGIN
  SELECT * INTO t FROM finance.transactions WHERE description = 'Amazon';
  IF t.currency <> 'BOB'
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac03') <> 1930.4 THEN
    RAISE EXCEPTION 'gasto con débito: %', row_to_json(t);
  END IF;
  RAISE NOTICE 'OK 8  69,60 Bs con la tarjeta en Bs';
END $$;

-- BUG-024 (migración 0025): un gasto que pasa el saldo de la cuenta se rechaza.
DO $$ BEGIN
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac04', c.id, 105,
           current_date, 'Netflix'
    FROM finance.categories c
    WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'subscriptions';
    RAISE EXCEPTION 'un gasto mayor que el saldo de la tarjeta debió rechazarse';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE 'OK 9a un gasto de 105 Bs en la Visa con 0 Bs se rechaza (account_insufficient)';
  END;
END $$;

-- Netflix ya cobrado antes de esa regla: el resto de las pruebas parte de la tarjeta en −105.
ALTER TABLE finance.transactions DISABLE TRIGGER transactions_check_funds;
INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
SELECT :ana, 'expense', :card_a, c.id, 105, current_date, 'Netflix'
FROM finance.categories c WHERE c.user_id = :ana AND c.template_key = 'subscriptions';
ALTER TABLE finance.transactions ENABLE TRIGGER transactions_check_funds;

DO $$ DECLARE b record; BEGIN
  SELECT * INTO b FROM finance.account_balances WHERE account_id = '00000000-0000-7000-8000-00000000ac04';
  IF b.current_balance <> -105 OR NOT b.is_card OR b.institution <> 'Mercantil' OR b.last4 <> '9012' THEN
    RAISE EXCEPTION 'tarjeta: %', row_to_json(b);
  END IF;
  RAISE NOTICE 'OK 9  Netflix por 105 Bs con la Visa Mercantil ••9012: la tarjeta queda en −105 (no se distingue débito de crédito)';
END $$;

-- Un gasto en dólares va a la tarjeta en dólares; en la de Bs se rechaza
INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on, description)
SELECT :ana, 'expense', :usd_a, c.id, 20, 'USD', current_date, 'Hipermaxi'
FROM finance.categories c WHERE c.user_id = :ana AND c.template_key = 'groceries';

DO $$ DECLARE h text; BEGIN
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac03', c.id, 10, 'USD', current_date
    FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'travel';
    RAISE EXCEPTION 'FALLO: se registraron USD en una tarjeta en Bs';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h = PG_EXCEPTION_HINT;
  END;
  IF h IS DISTINCT FROM 'currency_mismatch'
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac02') <> 980
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac03') <> 1930.4 THEN
    RAISE EXCEPTION 'moneda de la cuenta: hint %', h;
  END IF;
  RAISE NOTICE 'OK 10 20 USD con la tarjeta en USD (1.000 → 980); 10 USD en la tarjeta en Bs se rechazan con currency_mismatch';
END $$;

-- Montos con los decimales de la moneda (prueba en una cuenta en CLP que se revierte)
DO $$ DECLARE h text; BEGIN
  BEGIN
    -- Ana está en el plan gratuito (1 moneda): para esta prueba se quita el límite (se revierte)
    UPDATE billing.plan_features SET limit_value = NULL WHERE feature_key = 'finance.currencies';
    -- Con saldo: desde BUG-024 un gasto no pasa el saldo de la cuenta.
    INSERT INTO finance.accounts (id, user_id, name, type, currency, opening_balance)
    VALUES ('00000000-0000-7000-8000-00000000ac09', '00000000-0000-7000-8000-00000000000a', 'Pesos chilenos', 'cash', 'CLP',
            100000);
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac09', c.id, 1000, current_date
    FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'travel';
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac09', c.id, 1000.5, current_date
    FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'travel';
    RAISE EXCEPTION 'FALLO: se aceptaron decimales en CLP';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h = PG_EXCEPTION_HINT;
  END;
  IF h IS DISTINCT FROM 'invalid_amount' THEN RAISE EXCEPTION 'decimales: hint %', h; END IF;
  RAISE NOTICE 'OK 11 CLP no tiene decimales: 1000 pasa y 1000,5 se rechaza con invalid_amount';
END $$;

-- 5. Cuenta por defecto: una sola por usuario ------------------------------------------------
DO $$ DECLARE d0 uuid; d1 uuid; n int; BEGIN
  SELECT id INTO d0 FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND is_default;
  UPDATE finance.accounts SET is_default = true WHERE id = '00000000-0000-7000-8000-00000000ac04';
  SELECT id, count(*) OVER () INTO d1, n FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND is_default;
  UPDATE finance.accounts SET is_default = true WHERE id = '00000000-0000-7000-8000-00000000ac01';
  SET CONSTRAINTS finance.accounts_one_default IMMEDIATE;   -- valida ya la regla de una sola
  SET CONSTRAINTS finance.accounts_one_default DEFERRED;
  IF d0 IS DISTINCT FROM '00000000-0000-7000-8000-00000000ac01' OR d1 IS DISTINCT FROM '00000000-0000-7000-8000-00000000ac04' OR n <> 1
  OR NOT (SELECT is_default FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01') THEN
    RAISE EXCEPTION 'cuenta por defecto: primera %, después % (% marcadas)', d0, d1, n;
  END IF;
  RAISE NOTICE 'OK 12 la primera cuenta queda por defecto; marcar otra desmarca la anterior (siempre una sola)';
END $$;

-- 6. Transferencias en la misma moneda y pago de la tarjeta ---------------------------------
-- Retira 300 Bs del cajero con la tarjeta de débito en Bs
INSERT INTO finance.transactions (id, user_id, kind, account_id, amount, transfer_account_id, occurred_on, description)
VALUES (:tx3, :ana, 'transfer', :bob_a, 300, :cash_a, current_date, 'Cajero');
-- Paga la tarjeta de crédito desde la tarjeta de débito en Bs
INSERT INTO finance.transactions (user_id, kind, account_id, amount, transfer_account_id, occurred_on, description)
VALUES (:ana, 'transfer', :bob_a, 105, :card_a, current_date, 'Pago Visa');

DO $$ DECLARE r record; ok boolean := true; h1 text; h2 text; BEGIN
  FOR r IN SELECT id, current_balance FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000a' LOOP
    ok := ok AND r.current_balance = finance.recalculate_account_balance('00000000-0000-7000-8000-00000000000a', r.id);
  END LOOP;
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, amount, transfer_account_id, occurred_on)
    VALUES ('00000000-0000-7000-8000-00000000000a', 'transfer', '00000000-0000-7000-8000-00000000ac02', 100,
            '00000000-0000-7000-8000-00000000ac01', current_date);
    RAISE EXCEPTION 'FALLO: transfirió de USD a una cuenta en Bs';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h1 = PG_EXCEPTION_HINT;
  END;
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, amount, transfer_account_id, occurred_on)
    VALUES ('00000000-0000-7000-8000-00000000000a', 'transfer', '00000000-0000-7000-8000-00000000ac01', 10,
            '00000000-0000-7000-8000-00000000ac01', current_date);
    RAISE EXCEPTION 'FALLO: transfirió a la misma cuenta';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h2 = PG_EXCEPTION_HINT;
  END;
  IF (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac02') <> 980
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01') <> 750
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac03') <> 1525.4
  OR (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac04') <> 0
  OR h1 IS DISTINCT FROM 'transfer_currency_mismatch' OR h2 IS DISTINCT FROM 'invalid_transfer_target'
  OR NOT ok THEN
    RAISE EXCEPTION 'transferencias o conciliación incorrectas (%, %)', h1, h2;
  END IF;
  RAISE NOTICE 'OK 13 transferencias en Bs: cajero 300 y tarjeta pagada en 0; de USD a Bs o a la misma cuenta se rechazan; la conciliación coincide';
END $$;

-- Beto (principal USD) gasta 10 USD; su cuenta usada ya no cambia de moneda
INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
SELECT :beto, 'expense', :cash_b, c.id, 10, current_date, 'Taxi'
FROM finance.categories c WHERE c.user_id = :beto AND c.template_key = 'transport';

DO $$ DECLARE h text; BEGIN
  BEGIN
    UPDATE finance.accounts SET currency = 'BOB' WHERE id = '00000000-0000-7000-8000-00000000bc01';
    RAISE EXCEPTION 'FALLO: cambió la moneda de una cuenta usada';
  EXCEPTION WHEN check_violation THEN GET STACKED DIAGNOSTICS h = PG_EXCEPTION_HINT;
  END;
  IF h IS DISTINCT FROM 'account_currency_locked' THEN RAISE EXCEPTION 'moneda bloqueada: hint %', h; END IF;
  -- Una cuenta recién creada por error sí se corrige (se revierte al final del bloque)
  BEGIN
    UPDATE billing.plan_features SET limit_value = NULL WHERE feature_key = 'finance.currencies';
    INSERT INTO finance.accounts (id, user_id, name, type, currency)
    VALUES ('00000000-0000-7000-8000-00000000bc09', '00000000-0000-7000-8000-00000000000b', 'Nueva', 'cash', 'BOB');
    UPDATE finance.accounts SET currency = 'USD' WHERE id = '00000000-0000-7000-8000-00000000bc09';
    RAISE EXCEPTION 'revertir' USING ERRCODE = 'P0099';
  EXCEPTION WHEN SQLSTATE 'P0099' THEN NULL;
  END;
  IF (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000bc01') <> 190 THEN
    RAISE EXCEPTION 'saldo de Beto incorrecto';
  END IF;
  RAISE NOTICE 'OK 14 Beto gasta 10 USD (200 → 190); la moneda de una cuenta usada queda bloqueada y la de una nueva se corrige';
END $$;

-- 7. Integridad entre usuarios y categorías ---------------------------------------------
DO $$ BEGIN
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac01', c.id, 10, 'BOB', current_date
    FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'salary';
    RAISE EXCEPTION 'FALLO: gasto con categoría de ingreso';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on)
    SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000bc01', c.id, 10, 'USD', current_date
    FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'groceries';
    RAISE EXCEPTION 'FALLO: Ana usó la cuenta de Beto';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  RAISE NOTICE 'OK 15 un gasto no usa categorías de ingreso, ni la cuenta de otro usuario';
END $$;

-- 8. Metas, reportes y método de pago -------------------------------------------------------
INSERT INTO goals.goals (id, user_id, name, target_amount, currency, target_date)
VALUES (:goal_a, :ana, 'Fondo de emergencia', 5000, 'BOB', '2027-03-01');

-- Periodos financieros: semanal, quincenal y mensual
DO $$ DECLARE w record; q1 record; q2 record; q3 record; m record; c record; BEGIN
  w  := finance.period_bounds('weekly',       1::smallint,  '2026-10-14');   -- miércoles; semana desde el lunes
  q1 := finance.period_bounds('semi_monthly', 1::smallint,  '2026-10-14');
  q2 := finance.period_bounds('semi_monthly', 1::smallint,  '2026-10-20');
  q3 := finance.period_bounds('semi_monthly', 10::smallint, '2026-10-05');   -- cobra el 10 y el 25
  m  := finance.period_bounds('monthly',      25::smallint, '2026-10-14');   -- cobra el 25
  IF (w.starts_on, w.ends_on)   <> ('2026-10-12'::date, '2026-10-18'::date)
  OR (q1.starts_on, q1.ends_on) <> ('2026-10-01'::date, '2026-10-15'::date)
  OR (q2.starts_on, q2.ends_on) <> ('2026-10-16'::date, '2026-10-31'::date)
  OR (q3.starts_on, q3.ends_on) <> ('2026-09-25'::date, '2026-10-09'::date)
  OR (m.starts_on, m.ends_on)   <> ('2026-09-25'::date, '2026-10-24'::date) THEN
    RAISE EXCEPTION 'periodos: % % % % %', row_to_json(w), row_to_json(q1), row_to_json(q2), row_to_json(q3), row_to_json(m);
  END IF;
  -- Sin configurar, el periodo de un usuario es el mes calendario
  c := finance.current_period('00000000-0000-7000-8000-00000000000a', '2026-02-10');
  IF (c.starts_on, c.ends_on) <> ('2026-02-01'::date, '2026-02-28'::date) THEN RAISE EXCEPTION 'periodo de Ana: %', row_to_json(c); END IF;
  BEGIN
    UPDATE finance.user_settings SET period_type = 'semi_monthly', period_start_day = 20
     WHERE user_id = '00000000-0000-7000-8000-00000000000a';
    RAISE EXCEPTION 'FALLO: quincena desde el día 20';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  RAISE NOTICE 'OK 16b periodos: semana lunes a domingo, quincenas 1-15 y 16-31 (o 25-9 si cobra el 10), mes del 25 al 24; la quincena no empieza después del 13';
END $$;
INSERT INTO goals.goal_contributions (user_id, goal_id, amount) VALUES (:ana, :goal_a, 300), (:ana, :goal_a, 200);
INSERT INTO goals.goal_contributions (user_id, goal_id, amount, source, transaction_id)
VALUES (:ana, :goal_a, -50, 'transaction', :tx3);

DO $$ BEGIN
  IF (SELECT current_amount FROM goals.goals WHERE id = '00000000-0000-7000-8000-00000000a0a1') <> 450 THEN
    RAISE EXCEPTION 'current_amount de la meta incorrecto';
  END IF;
  RAISE NOTICE 'OK 16 aportes 300 + 200 − 50 = 450 en la meta';
END $$;

DO $$ DECLARE p record; n int; f jsonb; BEGIN
  p := finance.current_period('00000000-0000-7000-8000-00000000000a');
  SELECT count(*) INTO n FROM reports.category_totals('00000000-0000-7000-8000-00000000000a', p.starts_on, p.ends_on);
  SELECT jsonb_object_agg(currency || '.' || node, amount) INTO f
  FROM reports.money_flow('00000000-0000-7000-8000-00000000000a', p.starts_on, p.ends_on);
  IF n <> 4 OR f <> '{"BOB.lifestyle": 224.6, "BOB.goals": 450, "BOB.available": -674.6, "USD.needs": 20, "USD.available": -20}'::jsonb THEN
    RAISE EXCEPTION 'money_flow: % categorías, %', n, f;
  END IF;
  RAISE NOTICE 'OK 17 Money Flow del periodo por moneda: Bs estilo de vida 224,60 y metas 450; USD necesidades 20 (sin transferencias ni borrados)';
END $$;

DO $$ DECLARE p record; v text; BEGIN
  p := finance.current_period('00000000-0000-7000-8000-00000000000a');
  SELECT string_agg(currency || ' ' || method || '=' || total::numeric(12,2), ', ' ORDER BY currency, method) INTO v
  FROM reports.payment_method_totals('00000000-0000-7000-8000-00000000000a', p.starts_on, p.ends_on)
  WHERE kind = 'expense';
  IF v <> 'BOB card=174.60, BOB cash=50.00, USD card=20.00' THEN RAISE EXCEPTION 'por método: %', v; END IF;
  RAISE NOTICE 'OK 18 efectivo o tarjeta sale del tipo de cuenta: %', v;
END $$;

-- Sugerencia de Quick Add desde el historial y recurrentes
DO $$ DECLARE g record; r record; BEGIN
  SELECT * INTO g FROM finance.suggest_from_history('00000000-0000-7000-8000-00000000000a', 'NETFLIX');
  IF g.account_id <> '00000000-0000-7000-8000-00000000ac04' OR g.kind <> 'expense'
  OR (SELECT template_key FROM finance.categories WHERE id = g.category_id) <> 'subscriptions'
  OR EXISTS (SELECT 1 FROM finance.suggest_from_history('00000000-0000-7000-8000-00000000000a', '%')) THEN
    RAISE EXCEPTION 'sugerencia: %', row_to_json(g);
  END IF;
  -- Alquiler mensual el 31: sin moneda ni próxima fecha, las completa la base
  INSERT INTO finance.recurring_rules (user_id, account_id, category_id, amount, description, frequency, start_date)
  SELECT '00000000-0000-7000-8000-00000000000a', '00000000-0000-7000-8000-00000000ac01', c.id, 1500, 'Alquiler', 'monthly', '2026-01-31'
  FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'housing'
  RETURNING * INTO r;
  IF r.currency <> 'BOB' OR r.next_due_on <> '2026-01-31'
  OR finance.next_occurrence(r.start_date, r.frequency, '2026-01-31') <> '2026-02-28'
  OR finance.next_occurrence(r.start_date, r.frequency, '2026-02-28') <> '2026-03-31'
  OR finance.next_occurrence('2026-10-01', 'biweekly', '2026-10-01') <> '2026-10-15' THEN
    RAISE EXCEPTION 'recurrente: %', row_to_json(r);
  END IF;
  RAISE NOTICE 'OK 18b "netflix" sugiere Suscripciones y la Visa desde el historial; un alquiler del 31 vence el 28 de febrero y vuelve al 31 de marzo';
END $$;

-- 9. Cuotas, particiones y auditoría -----------------------------------------------------
DO $$ DECLARE ok int := 0; BEGIN
  FOR i IN 1 .. 11 LOOP
    IF billing.try_consume('00000000-0000-7000-8000-00000000000a', 'planning.affordability_checks') THEN ok := ok + 1; END IF;
  END LOOP;
  IF ok <> 10 THEN RAISE EXCEPTION 'la cuota de Can I Afford It? permitió % de 10', ok; END IF;
  -- Desde la migración 0023 el gratuito no dicta: ni el primero pasa.
  IF billing.try_consume('00000000-0000-7000-8000-00000000000a', 'ai.voice_entries') THEN
    RAISE EXCEPTION 'el plan gratuito no debería poder dictar';
  END IF;
  RAISE NOTICE 'OK 19 plan gratuito: 10 consultas de Can I Afford It? al mes (la 11.ª se rechaza) y sin registro por voz';
END $$;

INSERT INTO notify.notifications (user_id, type_key, title, body)
VALUES (:ana, 'money_story.ready', 'Tu historia de octubre', 'Ahorraste más que el mes pasado');
INSERT INTO ai.voice_entries (user_id, status, stt_model_code, llm_model_code, transcript, transaction_id)
VALUES (:ana, 'confirmed', 'openai.gpt-transcribe', 'anthropic.claude-haiku-5-5', 'gasté 35 bolivianos en almuerzo', :tx1);

DO $$ DECLARE p text; BEGIN
  SELECT tableoid::regclass::text INTO p FROM notify.notifications LIMIT 1;
  IF p LIKE '%default' THEN RAISE EXCEPTION 'la notificación cayó en la partición por defecto'; END IF;
  IF core.ensure_monthly_partitions('notify.notifications', current_date, 4) <> 0 THEN
    RAISE EXCEPTION 'ensure_monthly_partitions no es idempotente';
  END IF;
  PERFORM core.ensure_monthly_partitions('ai.voice_entries', (current_date - INTERVAL '8 months')::date, 2);
  IF core.drop_partitions_older_than('ai.voice_entries', (date_trunc('month', current_date) - INTERVAL '3 months')::date) <> 2 THEN
    RAISE EXCEPTION 'la retención no borró las 2 particiones viejas';
  END IF;
  RAISE NOTICE 'OK 20 particiones mensuales: enrutado (%), idempotencia y retención', p;
END $$;

DO $$ DECLARE n int; o int; BEGIN
  SELECT count(*), count(*) FILTER (WHERE owner_user_id = '00000000-0000-7000-8000-00000000000a') INTO n, o
  FROM core.audit_log WHERE entity = 'finance.accounts' AND action = 'insert';
  IF n <> 5 OR o <> 4 THEN RAISE EXCEPTION 'auditoría de cuentas: % filas, % de Ana', n, o; END IF;
  RAISE NOTICE 'OK 21 la auditoría registra las 5 altas de cuentas con su dueño y omite los cambios de saldo';
END $$;

-- 10. Datos personales: nadie más los ve ----------------------------------------------------
SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000a', true) \g /dev/null

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM finance.accounts;
  IF n <> 4 THEN RAISE EXCEPTION 'Ana ve % cuentas (se esperaban 4)', n; END IF;
  IF EXISTS (SELECT 1 FROM finance.transactions WHERE user_id <> '00000000-0000-7000-8000-00000000000a') THEN
    RAISE EXCEPTION 'Ana ve transacciones ajenas';
  END IF;
  UPDATE iam.user_preferences SET theme = 'dark', accent_color = '#16A34A';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 OR (SELECT count(*) FROM iam.user_preferences) <> 1 THEN
    RAISE EXCEPTION 'Ana cambió o ve % preferencias', n;
  END IF;
  RAISE NOTICE 'OK 22 RLS: Ana solo ve sus 4 cuentas, sus transacciones y solo cambia sus preferencias';
END $$;

DO $$ BEGIN
  INSERT INTO finance.accounts (user_id, name, type, currency)
  VALUES ('00000000-0000-7000-8000-00000000000b', 'Intrusa', 'cash', 'USD');
  RAISE EXCEPTION 'FALLO: Ana creó una cuenta para Beto';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'OK 23 RLS: Ana no puede escribir datos de Beto';
END $$;

DO $$ BEGIN
  PERFORM count(*) FROM finance.transactions_p00;
  RAISE EXCEPTION 'FALLO: acceso directo a una partición';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'OK 24 las particiones solo se leen a través de la tabla padre';
END $$;

DO $$ DECLARE b record; u record; BEGIN
  SELECT * INTO b FROM finance.balance_totals WHERE currency = 'BOB';
  SELECT * INTO u FROM finance.balance_totals WHERE currency = 'USD';
  IF (SELECT count(*) FROM finance.balance_totals) <> 2 OR (SELECT count(*) FROM finance.account_balances) <> 4
  OR b.total <> 2275.4 OR b.cash_total <> 750 OR b.card_total <> 1525.4 OR NOT b.is_main_currency
  OR u.total <> 980 OR u.card_total <> 980 OR u.is_main_currency THEN
    RAISE EXCEPTION 'totales por moneda: %, %', row_to_json(b), row_to_json(u);
  END IF;
  RAISE NOTICE 'OK 25 totales por moneda, solo con las cuentas de Ana: Bs 2.275,40 (750 en efectivo y 1.525,40 en tarjetas, principal) y USD 980, sin sumarlos';
END $$;

INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on, description)
SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac01', c.id, 46, 'BOB', current_date, 'Mercado'
FROM finance.categories c WHERE c.template_key = 'groceries';
DO $$ BEGIN
  IF (SELECT current_balance FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01') <> 704 THEN
    RAISE EXCEPTION 'saldo tras gasto bajo RLS incorrecto';
  END IF;
  RAISE NOTICE 'OK 26 con el rol de la API, el gasto de 46 Bs deja el efectivo en 704';
END $$;

SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000b', true) \g /dev/null
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac01';
  UPDATE finance.accounts SET name = 'Hackeada' WHERE id = '00000000-0000-7000-8000-00000000ac01';
  IF n <> 0 OR FOUND THEN RAISE EXCEPTION 'Beto accedió a una cuenta de Ana'; END IF;
  RAISE NOTICE 'OK 27 Beto no ve ni modifica la cuenta de Ana aunque conozca su id';
END $$;

RESET ROLE;
SET LOCAL ROLE moneymap_worker;
DO $$ BEGIN
  IF (SELECT count(*) FROM finance.accounts) <> 5 THEN RAISE EXCEPTION 'el worker no ve todos los usuarios'; END IF;
  RAISE NOTICE 'OK 28 el rol worker procesa a todos los usuarios';
END $$;
RESET ROLE;

DO $$ DECLARE l text; plan text := ''; n int; BEGIN
  FOR l IN EXECUTE $q$EXPLAIN SELECT * FROM finance.transactions
                      WHERE user_id = '00000000-0000-7000-8000-00000000000a'$q$ LOOP
    plan := plan || l || E'\n';
  END LOOP;
  n := (SELECT count(DISTINCT m[1]) FROM regexp_matches(plan, ' on (transactions_p\d\d)', 'g') AS m);
  IF n <> 1 THEN RAISE EXCEPTION 'la consulta tocó % particiones', n; END IF;
  RAISE NOTICE 'OK 29 las consultas de un usuario leen 1 de 16 particiones';
END $$;

-- =============================================================================
-- 11. Suscripciones: mensual, anual, cambios, cancelación y vuelta a gratuito
-- (los planes de pago y sus precios de PRUEBA se cargaron en la sección 2)
-- =============================================================================

DO $$ DECLARE r record; BEGIN
  SELECT * INTO r FROM billing.price_catalog WHERE plan_code = 'paid_1' AND currency = 'USD';
  IF r.monthly_amount <> 4.99 OR r.yearly_amount <> 49.99 OR r.yearly_saving_pct <> 16.5 THEN
    RAISE EXCEPTION 'price_catalog: %', row_to_json(r);
  END IF;
  RAISE NOTICE 'OK 30 cada plan tiene precio mensual y anual; pagar el año ahorra 16,5%%';
END $$;

DO $$ DECLARE r record; BEGIN
  SELECT * INTO r FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  IF r.plan_code <> 'free' OR r.status <> 'free' OR r.has_paid_access THEN RAISE EXCEPTION 'Beto no empieza en gratuito'; END IF;
  RAISE NOTICE 'OK 31 sin suscripción, el usuario está en el plan gratuito';
END $$;

-- Beto compra paid_1 mensual en App Store
SELECT set_config('app.change_source', 'store_webhook', true) \g /dev/null
INSERT INTO billing.subscriptions (id, user_id, plan_id, plan_price_id, billing_period, status, provider,
                                   provider_subscription_id, current_period_end)
SELECT :sub_b, :beto, p.id, :p1m, 'month', 'active', 'app_store', 'apple-otid-1', now() + INTERVAL '1 month'
FROM billing.plans p WHERE p.code = 'paid_1';

DO $$ DECLARE r record; v record; BEGIN
  SELECT * INTO r FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  SELECT * INTO v FROM billing.limit_status('00000000-0000-7000-8000-00000000000b', 'ai.voice_entries');
  IF r.plan_code <> 'paid_1' OR NOT r.has_paid_access OR r.billing_period <> 'month' OR v.limit_value IS NOT NULL THEN
    RAISE EXCEPTION 'suscripción mensual: %, %', row_to_json(r), row_to_json(v);
  END IF;
  RAISE NOTICE 'OK 32 al suscribirse pasa a paid_1 mensual y el registro por voz queda ilimitado';
END $$;

DO $$ BEGIN
  INSERT INTO billing.subscriptions (user_id, plan_id, plan_price_id, billing_period, status, provider, current_period_end)
  SELECT '00000000-0000-7000-8000-00000000000b', p.id, '00000000-0000-7000-8000-00000000f201', 'month', 'active', 'web', now() + INTERVAL '1 month'
  FROM billing.plans p WHERE p.code = 'paid_2';
  RAISE EXCEPTION 'FALLO: dos suscripciones vivas';
EXCEPTION WHEN unique_violation THEN NULL;
END $$;
DO $$ BEGIN
  INSERT INTO billing.subscriptions (user_id, plan_id, plan_price_id, billing_period, status, provider, current_period_end)
  SELECT '00000000-0000-7000-8000-00000000000c', p.id, '00000000-0000-7000-8000-00000000f101', 'month', 'active', 'web', now() + INTERVAL '1 month'
  FROM billing.plans p WHERE p.code = 'paid_2';
  RAISE EXCEPTION 'FALLO: precio de otro plan';
EXCEPTION WHEN foreign_key_violation THEN
  RAISE NOTICE 'OK 33 una sola suscripción viva por usuario, y el precio debe ser del plan y periodo elegidos';
END $$;

INSERT INTO billing.payments (user_id, subscription_id, plan_price_id, provider, provider_transaction_id, kind, status,
                              amount, currency, billing_period, period_start, period_end)
VALUES (:beto, :sub_b, :p1m, 'app_store', 'apple-tx-1', 'initial', 'succeeded', 4.99, 'USD', 'month', now(), now() + INTERVAL '1 month');
DO $$ BEGIN
  INSERT INTO billing.payments (user_id, provider, provider_transaction_id, kind, status, amount, currency)
  VALUES ('00000000-0000-7000-8000-00000000000b', 'app_store', 'apple-tx-1', 'initial', 'succeeded', 4.99, 'USD');
  RAISE EXCEPTION 'FALLO: cobro duplicado';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'OK 34 un mismo cobro de la tienda no se registra dos veces';
END $$;

-- De mensual a anual
UPDATE billing.subscriptions
   SET plan_price_id = :p1y, billing_period = 'year', current_period_start = now(), current_period_end = now() + INTERVAL '1 year'
 WHERE id = :sub_b;
-- Sube a paid_2 mensual
UPDATE billing.subscriptions
   SET plan_id = (SELECT id FROM billing.plans WHERE code = 'paid_2'), plan_price_id = :p2m, billing_period = 'month',
       current_period_start = now(), current_period_end = now() + INTERVAL '1 month'
 WHERE id = :sub_b;

DO $$ DECLARE v text[]; BEGIN
  SELECT array_agg(change_type || ':' || coalesce(from_period, '-') || '>' || to_period ORDER BY seq) INTO v
  FROM billing.subscription_changes WHERE subscription_id = '00000000-0000-7000-8000-00000000e00b';
  IF v <> ARRAY['started:->month', 'period_changed:month>year', 'upgraded:year>month'] THEN
    RAISE EXCEPTION 'historial: %', v;
  END IF;
  RAISE NOTICE 'OK 35 historial: alta mensual, cambio a anual y subida de plan';
END $$;

-- Mientras paga, Beto agrega 4 tarjetas de débito
INSERT INTO finance.accounts (user_id, name, type, currency, opening_balance)
SELECT :beto, 'Tarjeta ' || g, 'card', 'USD', 100 FROM generate_series(2, 5) g;

-- Cancela: conserva el acceso hasta el fin del periodo
SELECT set_config('app.change_source', 'user', true) \g /dev/null
UPDATE billing.subscriptions SET auto_renew = false WHERE id = :sub_b;

DO $$ DECLARE r record; s record; BEGIN
  SELECT * INTO r FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  SELECT * INTO s FROM billing.subscriptions WHERE id = '00000000-0000-7000-8000-00000000e00b';
  IF NOT r.has_paid_access OR r.auto_renew OR s.canceled_at IS NULL OR s.cancel_reason <> 'user' THEN
    RAISE EXCEPTION 'cancelación: %', row_to_json(r);
  END IF;
  RAISE NOTICE 'OK 36 al cancelar sigue con el plan de pago hasta el fin del periodo';
END $$;

-- Pasa el periodo: el job lo devuelve a gratuito
DO $$ DECLARE n int; r record; v text[]; BEGIN
  n := billing.process_due_subscriptions(now() + INTERVAL '2 months');
  SELECT * INTO r FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  SELECT array_agg(change_type || '@' || source ORDER BY seq) INTO v FROM billing.subscription_changes
  WHERE subscription_id = '00000000-0000-7000-8000-00000000e00b' AND seq > (
    SELECT max(seq) FROM billing.subscription_changes WHERE change_type = 'auto_renew_disabled');
  IF r.plan_code <> 'free' OR r.has_paid_access OR v <> ARRAY['expired@job', 'reverted_to_free@job'] THEN
    RAISE EXCEPTION 'vuelta a gratuito: %, %', row_to_json(r), v;
  END IF;
  RAISE NOTICE 'OK 37 al terminar el periodo expira y el usuario vuelve al plan gratuito';
END $$;

DO $$ DECLARE l record; n int; BEGIN
  SELECT count(*) INTO n FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000b' AND deleted_at IS NULL;
  SELECT * INTO l FROM billing.limit_status('00000000-0000-7000-8000-00000000000b', 'finance.cards');
  IF n <> 5 OR l.used <> 4 OR l.limit_value <> 1 OR l.allowed THEN
    RAISE EXCEPTION 'límites tras bajar: % cuentas, %', n, row_to_json(l);
  END IF;
  -- Sigue registrando gastos con sus tarjetas
  INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, currency, occurred_on, description)
  SELECT a.user_id, 'expense', a.id, c.id, 12, 'USD', current_date, 'Café'
  FROM finance.accounts a JOIN finance.categories c ON c.user_id = a.user_id AND c.template_key = 'restaurants'
  WHERE a.user_id = '00000000-0000-7000-8000-00000000000b' AND a.name = 'Tarjeta 2';
  -- Pero no agrega otra tarjeta…
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency)
    VALUES ('00000000-0000-7000-8000-00000000000b', 'Tarjeta 6', 'card', 'USD');
    RAISE EXCEPTION 'FALLO: agregó una tarjeta en el plan gratuito';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN NULL;
  END;
  -- …ni desarchiva una que archivó
  UPDATE finance.accounts SET archived_at = now() WHERE user_id = '00000000-0000-7000-8000-00000000000b' AND name = 'Tarjeta 5';
  BEGIN
    UPDATE finance.accounts SET archived_at = NULL WHERE user_id = '00000000-0000-7000-8000-00000000000b' AND name = 'Tarjeta 5';
    RAISE EXCEPTION 'FALLO: desarchivó una tarjeta en el plan gratuito';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN NULL;
  END;
  -- El efectivo no tiene límite en su moneda, pero el gratuito permite 1 sola moneda
  INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000b', 'Ahorro', 'cash', 'USD');
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000b', 'Efectivo Bs', 'cash', 'BOB');
    RAISE EXCEPTION 'FALLO: abrió una segunda moneda en el plan gratuito';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN NULL;
  END;
  IF (SELECT current_balance FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000b' AND name = 'Tarjeta 2') <> 88 THEN
    RAISE EXCEPTION 'el gasto con la tarjeta conservada no se registró';
  END IF;
  RAISE NOTICE 'OK 38 en gratuito (1 tarjeta, 1 moneda) conserva y usa sus 4 tarjetas, pero no agrega ni desarchiva otra; más efectivo en USD sí, una cuenta en Bs no';
END $$;

-- Vuelve a suscribirse (App Store reactiva la misma suscripción)
SELECT set_config('app.change_source', 'store_webhook', true) \g /dev/null
UPDATE billing.subscriptions
   SET status = 'active', auto_renew = true, current_period_start = now() + INTERVAL '3 months',
       current_period_end = now() + INTERVAL '4 months'
 WHERE id = :sub_b;

DO $$ DECLARE r record; s record; BEGIN
  SELECT * INTO r FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  SELECT * INTO s FROM billing.subscriptions WHERE id = '00000000-0000-7000-8000-00000000e00b';
  IF r.plan_code <> 'paid_2' OR s.ended_at IS NOT NULL OR s.canceled_at IS NOT NULL OR NOT EXISTS (
       SELECT 1 FROM billing.subscription_changes WHERE subscription_id = s.id AND change_type = 'resubscribed') THEN
    RAISE EXCEPTION 'resuscripción: %', row_to_json(r);
  END IF;
  UPDATE finance.accounts SET archived_at = NULL WHERE user_id = '00000000-0000-7000-8000-00000000000b' AND name = 'Tarjeta 5';
  INSERT INTO finance.accounts (user_id, name, type, currency)
  VALUES ('00000000-0000-7000-8000-00000000000b', 'Tarjeta 6', 'card', 'USD');
  INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000b', 'Efectivo Bs', 'cash', 'BOB');
  RAISE NOTICE 'OK 39 puede volver a suscribirse, recupera el plan de pago y vuelve a agregar tarjetas y monedas';
END $$;

-- Ana: cobro fallido en Play Store → gracia → sin acceso → recupera
INSERT INTO billing.subscriptions (id, user_id, plan_id, plan_price_id, billing_period, status, provider,
                                   provider_subscription_id, current_period_end, grace_period_ends_at)
SELECT :sub_a, :ana, p.id, :p1m, 'month', 'grace_period', 'play_store', 'play-token-1',
       now() + INTERVAL '1 month', now() + INTERVAL '3 days'
FROM billing.plans p WHERE p.code = 'paid_1';

DO $$ DECLARE r1 record; r2 record; BEGIN
  SELECT * INTO r1 FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  PERFORM billing.process_due_subscriptions(now() + INTERVAL '4 days');
  SELECT * INTO r2 FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  IF NOT r1.has_paid_access OR r2.has_paid_access OR r2.plan_code <> 'free' OR r2.status <> 'on_hold' THEN
    RAISE EXCEPTION 'gracia: %, %', row_to_json(r1), row_to_json(r2);
  END IF;
  UPDATE billing.subscriptions SET status = 'active' WHERE id = '00000000-0000-7000-8000-00000000e00a';
  IF (SELECT plan_code FROM billing.user_plans WHERE user_id = '00000000-0000-7000-8000-00000000000a') <> 'paid_1'
  OR NOT EXISTS (SELECT 1 FROM billing.subscription_changes WHERE subscription_id = '00000000-0000-7000-8000-00000000e00a' AND change_type = 'recovered') THEN
    RAISE EXCEPTION 'no recuperó el plan tras pagar';
  END IF;
  RAISE NOTICE 'OK 40 cobro fallido: con acceso en gracia, gratuito en on_hold, y lo recupera al pagar';
END $$;

-- Carla: prueba gratis en web con cambio programado a anual
INSERT INTO iam.users (id, email, first_name, last_name, terms_version) VALUES (:carla, 'carla@example.com', 'Carla', 'Peña', '2026-10');
INSERT INTO billing.subscriptions (user_id, plan_id, plan_price_id, billing_period, status, provider,
                                   trial_ends_at, current_period_end, pending_plan_price_id, pending_change_at)
SELECT :carla, p.id, :p1m, 'month', 'trialing', 'web', now() + INTERVAL '7 days', now() + INTERVAL '7 days',
       :p1y, now() + INTERVAL '7 days'
FROM billing.plans p WHERE p.code = 'paid_1';

DO $$ DECLARE s record; BEGIN
  PERFORM billing.process_due_subscriptions(now() + INTERVAL '8 days');
  SELECT * INTO s FROM billing.subscriptions WHERE user_id = '00000000-0000-7000-8000-00000000000c';
  IF s.billing_period <> 'year' OR s.pending_plan_price_id IS NOT NULL OR NOT EXISTS (
       SELECT 1 FROM billing.subscription_changes WHERE subscription_id = s.id AND change_type = 'period_changed' AND source = 'job') THEN
    RAISE EXCEPTION 'cambio programado: %', row_to_json(s);
  END IF;
  RAISE NOTICE 'OK 41 un cambio programado (mensual → anual) se aplica al terminar el periodo';
END $$;

-- La API solo ve su propia suscripción y no puede modificarla
SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000a', true) \g /dev/null
DO $$ BEGIN
  IF (SELECT count(*) FROM billing.subscriptions) <> 2
  OR EXISTS (SELECT 1 FROM billing.subscriptions WHERE user_id <> '00000000-0000-7000-8000-00000000000a')
  OR EXISTS (SELECT 1 FROM billing.subscription_changes WHERE user_id <> '00000000-0000-7000-8000-00000000000a') THEN
    RAISE EXCEPTION 'la API ve suscripciones ajenas';
  END IF;
  BEGIN
    UPDATE billing.subscriptions SET status = 'active';
    RAISE EXCEPTION 'FALLO: la API modificó una suscripción';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 42 la API solo lee las suscripciones del usuario (su promoción vencida y la actual); las escriben los webhooks';
END $$;
RESET ROLE;

-- =============================================================================
-- 12. Logs e incidentes
-- =============================================================================
DO $$ DECLARE v uuid; BEGIN
  v := ops.log('info', 'auth', 'auth.login.succeeded', 'Inicio de sesión', p_user_id => '00000000-0000-7000-8000-00000000000a');
  IF v IS NULL OR (SELECT incident_id FROM ops.logs WHERE id = v) IS NOT NULL THEN RAISE EXCEPTION 'log info'; END IF;
  IF ops.log('debug', 'api', 'api.trace', 'detalle') IS NOT NULL THEN RAISE EXCEPTION 'debug no debería guardarse'; END IF;
  RAISE NOTICE 'OK 43 un log info se guarda sin incidente; debug se omite por defecto';
END $$;

DO $$ DECLARE l1 uuid; l2 uuid; i record; BEGIN
  l1 := ops.log('error', 'integration', 'push.fcm.timeout', 'Firebase Cloud Messaging no respondió',
                p_service => 'worker', p_error_type => 'TimeoutError', p_user_id => '00000000-0000-7000-8000-00000000000a');
  l2 := ops.log('error', 'integration', 'push.fcm.timeout', 'Firebase Cloud Messaging no respondió',
                p_service => 'worker', p_error_type => 'TimeoutError', p_user_id => '00000000-0000-7000-8000-00000000000b');
  SELECT * INTO i FROM ops.incidents WHERE fingerprint = 'push.fcm.timeout:TimeoutError';
  IF i.occurrences <> 2 OR i.affected_users <> 2 OR i.severity <> 'sev3' OR i.code !~ '^INC-\d{6}$'
  OR (SELECT count(DISTINCT incident_id) FROM ops.logs WHERE id IN (l1, l2) AND incident_id = i.id) <> 1 THEN
    RAISE EXCEPTION 'agrupación: %', row_to_json(i);
  END IF;
  PERFORM ops.log('critical', 'integration', 'push.fcm.timeout', 'Sin enviar notificaciones hace 2 horas',
                  p_service => 'worker', p_error_type => 'TimeoutError');
  IF (SELECT severity FROM ops.incidents WHERE id = i.id) <> 'sev2' THEN RAISE EXCEPTION 'no escaló a sev2'; END IF;
  RAISE NOTICE 'OK 44 errores iguales se agrupan en un incidente (%: 2 usuarios) y un critical lo escala a sev2', i.code;
END $$;

-- El equipo resuelve el incidente
SET LOCAL ROLE moneymap_ops;
SELECT set_config('app.actor', 'dana@moneymap.team', true) \g /dev/null
UPDATE ops.incidents SET status = 'investigating', assigned_to = 'dana@moneymap.team'
WHERE fingerprint = 'push.fcm.timeout:TimeoutError' AND status = 'open';
UPDATE ops.incidents SET status = 'resolved', root_cause = 'Timeout de 5 s muy corto', resolution = 'Reintentos con backoff'
WHERE fingerprint = 'push.fcm.timeout:TimeoutError' AND status = 'investigating';
DO $$ DECLARE i record; n int; BEGIN
  SELECT * INTO i FROM ops.incidents WHERE fingerprint = 'push.fcm.timeout:TimeoutError';
  SELECT count(*) INTO n FROM ops.incident_updates WHERE incident_id = i.id AND author = 'dana@moneymap.team';
  IF i.acknowledged_at IS NULL OR i.resolved_at IS NULL OR n <> 2 OR (SELECT count(*) FROM ops.open_incidents) <> 0 THEN
    RAISE EXCEPTION 'resolución: %, % notas', row_to_json(i), n;
  END IF;
  RAISE NOTICE 'OK 45 el equipo lo toma y lo resuelve; la línea de tiempo registra quién y cuándo';
END $$;
RESET ROLE;

DO $$ DECLARE old_id uuid; new_inc record; BEGIN
  SELECT id INTO old_id FROM ops.incidents WHERE fingerprint = 'push.fcm.timeout:TimeoutError' AND status = 'resolved';
  PERFORM ops.log('error', 'integration', 'push.fcm.timeout', 'Volvió a fallar', p_service => 'worker', p_error_type => 'TimeoutError');
  SELECT * INTO new_inc FROM ops.incidents WHERE fingerprint = 'push.fcm.timeout:TimeoutError' AND status = 'open';
  IF new_inc.id = old_id OR new_inc.previous_incident_id <> old_id THEN RAISE EXCEPTION 'regresión: %', row_to_json(new_inc); END IF;
  RAISE NOTICE 'OK 46 si un error resuelto vuelve, se abre un incidente nuevo enlazado al anterior';
END $$;

DO $$ BEGIN
  BEGIN
    UPDATE ops.logs SET message = 'editado';
    RAISE EXCEPTION 'FALLO: se editó un log';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    DELETE FROM ops.logs;
    RAISE EXCEPTION 'FALLO: se borró un log';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 47 los logs no se pueden editar ni borrar, ni siquiera con el rol dueño';
END $$;

SET LOCAL ROLE moneymap_app;
DO $$ BEGIN
  PERFORM ops.log('warning', 'billing', 'billing.webhook.retry', 'Reintento de webhook', p_service => 'api');
  BEGIN
    PERFORM count(*) FROM ops.logs;
    RAISE EXCEPTION 'FALLO: la API leyó los logs';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 48 la API escribe logs con ops.log() pero no puede leerlos';
END $$;
RESET ROLE;

SET LOCAL ROLE moneymap_ops;
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM ops.error_summary_24h WHERE event_code = 'push.fcm.timeout';
  IF n <> 1 THEN RAISE EXCEPTION 'resumen de errores'; END IF;
  BEGIN
    PERFORM count(*) FROM finance.transactions;
    RAISE EXCEPTION 'FALLO: el equipo de operaciones leyó transacciones';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 49 el equipo de operaciones ve logs e incidentes, pero no datos financieros';
END $$;
RESET ROLE;

DO $$ DECLARE v uuid; r record; BEGIN
  v := ops.log('LOUD', 'whatever', 'Bad Code!', 'Mensaje con datos raros');
  SELECT level, category, event_code, context, tableoid::regclass::text AS part INTO r FROM ops.logs WHERE id = v;
  IF r.level <> 'warning' OR r.category <> 'system' OR r.event_code <> 'system.bad_code' OR r.context ->> 'original_level' <> 'LOUD'
  OR r.part LIKE '%default' THEN
    RAISE EXCEPTION 'normalización: %', row_to_json(r);
  END IF;
  RAISE NOTICE 'OK 50 datos de entrada inválidos no rompen el log: se normalizan (partición %)', r.part;
END $$;

-- =============================================================================
-- 13. IA: proveedores con principal y respaldos
-- =============================================================================
DO $$ DECLARE t text; e text; BEGIN
  SELECT string_agg(model_code, ' > ' ORDER BY pos) INTO t FROM ai.route('voice.transcribe');
  SELECT string_agg(model_code, ' > ' ORDER BY pos) INTO e FROM ai.route('voice.extract');
  IF t <> 'local.parakeet-tdt-0.6b-v3 > local.whisper-large-v3-turbo'
  OR e <> 'ollama.qwen3-5-4b > ollama.gemma3-4b' THEN
    RAISE EXCEPTION 'rutas: % | %', t, e;
  END IF;
  RAISE NOTICE 'OK 51 cada tarea tiene principal y respaldos: % | %', t, e;
END $$;

DO $$ BEGIN
  INSERT INTO ai.routes (task, position, model_code) VALUES ('voice.transcribe', 9, 'openai.gpt-6-luna');
  RAISE EXCEPTION 'FALLO: un LLM quedó como modelo de voz a texto';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'OK 52 una ruta rechaza un modelo del tipo equivocado: %', SQLERRM;
END $$;

-- Ana dicta "gasté 50 en comida": la API crea el dictado (con RLS)...
SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000a', true) \g /dev/null
INSERT INTO ai.voice_entries (id, created_at, user_id, audio_seconds, prompt_version)
VALUES ('00000000-0000-7000-8000-0000000000e1', '2026-10-13 14:00:00+00', :ana, 6, 'extract-v1');
RESET ROLE;

-- ...y el worker llama a los proveedores: transcribe con el principal; al extraer,
-- el principal se agota y responde el primer respaldo
SET LOCAL ROLE moneymap_worker;
INSERT INTO ai.calls (task, model_code, route_position, status, user_id, voice_entry_id, voice_entry_created_at, latency_ms, audio_seconds)
VALUES ('voice.transcribe', 'openai.gpt-transcribe', 1, 'ok', :ana, '00000000-0000-7000-8000-0000000000e1', '2026-10-13 14:00:00+00', 900, 6);
INSERT INTO ai.calls (task, model_code, route_position, status, user_id, voice_entry_id, voice_entry_created_at, latency_ms)
VALUES ('voice.extract', 'openai.gpt-6-luna', 1, 'timeout', :ana, '00000000-0000-7000-8000-0000000000e1', '2026-10-13 14:00:00+00', 6000);
-- El detalle del error no va en ai.calls: el worker lo escribe en ops.logs
SELECT ops.log('warning', 'ai', 'ai.call.timeout', 'openai.gpt-6-luna no respondió en voice.extract',
               p_context => '{"model": "openai.gpt-6-luna", "task": "voice.extract", "error_code": "read_timeout"}',
               p_service => 'worker', p_user_id => :ana, p_http_status => 504) \g /dev/null
INSERT INTO ai.calls (task, model_code, route_position, status, user_id, voice_entry_id, voice_entry_created_at, latency_ms, input_tokens, output_tokens)
VALUES ('voice.extract', 'deepseek.deepseek-flash', 2, 'ok', :ana, '00000000-0000-7000-8000-0000000000e1', '2026-10-13 14:00:00+00', 1400, 800, 100);
RESET ROLE;

DO $$ DECLARE v record; BEGIN
  SELECT * INTO v FROM ai.voice_entries WHERE id = '00000000-0000-7000-8000-0000000000e1';
  IF v.attempts <> 3 OR NOT v.fallback_used OR v.stt_model_code <> 'openai.gpt-transcribe'
  OR v.llm_model_code <> 'deepseek.deepseek-flash' OR v.cost_usd <> 0.00081 OR v.input_tokens <> 800 THEN
    RAISE EXCEPTION 'dictado: %', row_to_json(v);
  END IF;
  RAISE NOTICE 'OK 53 respaldo: OpenAI se agotó, DeepSeek extrajo; el dictado suma 3 llamadas y % USD (6 s de audio + 800/100 tokens)', v.cost_usd;
END $$;

DO $$ DECLARE t record; x record; l record; BEGIN
  SELECT * INTO t FROM ai.usage_monthly WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND task = 'voice.transcribe';
  SELECT * INTO x FROM ai.usage_monthly WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND task = 'voice.extract';
  SELECT level, context ->> 'error_code' AS code INTO l FROM ops.logs WHERE event_code = 'ai.call.timeout' ORDER BY occurred_at DESC LIMIT 1;
  IF t.calls <> 1 OR t.audio_seconds <> 6 OR x.calls <> 2 OR x.failed_calls <> 1 OR x.input_tokens <> 800
  OR x.cost_usd <> 0.00036 OR l.level <> 'warning' OR l.code <> 'read_timeout' THEN
    RAISE EXCEPTION 'uso por usuario: %, %, %', row_to_json(t), row_to_json(x), row_to_json(l);
  END IF;
  RAISE NOTICE 'OK 54 uso de IA por usuario y mes: 1 transcripción (6 s) y 2 extracciones (1 fallida, 800 tokens); el detalle del error está en ops.logs';
END $$;

DO $$ DECLARE a numeric; b numeric; c numeric; BEGIN
  INSERT INTO ai.calls (task, model_code, route_position, status, audio_seconds)
  VALUES ('voice.transcribe', 'groq.whisper-large-v3-turbo', 2, 'ok', 3) RETURNING cost_usd INTO a;
  INSERT INTO ai.calls (task, model_code, route_position, status, input_tokens, cached_input_tokens, output_tokens)
  VALUES ('voice.extract', 'openai.gpt-6-luna', 1, 'ok', 800, 600, 100) RETURNING cost_usd INTO b;
  INSERT INTO ai.calls (task, model_code, route_position, status)
  VALUES ('voice.extract', 'anthropic.claude-haiku-5-5', 3, 'circuit_open') RETURNING cost_usd INTO c;
  IF a <> 0.000111 OR b <> 0.000076 OR c <> 0 THEN RAISE EXCEPTION 'costos: % % %', a, b, c; END IF;
  RAISE NOTICE 'OK 55 costo por llamada: Groq cobra 10 s mínimos (% USD), tokens en caché más baratos (% USD), circuito abierto 0', a, b;
END $$;

-- El equipo cambia el principal sin desplegar código
SET LOCAL ROLE moneymap_ops;
SELECT set_config('app.actor', 'dana@moneymap.team', true) \g /dev/null
SELECT ai.set_route_order('voice.extract', ARRAY['deepseek.deepseek-flash', 'openai.gpt-6-luna'], 'OpenAI con timeouts') \g /dev/null
DO $$ DECLARE e text; ch record; BEGIN
  SELECT string_agg(model_code, ' > ' ORDER BY pos) INTO e FROM ai.route('voice.extract');
  SELECT * INTO ch FROM ai.route_changes ORDER BY id DESC LIMIT 1;
  IF e <> 'deepseek.deepseek-flash > openai.gpt-6-luna' OR ch.changed_by <> 'dana@moneymap.team'
  OR ch.old_order <> ARRAY['ollama.qwen3-5-4b', 'ollama.gemma3-4b']
  OR (SELECT is_active FROM ai.routes WHERE task = 'voice.extract' AND model_code = 'anthropic.claude-haiku-5-5') THEN
    RAISE EXCEPTION 'cambio de orden: % / %', e, row_to_json(ch);
  END IF;
  UPDATE ai.models SET is_active = false WHERE code = 'deepseek.deepseek-flash';
  SELECT string_agg(model_code, ' > ' ORDER BY pos) INTO e FROM ai.route('voice.extract');
  IF e <> 'openai.gpt-6-luna' THEN RAISE EXCEPTION 'apagar un modelo: %', e; END IF;
  BEGIN
    UPDATE ai.models SET input_per_mtok_usd = 0 WHERE code = 'openai.gpt-6-luna';
    RAISE EXCEPTION 'FALLO: el equipo cambió un precio';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 56 el equipo pone a DeepSeek de principal (queda en el historial con su autor) y puede apagar un proveedor, pero no tocar precios';
END $$;
RESET ROLE;

SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000b', true) \g /dev/null
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM ai.voice_entries WHERE user_id = '00000000-0000-7000-8000-00000000000a') THEN
    RAISE EXCEPTION 'Beto ve los dictados de Ana';
  END IF;
  BEGIN
    PERFORM count(*) FROM ai.calls;
    RAISE EXCEPTION 'FALLO: la API leyó las llamadas a proveedores';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM ai.set_route_order('voice.extract', ARRAY['openai.gpt-6-luna']);
    RAISE EXCEPTION 'FALLO: la API cambió el proveedor principal';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'OK 57 la API no ve dictados ajenos, ni las llamadas, ni puede cambiar proveedores';
END $$;
RESET ROLE;

SET LOCAL ROLE moneymap_worker;
DO $$ BEGIN
  UPDATE ai.calls SET cost_usd = 0;
  RAISE EXCEPTION 'FALLO: el worker editó una llamada';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'OK 58 las llamadas son de solo inserción para el worker';
END $$;
RESET ROLE;

DO $$ DECLARE before int; after int; BEGIN
  SELECT used INTO before FROM billing.usage_counters
  WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND feature_key = 'ai.voice_entries';
  PERFORM billing.release('00000000-0000-7000-8000-00000000000a', 'ai.voice_entries');
  SELECT used INTO after FROM billing.usage_counters
  WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND feature_key = 'ai.voice_entries';
  IF after <> before - 1 OR NOT billing.try_consume('00000000-0000-7000-8000-00000000000a', 'ai.voice_entries') THEN
    RAISE EXCEPTION 'devolver cuota: % → %', before, after;
  END IF;
  RAISE NOTICE 'OK 59 si fallan todos los proveedores, el dictado se devuelve a la cuota (% → %)', before, after;
END $$;

SET LOCAL ROLE moneymap_ops;
DO $$ DECLARE h record; c record; BEGIN
  SELECT * INTO h FROM ai.provider_health_24h WHERE model_code = 'deepseek.deepseek-flash';
  IF h.ok <> 1 OR h.served_as_fallback <> 1 THEN RAISE EXCEPTION 'salud deepseek: %', row_to_json(h); END IF;
  SELECT * INTO h FROM ai.provider_health_24h WHERE model_code = 'openai.gpt-6-luna';
  IF h.calls <> 2 OR h.error_rate <> 0.5 THEN RAISE EXCEPTION 'salud openai: %', row_to_json(h); END IF;
  SELECT sum(cost_usd) AS total INTO c FROM ai.monthly_cost_by_model;
  IF c.total <> 0.000997 THEN RAISE EXCEPTION 'costo mensual: %', c.total; END IF;
  RAISE NOTICE 'OK 60 el tablero de proveedores muestra fallas, respaldos y costo real (% USD)', c.total;
END $$;
RESET ROLE;

-- =============================================================================
-- 14. Monedas configurables y tarjetas según el plan
-- =============================================================================
\set dani '''00000000-0000-7000-8000-00000000000d'''

DO $$ DECLARE a text; b text; BEGIN
  SELECT string_agg(currency, ',' ORDER BY currency) INTO a FROM finance.user_currencies WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  SELECT string_agg(currency, ',' ORDER BY currency) INTO b FROM finance.user_currencies WHERE user_id = '00000000-0000-7000-8000-00000000000b';
  IF a <> 'BOB,USD' OR b <> 'BOB,USD' THEN RAISE EXCEPTION 'Mis monedas: Ana %, Beto %', a, b; END IF;
  RAISE NOTICE 'OK 61 Mis monedas se arma sola con la moneda principal y las de sus cuentas (Ana %, Beto %)', a, b;
END $$;

SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000a', true) \g /dev/null
DO $$ DECLARE n int; BEGIN
  INSERT INTO finance.user_currencies (user_id, currency, sort_order) VALUES ('00000000-0000-7000-8000-00000000000a', 'EUR', 3);
  DELETE FROM finance.user_currencies WHERE currency = 'EUR';
  BEGIN
    DELETE FROM finance.user_currencies WHERE currency = 'BOB';
    RAISE EXCEPTION 'FALLO: quitó su moneda principal';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    DELETE FROM finance.user_currencies WHERE currency = 'USD';
    RAISE EXCEPTION 'FALLO: quitó la moneda de una tarjeta activa';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  SELECT count(*) INTO n FROM finance.user_currencies;
  IF n <> 2 THEN RAISE EXCEPTION 'Ana ve % monedas en Mis monedas', n; END IF;
  RAISE NOTICE 'OK 62 Ana agrega y quita EUR de Mis monedas; no puede quitar su moneda principal ni la de una tarjeta activa, y solo ve las suyas';
END $$;
RESET ROLE;

UPDATE catalog.currencies SET is_active = false WHERE code IN ('PYG', 'USD');
DO $$ DECLARE n int := 0; BEGIN
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000a', 'Guaraníes', 'cash', 'PYG');
  EXCEPTION WHEN check_violation THEN n := n + 1;
  END;
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000a', 'Dólares 2', 'cash', 'USD');
  EXCEPTION WHEN check_violation THEN n := n + 1;
  END;
  BEGIN
    INSERT INTO finance.user_currencies (user_id, currency) VALUES ('00000000-0000-7000-8000-00000000000a', 'PYG');
  EXCEPTION WHEN check_violation THEN n := n + 1;
  END;
  BEGIN
    UPDATE finance.user_settings SET main_currency = 'PYG' WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  EXCEPTION WHEN check_violation THEN n := n + 1;
  END;
  IF n <> 4 THEN RAISE EXCEPTION 'una moneda desactivada se aceptó % de 4 veces', 4 - n; END IF;
  -- USD está desactivado, pero la tarjeta en USD que ya existe sigue registrando y editando
  UPDATE finance.transactions SET description = 'Supermercado' WHERE description = 'Hipermaxi';
  IF NOT FOUND THEN RAISE EXCEPTION 'no se pudo editar un gasto en una moneda desactivada'; END IF;
  INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
  SELECT '00000000-0000-7000-8000-00000000000a', 'expense', '00000000-0000-7000-8000-00000000ac02', c.id, 5, current_date, 'Café'
  FROM finance.categories c WHERE c.user_id = '00000000-0000-7000-8000-00000000000a' AND c.template_key = 'restaurants';
  RAISE NOTICE 'OK 63 una moneda desactivada no se acepta en cuentas nuevas, Mis monedas ni como principal; las cuentas que ya existen siguen registrando';
END $$;
UPDATE catalog.currencies SET is_active = true WHERE code IN ('PYG', 'USD');

-- Dani se registra en el plan gratuito
INSERT INTO iam.users (id, email, first_name, last_name, terms_version) VALUES (:dani, 'dani@example.com', 'Daniela', 'Soria', '2026-10');
SELECT finance.setup_user(:dani, 'BOB') \g /dev/null
SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000d', true) \g /dev/null
DO $$ DECLARE l record; c record; BEGIN
  INSERT INTO finance.accounts (user_id, name, type, currency) VALUES
    ('00000000-0000-7000-8000-00000000000d', 'Efectivo', 'cash', 'BOB'),
    ('00000000-0000-7000-8000-00000000000d', 'Débito', 'card', 'BOB');
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000d', 'Visa', 'card', 'BOB');
    RAISE EXCEPTION 'FALLO: agregó una segunda tarjeta en el plan gratuito';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN
    IF SQLERRM <> 'Tu plan permite 1 tarjeta(s) y ya tienes 1' THEN RAISE; END IF;
  END;
  BEGIN
    UPDATE finance.accounts SET type = 'card' WHERE name = 'Efectivo';
    RAISE EXCEPTION 'FALLO: convirtió su efectivo en una segunda tarjeta';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN NULL;
  END;
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000d', 'Efectivo USD', 'cash', 'USD');
    RAISE EXCEPTION 'FALLO: abrió una segunda moneda en el plan gratuito';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN
    IF SQLERRM <> 'Tu plan permite 1 moneda(s) y ya usas 1' THEN RAISE; END IF;
  END;
  SELECT * INTO l FROM billing.limit_status('00000000-0000-7000-8000-00000000000d', 'finance.cards');
  SELECT * INTO c FROM billing.limit_status('00000000-0000-7000-8000-00000000000d', 'finance.currencies');
  IF l.limit_value <> 1 OR l.used <> 1 OR l.allowed OR c.limit_value <> 1 OR c.used <> 1 OR c.allowed
  OR (SELECT count(*) FROM finance.accounts) <> 2 THEN
    RAISE EXCEPTION 'plan gratuito: tarjetas %, monedas %', row_to_json(l), row_to_json(c);
  END IF;
  RAISE NOTICE 'OK 64 plan gratuito: efectivo y 1 tarjeta en Bs; ni otra tarjeta ni otra moneda: "Tu plan permite 1 moneda(s)…"';
END $$;
RESET ROLE;

-- Dani se suscribe a paid_1. Para la prueba, paid_1 permite 2 tarjetas (el seed lo deja ilimitado)
SELECT set_config('app.change_source', 'store_webhook', true) \g /dev/null
INSERT INTO billing.subscriptions (user_id, plan_id, plan_price_id, billing_period, status, provider, provider_subscription_id, current_period_end)
SELECT :dani, p.id, :p1m, 'month', 'active', 'play_store', 'play-token-dani', now() + INTERVAL '1 month'
FROM billing.plans p WHERE p.code = 'paid_1';
UPDATE billing.plan_features SET limit_value = 2
WHERE feature_key = 'finance.cards' AND plan_id = (SELECT id FROM billing.plans WHERE code = 'paid_1');

SET LOCAL ROLE moneymap_app;
SELECT set_config('app.user_id', '00000000-0000-7000-8000-00000000000d', true) \g /dev/null
DO $$ DECLARE l record; v uuid; BEGIN
  INSERT INTO finance.accounts (user_id, name, type, currency) VALUES
    ('00000000-0000-7000-8000-00000000000d', 'Visa BNB', 'card', 'BOB') RETURNING id INTO v;
  INSERT INTO finance.cards (account_id, user_id, institution_code, last4)
  VALUES (v, '00000000-0000-7000-8000-00000000000d', 'bo.bnb', '8765');
  BEGIN
    INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000d', 'Mastercard', 'card', 'USD');
    RAISE EXCEPTION 'FALLO: pasó el límite de tarjetas del plan';
  EXCEPTION WHEN SQLSTATE 'MM001' THEN
    IF SQLERRM <> 'Tu plan permite 2 tarjeta(s) y ya tienes 2' THEN RAISE; END IF;
  END;
  UPDATE finance.accounts SET archived_at = now() WHERE name = 'Visa BNB';
  INSERT INTO finance.accounts (user_id, name, type, currency) VALUES ('00000000-0000-7000-8000-00000000000d', 'Mastercard', 'card', 'USD');
  SELECT * INTO l FROM billing.limit_status('00000000-0000-7000-8000-00000000000d', 'finance.cards');
  IF l.limit_value <> 2 OR l.used <> 2 OR l.allowed
  OR (SELECT used FROM billing.limit_status('00000000-0000-7000-8000-00000000000d', 'finance.currencies')) <> 2 THEN
    RAISE EXCEPTION 'tarjetas en paid_1: %', row_to_json(l);
  END IF;
  RAISE NOTICE 'OK 65 con un plan de pago agrega tarjetas hasta su límite (2 en la prueba) y en otra moneda (USD); archivar una libera el cupo';
END $$;
RESET ROLE;

DO $$ BEGIN
  UPDATE finance.accounts SET type = 'cash' WHERE id = '00000000-0000-7000-8000-00000000ac03';
  RAISE EXCEPTION 'FALLO: cambió el tipo de una tarjeta con movimientos';
EXCEPTION WHEN check_violation THEN
  RAISE NOTICE 'OK 66 una cuenta con movimientos no cambia de tipo: "%"', SQLERRM;
END $$;

DO $$ DECLARE d uuid; BEGIN
  UPDATE finance.accounts SET is_default = true WHERE id = '00000000-0000-7000-8000-00000000ac03';
  UPDATE finance.accounts SET archived_at = now() WHERE id = '00000000-0000-7000-8000-00000000ac03';
  SELECT id INTO d FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000a' AND is_default;
  IF d IS DISTINCT FROM '00000000-0000-7000-8000-00000000ac01'
  OR (SELECT is_default FROM finance.accounts WHERE id = '00000000-0000-7000-8000-00000000ac03') THEN
    RAISE EXCEPTION 'cuenta por defecto tras archivar: %', d;
  END IF;
  SET CONSTRAINTS finance.accounts_one_default IMMEDIATE;
  SET CONSTRAINTS finance.accounts_one_default DEFERRED;
  RAISE NOTICE 'OK 68 al archivar la cuenta por defecto, pasa sola a la siguiente cuenta activa';
END $$;

DO $$ BEGIN
  DELETE FROM iam.users WHERE id = '00000000-0000-7000-8000-00000000000d';
  IF EXISTS (SELECT 1 FROM finance.accounts WHERE user_id = '00000000-0000-7000-8000-00000000000d')
  OR EXISTS (SELECT 1 FROM finance.user_currencies WHERE user_id = '00000000-0000-7000-8000-00000000000d') THEN
    RAISE EXCEPTION 'quedaron datos de Dani';
  END IF;
  RAISE NOTICE 'OK 67 borrar a un usuario borra en cascada sus cuentas, tarjetas y Mis monedas';
END $$;

DO $$ BEGIN
  BEGIN
    UPDATE iam.users SET status = 'pending_deletion' WHERE id = '00000000-0000-7000-8000-00000000000a';
    RAISE EXCEPTION 'aceptó un borrado pendiente sin fecha';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    UPDATE iam.users SET deletion_requested_at = now() WHERE id = '00000000-0000-7000-8000-00000000000a';
    RAISE EXCEPTION 'aceptó una cuenta activa con fecha de borrado';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  UPDATE iam.users SET status = 'pending_deletion', deletion_requested_at = now()
  WHERE id = '00000000-0000-7000-8000-00000000000a';
  RAISE NOTICE 'OK 69 el borrado pendiente va siempre con su fecha, y la fecha solo con el borrado pendiente';
END $$;

DO $$ BEGIN
  BEGIN
    UPDATE finance.user_settings SET planned_savings = 10.555 WHERE user_id = '00000000-0000-7000-8000-00000000000a';
    RAISE EXCEPTION 'aceptó un ahorro planificado con más decimales que la moneda';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  UPDATE finance.user_settings SET planned_savings = 10.55 WHERE user_id = '00000000-0000-7000-8000-00000000000a';
  RAISE NOTICE 'OK 70 el ahorro planificado respeta los decimales de la moneda principal';
END $$;

DO $$ BEGIN
  BEGIN
    UPDATE goals.goals SET target_amount = 5000.555 WHERE id = '00000000-0000-7000-8000-00000000a0a1';
    RAISE EXCEPTION 'aceptó un objetivo con más decimales que la moneda';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO goals.goal_contributions (user_id, goal_id, amount)
    VALUES ('00000000-0000-7000-8000-00000000000a', '00000000-0000-7000-8000-00000000a0a1', 10.555);
    RAISE EXCEPTION 'aceptó un aporte con más decimales que la moneda de la meta';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  RAISE NOTICE 'OK 71 el objetivo y los aportes de una meta respetan los decimales de su moneda';
END $$;

DO $$ BEGIN
  INSERT INTO goals.goal_contributions (user_id, goal_id, amount)
  VALUES ('00000000-0000-7000-8000-00000000000a', '00000000-0000-7000-8000-00000000a0a1', 4550);
  IF (SELECT status <> 'achieved' OR achieved_at IS NULL FROM goals.goals
      WHERE id = '00000000-0000-7000-8000-00000000a0a1') THEN
    RAISE EXCEPTION 'la meta llegó al objetivo y no quedó cumplida';
  END IF;
  RAISE NOTICE 'OK 72 una meta que llega a su objetivo queda cumplida';
END $$;

DO $$
DECLARE
  v_user     uuid := '00000000-0000-7000-8000-00000000000a';
  v_account  uuid;
  v_category uuid;
  v_rule     uuid;
BEGIN
  SELECT id INTO v_account FROM finance.accounts WHERE user_id = v_user AND currency = 'BOB' AND deleted_at IS NULL LIMIT 1;
  INSERT INTO finance.categories (user_id, kind, flow_group, name)
  VALUES (v_user, 'expense', 'lifestyle', 'Prueba 73') RETURNING id INTO v_category;
  INSERT INTO finance.recurring_rules (user_id, account_id, category_id, amount, description, frequency, start_date)
  VALUES (v_user, v_account, v_category, 10, 'Prueba', 'monthly', current_date) RETURNING id INTO v_rule;
  BEGIN
    UPDATE finance.categories SET deleted_at = now() WHERE id = v_category;
    RAISE EXCEPTION 'borró una categoría que usa un recurrente';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  UPDATE finance.recurring_rules SET deleted_at = now() WHERE id = v_rule;
  UPDATE finance.categories SET deleted_at = now() WHERE id = v_category;
  RAISE NOTICE 'OK 73 una categoría con recurrentes no se borra hasta quitarlos';

  BEGIN
    INSERT INTO finance.transactions (user_id, kind, account_id, category_id, amount, occurred_on, description)
    VALUES (v_user, 'expense', v_account, v_category, 10, current_date, 'Prueba');
    RAISE EXCEPTION 'registró un movimiento en una categoría borrada';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO finance.recurring_rules (user_id, account_id, category_id, amount, description, frequency, start_date)
    VALUES (v_user, v_account, v_category, 10, 'Prueba', 'monthly', current_date);
    RAISE EXCEPTION 'creó un recurrente en una categoría borrada';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  RAISE NOTICE 'OK 74 ni un movimiento ni un recurrente entran en una categoría borrada';
END $$;

DO $$
BEGIN
  PERFORM 1 FROM catalog.story_templates WHERE template_version = '1' AND key = 'summary';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'faltan las plantillas de la Money Story';
  END IF;
  RAISE NOTICE 'OK 75 las plantillas de la Money Story están cargadas';
END $$;

DO $$
DECLARE
  v_user     uuid := '00000000-0000-7000-8000-00000000000a';
  v_category uuid;
BEGIN
  INSERT INTO finance.categories (user_id, kind, flow_group, name)
  VALUES (v_user, 'expense', 'needs', 'Prueba 76') RETURNING id INTO v_category;
  INSERT INTO planning.budgets (user_id, category_id, currency, amount) VALUES (v_user, v_category, 'BOB', 400);
  BEGIN
    INSERT INTO planning.budgets (user_id, category_id, currency, amount) VALUES (v_user, v_category, 'BOB', 100);
    RAISE EXCEPTION 'aceptó dos presupuestos para la misma categoría y moneda';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO planning.budgets (user_id, category_id, currency, amount)
    SELECT v_user, id, 'BOB', 100 FROM finance.categories WHERE user_id = v_user AND kind = 'income' LIMIT 1;
    RAISE EXCEPTION 'aceptó un presupuesto en una categoría de ingreso';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  RAISE NOTICE 'OK 76 un presupuesto por categoría de gasto y moneda';

  UPDATE finance.categories SET deleted_at = now() WHERE id = v_category;
  PERFORM 1 FROM planning.budgets WHERE category_id = v_category AND deleted_at IS NULL;
  IF FOUND THEN
    RAISE EXCEPTION 'quedó un presupuesto vivo en una categoría borrada';
  END IF;
  RAISE NOTICE 'OK 77 borrar una categoría borra sus presupuestos';
END $$;

ROLLBACK;
\echo 'Todas las pruebas pasaron.'
