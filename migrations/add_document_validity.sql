BEGIN;

ALTER TABLE t_documents
    ADD COLUMN IF NOT EXISTS valid_until DATE NULL;

COMMENT ON COLUMN t_documents.valid_until IS
    '有效期截止日期（含当天），NULL 表示永久有效';

CREATE INDEX IF NOT EXISTS ix_documents_knowledge_base_valid_until
    ON t_documents (knowledge_base_id, valid_until);

COMMIT;
