-- 对话产出物：Agent 在对话中生成的可交付文档（全文存文件系统，DB 只存元数据）
-- 部署：psql -h 127.0.0.1 -U agentdevstu -d agentdevstu -f migrations/add_conversation_artifacts.sql
CREATE TABLE IF NOT EXISTS t_conversation_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    conversation_id UUID NOT NULL REFERENCES t_conversations(id) ON DELETE CASCADE,
    message_id UUID REFERENCES t_conversation_messages(id) ON DELETE SET NULL,
    owner_user_id UUID NOT NULL,
    agent_id UUID,
    title VARCHAR(200) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    format VARCHAR(20) NOT NULL DEFAULT 'markdown',
    byte_size INTEGER NOT NULL DEFAULT 0,
    content_sha256 CHAR(64),
    path TEXT NOT NULL,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT ck_conversation_artifacts_format CHECK (format IN ('markdown', 'text'))
);
CREATE INDEX IF NOT EXISTS idx_conversation_artifacts_workspace ON t_conversation_artifacts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conversation_artifacts_conversation ON t_conversation_artifacts(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_artifacts_owner ON t_conversation_artifacts(owner_user_id);
