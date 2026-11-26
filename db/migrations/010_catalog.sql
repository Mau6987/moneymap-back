-- =============================================================================
-- MoneyMap · 010 · catalog
-- Datos de referencia compartidos por todos los usuarios: monedas, países,
-- instituciones financieras, tipos de cuenta, grupos del Money Flow y
-- plantillas de categorías iniciales.
-- MoneyMap no convierte monedas.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS catalog;
COMMENT ON SCHEMA catalog IS 'Datos de referencia globales (no pertenecen a ningún usuario).';

-- Tipo de movimiento. Es una lista fija (ENUM) porque no cambia nunca:
--   income   ingreso: suma al saldo
--   expense  gasto: resta del saldo
--   transfer transferencia entre dos cuentas del usuario (solo en transacciones)
CREATE TYPE catalog.money_kind AS ENUM ('income', 'expense', 'transfer');
COMMENT ON TYPE catalog.money_kind IS 'income suma al saldo, expense resta, transfer mueve entre dos cuentas propias.';

-- -----------------------------------------------------------------------------
-- Monedas
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.currencies (
  code       char(3)  PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),   -- ISO 4217
  name       text     NOT NULL,
  symbol     text     NOT NULL,
  decimals   smallint NOT NULL DEFAULT 2 CHECK (decimals BETWEEN 0 AND 4),   -- BOB 2, CLP 0
  is_active  boolean  NOT NULL DEFAULT true,     -- false = no se ofrece para cuentas nuevas
  sort_order smallint NOT NULL DEFAULT 100        -- orden en el selector, después de "Mis monedas"
);
COMMENT ON TABLE catalog.currencies IS
  'Monedas ISO 4217 que ofrece la app. Agregar una es un INSERT; desactivarla la oculta para datos nuevos y conserva los existentes.';
COMMENT ON COLUMN catalog.currencies.decimals IS
  'Cuántos decimales acepta un monto en esta moneda: BOB y USD 2, CLP y PYG 0. 1000,5 pesos chilenos se rechaza.';

-- Valida que una moneda esté activa antes de usarla en una cuenta, una meta,
-- la moneda principal o "Mis monedas". Los datos guardados con una moneda que
-- luego se desactiva siguen siendo válidos.
CREATE OR REPLACE FUNCTION catalog.assert_currency_active(p_code char(3)) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM catalog.currencies WHERE code = p_code AND is_active) THEN
    RAISE EXCEPTION 'La moneda % no está disponible', p_code
      USING ERRCODE = 'check_violation', HINT = 'currency_unavailable';
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- Países (ISO 3166-1) e instituciones financieras de cada país
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.countries (
  code       char(2)  PRIMARY KEY CHECK (code ~ '^[A-Z]{2}$'),   -- ISO 3166-1: BO, AR…
  name       text     NOT NULL,
  currency   char(3)  REFERENCES catalog.currencies (code),     -- moneda local
  is_active  boolean  NOT NULL DEFAULT true,
  sort_order smallint NOT NULL DEFAULT 100
);

-- Bancos, cooperativas y billeteras que emiten tarjetas. La app muestra la
-- lista del país del usuario en vez de pedir el nombre del banco como texto.
CREATE TABLE catalog.financial_institutions (
  code         text     PRIMARY KEY CHECK (code ~ '^[a-z]{2}\.[a-z0-9_]+$'),   -- 'bo.bnb'
  country_code char(2)  NOT NULL REFERENCES catalog.countries (code),
  name         text     NOT NULL,                       -- Banco Nacional de Bolivia
  short_name   text     NOT NULL,                       -- BNB
  kind         text     NOT NULL DEFAULT 'bank' CHECK (kind IN ('bank', 'cooperative', 'microfinance', 'fintech')),
  is_active    boolean  NOT NULL DEFAULT true,
  sort_order   smallint NOT NULL DEFAULT 100,
  CONSTRAINT financial_institutions_name_uq UNIQUE (country_code, short_name)
);
CREATE INDEX financial_institutions_country_idx ON catalog.financial_institutions (country_code, sort_order) WHERE is_active;

-- -----------------------------------------------------------------------------
-- Tipos de cuenta: efectivo y tarjeta. "¿Pagué en efectivo o con tarjeta?" se
-- responde con is_card. No se distingue débito de crédito.
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.account_types (
  code       text     PRIMARY KEY CHECK (code ~ '^[a-z_]+$'),
  names      jsonb    NOT NULL CHECK (names ? 'es'),    -- {"es": "Efectivo", "en": "Cash"}
  icon       text     NOT NULL,
  is_card    boolean  NOT NULL DEFAULT false,   -- tarjeta: cuenta para el límite 'finance.cards' del plan
  sort_order smallint NOT NULL DEFAULT 0,
  is_active  boolean  NOT NULL DEFAULT true
);

-- Grupo del Money Flow al que va cada categoría de gasto. Lista fija:
--   needs      Necesidades (alquiler, supermercado, transporte…)
--   lifestyle  Estilo de vida (restaurantes, suscripciones, compras…)
-- Los ingresos no llevan grupo. El nombre y el color que se muestran viven en la app.
CREATE TYPE catalog.flow_group AS ENUM ('needs', 'lifestyle');
COMMENT ON TYPE catalog.flow_group IS 'Grupo de gasto del Money Flow: needs (Necesidades) o lifestyle (Estilo de vida).';

-- -----------------------------------------------------------------------------
-- Plantillas de categorías: se copian a cada usuario nuevo, que puede
-- editarlas sin afectar a otros. Solo categorías, sin subcategorías.
-- -----------------------------------------------------------------------------
CREATE TABLE catalog.category_templates (
  key        text               PRIMARY KEY CHECK (key ~ '^[a-z0-9_]+$'),
  kind       catalog.money_kind NOT NULL CHECK (kind IN ('income', 'expense')),
  flow_group catalog.flow_group,                                          -- solo en gastos
  names      jsonb              NOT NULL CHECK (names ? 'es'),           -- {"es": "Comida", "en": "Food"}
  icon       text               NOT NULL,
  color      text               NOT NULL CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  sort_order smallint           NOT NULL DEFAULT 0,
  is_active  boolean            NOT NULL DEFAULT true,
  CONSTRAINT category_templates_flow_chk CHECK ((kind = 'expense') = (flow_group IS NOT NULL))
);
COMMENT ON TABLE catalog.category_templates IS 'Categorías iniciales (FTR-005, FTR-031). Cada gasto lleva su grupo del Money Flow.';
