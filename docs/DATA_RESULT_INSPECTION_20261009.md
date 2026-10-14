# 查询返回内容查看

- 执行记录的 DATA 结果增加「查看数据」，按需读取私有 Goal 快照；不重新查询业务数据库。
- 根 Agent 与协作 LLM Agent 递归按 action_id 精确定位，支持已保存的历史结果。没有保存的记录返回明确提示。
- 表格每页 50 条，接口最多 100 条，支持当前页 JSON、空结果和截断说明。
- 每次读取重新检查对话所有权、主 Agent 使用权、实际执行 Agent 使用权和当前数据能力绑定；能力必须 active 且同工作区。响应 no-store，不返回 SQL、连接配置、凭证或整份快照。
- 未保存外部 Proxy 内部工具结果明细的步骤无法补造记录。
- 无 Schema/Migration 变更。

## 验证

44 项测试通过（test_data_results、test_goal_loop）。浏览器桌面和窄屏验证历史入口、按需加载、失败重试、分页、文本转义、Esc 与焦点恢复。前端构建通过。

## 回滚

开发服务器部署前备份 api/router.py、api/goals.py、runtime/loop.py 与 static/dist；恢复并重启服务即可。新 data_results.py 未被路由引用时不会生效。
