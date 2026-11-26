-- =============================================================================
-- Estructura del esquema en JSON, para generar DICCIONARIO_CAMPOS.md:
--   psql -d moneymap -At -f tools/dictionary.sql | python tools/build_dictionary.py > DICCIONARIO_CAMPOS.md
-- Lee tablas, columnas, claves, relaciones, triggers, vistas, funciones y sus
-- comentarios (migrations/990_comments.sql) desde el catálogo de PostgreSQL.
-- =============================================================================
WITH sch AS (
  SELECT unnest(ARRAY['iam', 'billing', 'catalog', 'finance', 'goals', 'planning', 'reports', 'notify', 'ai', 'ops', 'core']) AS nspname
),
tbl AS (
  SELECT c.oid, n.nspname, c.relname, c.relkind = 'p' AS partitioned
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN sch USING (nspname)
  WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
),
cols AS (
  SELECT a.attrelid, a.attnum,
         jsonb_build_object(
           'name', a.attname,
           'type', format_type(a.atttypid, a.atttypmod),
           'enum', (SELECT jsonb_agg(e.enumlabel ORDER BY e.enumsortorder) FROM pg_enum e WHERE e.enumtypid = a.atttypid),
           'notnull', a.attnotnull,
           'generated', a.attgenerated <> '',
           'default', pg_get_expr(d.adbin, d.adrelid),
           'comment', col_description(a.attrelid, a.attnum)) AS j
  FROM pg_attribute a
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  WHERE a.attrelid IN (SELECT oid FROM tbl) AND a.attnum > 0 AND NOT a.attisdropped
),
cons AS (
  SELECT k.conrelid,
         jsonb_build_object(
           'type', k.contype,
           'cols', (SELECT jsonb_agg(a.attname ORDER BY x.o) FROM unnest(k.conkey) WITH ORDINALITY x (n, o)
                    JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = x.n),
           'ref_table', CASE WHEN k.contype = 'f' THEN k.confrelid::regclass::text END,
           'ref_cols', (SELECT jsonb_agg(a.attname ORDER BY x.o) FROM unnest(k.confkey) WITH ORDINALITY x (n, o)
                        JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = x.n),
           'on_delete', k.confdeltype) AS j
  FROM pg_constraint k
  WHERE k.conrelid IN (SELECT oid FROM tbl) AND k.contype IN ('p', 'f', 'u') AND k.conparentid = 0
),
uidx AS (   -- índices únicos que no son restricción (por ejemplo, parciales)
  SELECT i.indrelid,
         jsonb_build_object('type', 'u',
           'cols', (SELECT jsonb_agg(coalesce(a.attname, '(expresión)') ORDER BY x.o) FROM unnest(i.indkey) WITH ORDINALITY x (n, o)
                    LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = x.n),
           'where', pg_get_expr(i.indpred, i.indrelid)) AS j
  FROM pg_index i
  WHERE i.indrelid IN (SELECT oid FROM tbl) AND i.indisunique AND NOT i.indisprimary
    AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)
),
trg AS (
  SELECT t.tgrelid,
         jsonb_build_object('name', t.tgname, 'function', p.oid::regproc::text,
                            'comment', obj_description(p.oid, 'pg_proc')) AS j
  FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
  WHERE t.tgrelid IN (SELECT oid FROM tbl) AND NOT t.tgisinternal
),
tables AS (
  SELECT jsonb_agg(jsonb_build_object(
           'schema', t.nspname, 'name', t.relname, 'partitioned', t.partitioned,
           'comment', obj_description(t.oid, 'pg_class'),
           'rls', (SELECT relrowsecurity FROM pg_class WHERE oid = t.oid),
           'columns', (SELECT jsonb_agg(j ORDER BY attnum) FROM cols WHERE attrelid = t.oid),
           'constraints', coalesce((SELECT jsonb_agg(j) FROM cons WHERE conrelid = t.oid), '[]')
                          || coalesce((SELECT jsonb_agg(j) FROM uidx WHERE indrelid = t.oid), '[]'),
           'triggers', coalesce((SELECT jsonb_agg(j ORDER BY j ->> 'name') FROM trg WHERE tgrelid = t.oid), '[]'))
         ORDER BY t.nspname, t.relname) AS j
  FROM tbl t
),
views AS (
  SELECT jsonb_agg(jsonb_build_object('name', n.nspname || '.' || c.relname, 'comment', obj_description(c.oid, 'pg_class'))
                   ORDER BY n.nspname, c.relname) AS j
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN sch USING (nspname)
  WHERE c.relkind = 'v'
),
funcs AS (   -- funciones con descripción que no son de triggers
  SELECT jsonb_agg(jsonb_build_object('name', p.oid::regprocedure::text, 'comment', obj_description(p.oid, 'pg_proc'))
                   ORDER BY n.nspname, p.proname) AS j
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN sch USING (nspname)
  WHERE obj_description(p.oid, 'pg_proc') IS NOT NULL AND p.prorettype <> 'trigger'::regtype
),
enums AS (
  SELECT jsonb_agg(jsonb_build_object('name', t.typnamespace::regnamespace || '.' || t.typname,
                                      'values', (SELECT jsonb_agg(enumlabel ORDER BY enumsortorder) FROM pg_enum WHERE enumtypid = t.oid),
                                      'comment', obj_description(t.oid, 'pg_type'))) AS j
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace JOIN sch USING (nspname)
  WHERE t.typtype = 'e'
)
SELECT jsonb_build_object('tables', (SELECT j FROM tables), 'views', (SELECT j FROM views),
                          'functions', (SELECT j FROM funcs), 'enums', (SELECT j FROM enums));
