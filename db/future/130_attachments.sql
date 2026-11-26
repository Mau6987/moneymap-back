-- =============================================================================
-- MoneyMap · 130 · comprobantes y escaneo de facturas (FTR-030)
-- El archivo vive en Cloud Storage; aquí solo la referencia y el resultado OCR.
-- =============================================================================

CREATE TABLE finance.attachments (
  id             uuid        PRIMARY KEY DEFAULT core.uuid_v7(),
  user_id        uuid        NOT NULL REFERENCES iam.users (id) ON DELETE CASCADE,
  transaction_id uuid,
  object_key     text        NOT NULL UNIQUE,
  mime_type      text        NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/heic', 'application/pdf')),
  size_bytes     integer     NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
  ocr_status     text        NOT NULL DEFAULT 'none' CHECK (ocr_status IN ('none', 'pending', 'done', 'failed')),
  ocr_result     jsonb,      -- {"merchant": "…", "amount": 120.5, "date": "…", "confidence": 0.93}
  created_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  CONSTRAINT attachments_transaction_fk FOREIGN KEY (user_id, transaction_id)
                                        REFERENCES finance.transactions (user_id, id) ON DELETE SET NULL (transaction_id)
);
CREATE INDEX attachments_transaction_idx ON finance.attachments (user_id, transaction_id) WHERE transaction_id IS NOT NULL;

ALTER TABLE finance.attachments ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows   ON finance.attachments FOR ALL TO moneymap_app
  USING (user_id = (SELECT core.current_user_id())) WITH CHECK (user_id = (SELECT core.current_user_id()));
CREATE POLICY worker_all   ON finance.attachments FOR ALL TO moneymap_worker USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON finance.attachments TO moneymap_app, moneymap_worker;
