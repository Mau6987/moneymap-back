-- =============================================================================
-- Exporta el esquema a DBML para verlo en https://dbdiagram.io
-- Uso: psql -d moneymap -At -f tools/export_dbml.sql > docs/moneymap.dbml
-- Solo tablas, columnas, claves y relaciones: sin triggers, funciones ni
-- particiones (dbdiagram no las entiende). Un grupo de color por módulo.
-- =============================================================================
WITH schemas (nspname, color) AS (
  VALUES ('iam', '#2563EB'), ('billing', '#7C3AED'), ('catalog', '#64748B'), ('finance', '#16A34A'),
         ('goals', '#0D9488'), ('planning', '#0891B2'), ('reports', '#EA580C'), ('notify', '#DB2777'),
         ('ai', '#C026D3'), ('ops', '#DC2626'), ('core', '#475569')
),
tbl AS (
  SELECT c.oid, n.nspname, c.relname, s.color, obj_description(c.oid, 'pg_class') AS note
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN schemas s ON s.nspname = n.nspname
  WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
),
pk AS (
  SELECT conrelid, conkey FROM pg_constraint WHERE contype = 'p'
),
col AS (
  SELECT t.oid,
         string_agg(format('  %I %s%s', a.attname, quote_ident(format_type(a.atttypid, a.atttypmod)),
                           CASE WHEN array_length(p.conkey, 1) = 1 AND a.attnum = p.conkey[1] THEN ' [pk]'
                                WHEN a.attnotnull THEN ' [not null]' ELSE '' END),
                    E'\n' ORDER BY a.attnum) AS cols
  FROM tbl t
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
  LEFT JOIN pk p ON p.conrelid = t.oid
  GROUP BY t.oid
),
cpk AS (   -- claves primarias compuestas
  SELECT t.oid,
         format(E'\n  indexes {\n    (%s) [pk]\n  }',
                (SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY k.ord)
                 FROM unnest(p.conkey) WITH ORDINALITY k (attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum)) AS idx
  FROM tbl t JOIN pk p ON p.conrelid = t.oid
  WHERE array_length(p.conkey, 1) > 1
),
tables AS (
  SELECT format(E'Table %I.%I [headercolor: %s] {\n%s%s%s\n}',
                t.nspname, t.relname, t.color, c.cols, coalesce(k.idx, ''),
                CASE WHEN t.note IS NOT NULL THEN format(E'\n  Note: ''%s''', replace(t.note, '''', '\''')) ELSE '' END
         ) AS dbml, t.nspname, t.relname
  FROM tbl t JOIN col c ON c.oid = t.oid LEFT JOIN cpk k ON k.oid = t.oid
),
refs AS (
  SELECT format('Ref: %I.%I.%s > %I.%I.%s',
                sn.nspname, sc.relname, src.cols, tn.nspname, tc.relname, dst.cols) AS dbml
  FROM pg_constraint f
  JOIN pg_class sc ON sc.oid = f.conrelid JOIN pg_namespace sn ON sn.oid = sc.relnamespace
  JOIN pg_class tc ON tc.oid = f.confrelid JOIN pg_namespace tn ON tn.oid = tc.relnamespace
  -- una columna: tabla.col · varias: tabla.(a, b)
  CROSS JOIN LATERAL (
    SELECT CASE WHEN count(*) = 1 THEN min(quote_ident(a.attname))
                ELSE '(' || string_agg(quote_ident(a.attname), ', ' ORDER BY k.ord) || ')' END AS cols
    FROM unnest(f.conkey) WITH ORDINALITY k (attnum, ord)
    JOIN pg_attribute a ON a.attrelid = f.conrelid AND a.attnum = k.attnum) src
  CROSS JOIN LATERAL (
    SELECT CASE WHEN count(*) = 1 THEN min(quote_ident(a.attname))
                ELSE '(' || string_agg(quote_ident(a.attname), ', ' ORDER BY k.ord) || ')' END AS cols
    FROM unnest(f.confkey) WITH ORDINALITY k (attnum, ord)
    JOIN pg_attribute a ON a.attrelid = f.confrelid AND a.attnum = k.attnum) dst
  WHERE f.contype = 'f' AND f.conparentid = 0
    AND sn.nspname IN (SELECT nspname FROM schemas)
    AND NOT sc.relispartition AND NOT tc.relispartition
),
groups AS (
  SELECT format(E'TableGroup %s {\n%s\n}', t.nspname,
                string_agg(format('  %I.%I', t.nspname, t.relname), E'\n' ORDER BY t.relname)) AS dbml
  FROM tbl t GROUP BY t.nspname
)
SELECT string_agg(dbml, E'\n\n') FROM (
  SELECT dbml, 1 AS ord, nspname AS a, relname AS b FROM tables
  UNION ALL SELECT dbml, 2, dbml, '' FROM refs
  UNION ALL SELECT dbml, 3, dbml, '' FROM groups
  ORDER BY ord, a, b
) all_parts;
