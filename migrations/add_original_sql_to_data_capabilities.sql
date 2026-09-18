BEGIN;

ALTER TABLE t_data_capabilities
    ADD COLUMN IF NOT EXISTS original_sql TEXT NULL;

UPDATE t_data_capabilities
SET original_sql = query_template
WHERE original_sql IS NULL AND query_template IS NOT NULL;

COMMENT ON COLUMN t_data_capabilities.original_sql IS
    '用户录入的原始只读 SQL，保留用于查看、测试和再次 AI 改写';

COMMIT;
