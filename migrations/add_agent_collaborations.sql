-- Agent Collaboration 表
-- 记录 Agent 之间的 @协作调用，用于审计和追踪

CREATE TABLE IF NOT EXISTS t_agent_collaborations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES t_conversations(id) ON DELETE CASCADE,
    source_agent_id UUID NOT NULL REFERENCES t_agents(id) ON DELETE CASCADE,
    target_agent_id UUID NOT NULL REFERENCES t_agents(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    known_facts JSONB,
    question TEXT NOT NULL,
    constraints JSONB,
    expected_output TEXT,
    status VARCHAR(32) DEFAULT 'pending',
    result_summary TEXT,
    result_content TEXT,
    result_sources JSONB,
    confidence FLOAT,
    duration_ms INTEGER,
    error_message TEXT,
    call_depth INTEGER DEFAULT 1,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collab_conversation ON t_agent_collaborations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_collab_source_agent ON t_agent_collaborations(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_collab_target_agent ON t_agent_collaborations(target_agent_id);
CREATE INDEX IF NOT EXISTS idx_collab_status ON t_agent_collaborations(status);
