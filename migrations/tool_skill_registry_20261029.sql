-- 工具与技能体系（Tools & Skills）加列迁移。单事务执行。
-- 设计提案：docs/TOOL_SKILL_DESIGN_PROPOSAL_20261028.md（已批准）
-- 变更：t_tools 扩展为工具注册表；新建 t_skills；t_agents 增加 skill_ids 绑定。
BEGIN;
SET LOCAL lock_timeout = '5s';

-- 1) t_tools 注册表化（保留原列；web_search 开关行由 configure_search 继续使用）
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS provider_type varchar(16) NOT NULL DEFAULT 'builtin';
COMMENT ON COLUMN t_tools.provider_type IS '提供方类型：builtin(内置函数)|http(HTTP API)|mcp(MCP服务器)';
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS endpoint jsonb NOT NULL DEFAULT '{}';
COMMENT ON COLUMN t_tools.endpoint IS '调用端点：http={url,method,auth...}; mcp={url,command...}; builtin={}';
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS auth_secret_enc text;
COMMENT ON COLUMN t_tools.auth_secret_enc IS '加密凭证（Fernet），永不回传前端';
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS manifest jsonb NOT NULL DEFAULT '{}';
COMMENT ON COLUMN t_tools.manifest IS '工具清单：参数定义/风险级/超时/配额/使用规则等';
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS health_status varchar(16) NOT NULL DEFAULT 'unknown';
COMMENT ON COLUMN t_tools.health_status IS '健康状态：unknown|healthy|unhealthy';
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS health_checked_at timestamptz;
ALTER TABLE t_tools ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES t_users(id);
CREATE INDEX IF NOT EXISTS ix_t_tools_workspace_id ON t_tools(workspace_id);
CREATE INDEX IF NOT EXISTS ix_t_tools_status ON t_tools(status);

-- 2) 技能库（正文存文件系统，DB 存元数据与摘要）
CREATE TABLE IF NOT EXISTS t_skills (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES t_workspaces(id),
  name varchar(100) NOT NULL,
  description text NOT NULL DEFAULT '',
  instructions_path text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  tool_ids jsonb NOT NULL DEFAULT '[]',
  status varchar(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  version integer NOT NULL DEFAULT 1,
  created_by uuid REFERENCES t_users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE t_skills IS '技能库 - 程序性知识包（SOP），按需注入提示词；正文存文件系统';
CREATE INDEX IF NOT EXISTS ix_t_skills_workspace_id ON t_skills(workspace_id);

-- 3) Agent 技能绑定（与 tool_ids 对称）
ALTER TABLE t_agents ADD COLUMN IF NOT EXISTS skill_ids jsonb NOT NULL DEFAULT '[]';
COMMENT ON COLUMN t_agents.skill_ids IS '绑定的技能 ID 列表';

COMMIT;
