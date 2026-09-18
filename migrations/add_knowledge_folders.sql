BEGIN;

CREATE TABLE IF NOT EXISTS t_knowledge_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id UUID NOT NULL REFERENCES t_knowledge_bases(id) ON DELETE CASCADE,
    parent_id UUID NULL REFERENCES t_knowledge_folders(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    created_by UUID NULL REFERENCES t_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE t_documents ADD COLUMN IF NOT EXISTS folder_id UUID NULL REFERENCES t_knowledge_folders(id) ON DELETE SET NULL;
ALTER TABLE t_documents ADD COLUMN IF NOT EXISTS created_by UUID NULL REFERENCES t_users(id);

CREATE INDEX IF NOT EXISTS ix_knowledge_folders_knowledge_base_id ON t_knowledge_folders(knowledge_base_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_folders_parent_id ON t_knowledge_folders(parent_id);
CREATE INDEX IF NOT EXISTS ix_documents_folder_id ON t_documents(folder_id);
CREATE INDEX IF NOT EXISTS ix_documents_created_by ON t_documents(created_by);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_folder_sibling_name
    ON t_knowledge_folders (knowledge_base_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name));

COMMIT;
