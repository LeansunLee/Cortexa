# Knowledge Retrieval 相关性控制（2026-10-08）

## Changed

复用现有 Retrieval Planner、Metadata JSON、RAG 召回、UTF-8 保守 Context Budget 和 Runtime Trace。
未修改业务表结构，未执行 Migration，未新增 Embedding / Reranker 模型。

### 查询与实体

- Planner 入口提供核心实体、业务意图、资料类型和未确定项。
- 先在已授权文档元数据中解析业务 ID 和声明的别名，再解析完整车型/版本标记。
  `金吉拉250`、`金吉拉250CVT`、`金吉拉2500`、其他车型不互认为同一实体。
- 业务 ID 区分声明的实体类型/命名空间；别名歧义、正文或文件名冲突保留不确定性。
- 没有可靠登记信息的名字保留原约束，不把问题改写成其他车型或系列。
- Query Expansion 只增加业务同义词，保留原查询实体文本。
  Multi-Query 不再自由生成变体；原 HyDE 配置入口保留向量召回通道，但使用受约束查询，不再生成假设事实扩展实体。

### 候选与证据

先读取授权、有效的候选（元数据命中不依赖显式关键词），再进行实体过滤、重排和 Evidence Gate。
原始 lexical / BM25 / cosine / RRF 分数保留用于同等级排序，不以一个未经校准的数值跨算法截断。
入选由实体身份、意图支持、资料类型与案例状态等可解释特征决定：

| 等级 | 用途 |
| --- | --- |
| DIRECT | 支持资料明确覆盖的目标事实，不外推未覆盖对象 |
| RELATED | 方法、政策框架、比较参考，不作为目标实体事实或真实案例 |
| BACKGROUND | 按明确需求提供背景，不支持目标事实 |
| IRRELEVANT | 不注入 |

- 同系列参考只在明确比较/系列范围下选择，不放宽精确实体约束。
- 公司介绍、手册不会因几个通用词而成为真实促销案例。
- 案例缺少执行支持、属于模板/假设/待执行时不能提升为 DIRECT。
- Top K 是上限；先放直接证据，相关/背景按需求最多各 2 份，预算不够则跳过并记录原因。
- 注入文段亦校验实体；不能把同文档中另一版本的案例片段借给目标车型。
- 无直接证据或多实体请求覆盖不全时返回 `Evidence Insufficient`，不拿参考资料补足事实。
- Knowledge 缓存加入规则版本，避免沿用旧门槛的缓存；已有识别中/读取失败状态保持原执行语义。

### 可复用元数据（现有 JSON 字段；无需 Schema 变更）

```json
{
  "retrieval": {
    "entities": [
      {"type": "model", "id": "业务ID", "name": "完整名称", "aliases": ["明确别名"], "family": "系列"}
    ],
    "intents": ["clearance"],
    "document_type": "case",
    "case_status": "completed",
    "evidence_status": "verified"
  }
}
```

兼容已有顶层 `entities`、`entity_id`、`model_id`、`entity_name`、`model_name`、`entity_aliases` 等声明。
意图包括 clearance / inventory / pricing / policy / marketing / sales / specification；资料类型包括
case / policy / manual / report / profile。未定义类型不擅自映射。元数据不自动回填业务 ID 或别名。

### Debug 与权限

- Runtime Trace 展示查询解析、实体约束、授权召回数、每个候选原始分数及算法、重排分数、等级、
  过滤原因、实际注入内容与预算。协作 LLM 的检索诊断也进入主流程调试记录。
- 来源标签标注直接证据/相关参考/背景，悬停展示用途；正文保留同样的标记。
- 只有现有对话调试权限允许读取完整诊断；实体登记表只取当前 Agent 有权访问的文档。
- 普通对话沿用已有受限调试展示，完整请求也可在已授权的 Prompt 浮层查看。

## Tests

- 精确车型、CVT/未知版本、同系列、其他车型、系列范围及 ID 命名空间冲突。
- ID/别名优先、别名歧义、无关键词元数据命中、同义词扩展不改变实体。
- 无直接案例、模板/假设资料、正文范围冲突、低分候选、Top K 不凑数。
- 不同评分量纲、BM25 零分元数据召回、各 RAG 策略原始实体约束。
- Context Budget、直接证据优先、背景显式需求、窗口实体校验。
- 隔离 PostgreSQL 的真实 BM25 / Runtime Trace / 私有 Agent 资料权限回归。
- 开发库只读回放：原“金吉拉250 库存 去库存 活动 促销 案例”查询从 10 个来源变为 2 个 RELATED，
  DIRECT 为 0，明确证据不足，公司介绍被过滤。未触发模型或业务查询。

## Remaining Issues

- 缺少可靠 ID、别名、资料类型或执行状态的文档会保守降级，可能减少召回；需要完善已有元数据。
- 自由文本复合条件与 OCR 错误仍有确定性解析边界；本次没有增加语义模型或真实性审批流程。
- 文档级混合事实/模板会保守处理；未引入逐句证据审核。
- 既有 `test_settings_merge_publication_and_policy_revocation` 测试夹具未提供必填业务角色，
  在 Agent 更新时返回 422；与本次检索修改无关，本轮未修改该业务模块。
