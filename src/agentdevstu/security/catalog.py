"""Permission codes are executable API contracts, not arbitrary menu labels."""

SYSTEM = {
    "users.manage": "用户管理",
    "roles.manage": "角色管理",
    "workspaces.create": "创建工作空间",
    "config.manage": "系统配置",
    "audit.read": "查看安全审计",
    "identity.manage": "外部身份配置",
}
SPACE = {
    "workspace.manage": "管理空间设置",
    "members.manage": "管理空间成员与授权",
    "agent.read": "查看 Agent 配置",
    "agent.create": "创建 Agent",
    "agent.update": "编辑 Agent",
    "agent.delete": "删除 Agent",
    "agent.publish": "发布 Agent",
    "agent.use": "使用获授权的已发布 Agent",
    "agent.operate": "运维 Agent（知识库、工具、数据、记忆）",
    "knowledge.manage": "管理知识库",
    "knowledge.use": "使用知识库",
    "data.manage": "管理数据源与数据能力",
    "tools.manage": "管理工具",
    "workflows.manage": "管理工作流",
    "tasks.manage": "管理自己的任务",
    "meeting.use": "创建和使用自己的会议",
    "memory.manage": "管理自己的记忆",
}
PERMISSIONS = {**SYSTEM, **SPACE}
BUILTINS = [
    ("user_admin", "用户管理员", "system", ["users.manage"]),
    ("space_admin", "工作空间管理员", "workspace", list(SPACE)),
    (
        "agent_developer",
        "Agent 开发者",
        "workspace",
        [
            "agent.read",
            "agent.create",
            "agent.update",
            "agent.use",
            "agent.operate",
            "knowledge.manage",
            "meeting.use",
            "memory.manage",
        ],
    ),
    ("member", "普通使用者", "workspace", ["agent.use", "meeting.use", "memory.manage", "knowledge.use"]),
]
