-- 项目-Agent 权限授权（2026-11-18）。执行于单事务。
-- 一个项目可授权给多个 Agent，level: use（仅查看项目与关联工作）| manage（另可改名称/截止时间、派发关联工作）。
-- 两个外键均 ON DELETE CASCADE：项目/Agent 删除时授权自动清理，工作区删除预清理链无需改动。
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS t_project_agent_grants (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES t_workspaces(id),
    project_id uuid NOT NULL,
    agent_id uuid NOT NULL REFERENCES t_agents(id) ON DELETE CASCADE,
    level varchar(16) NOT NULL DEFAULT 'use' CHECK (level IN ('manage','use')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_project_agent_grants_project FOREIGN KEY (workspace_id, project_id)
        REFERENCES t_projects (workspace_id, id) ON DELETE CASCADE,
    CONSTRAINT uq_project_agent_grants UNIQUE (project_id, agent_id)
);
CREATE INDEX IF NOT EXISTS ix_project_agent_grants_agent ON t_project_agent_grants (agent_id);
COMMIT;
