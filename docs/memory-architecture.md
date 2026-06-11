# Oha-Yachiyo Memory Architecture

本文整理后续“记忆”能力的产品与技术边界。当前项目已经有 SQLite 聊天记录，但它只是原始会话存档，不等于可召回、可共享、可管理的助手记忆。

记忆系统必须建立在当前 Oha-Yachiyo 产品合同之上：ChatSession 是用户可见 transcript，Task 是产品级任务合同，Run 是 Native Agent 执行记录。长期记忆不能替代 TaskRunner、ChatSession 或 NativeRunEngine，也不能引入第二套执行 runtime。

## 现状

- `apps.core.chat_store.ChatStore` 使用 SQLite 保存 `chat_sessions` 与 `chat_messages`。
- `apps.core.chat_session.ChatSession` 负责当前会话状态，并在重启后恢复当前会话消息。
- Chat Window、Bubble、Live2D 和 Control Center 共享同一个 ChatSession 视图。
- NativeAgentExecutor 会把产品 Task 映射到 Native Run，并通过 TaskRunLink 保留可追踪关系。
- RunEvent 是执行事实日志，用于 Run Detail、审批、工具调用和诊断 replay。
- 现有存储不做事实抽取、长期召回、跨会话筛选，也没有用户可编辑的记忆条目。

## 目标形态

记忆系统应保持本地优先，并分成四层：

1. 当前会话上下文
   - 用于持续对话。
   - 来源是当前 ChatSession、最近消息、当前 Task 和关联 Run 摘要。

2. 项目/目的上下文
   - 用户可以把会话归入一个项目或目的，例如“Oha-Yachiyo 开发”“日语学习”“个人日程”。
   - 项目上下文优先影响同项目的新会话，不自动污染所有对话。

3. 共享助手记忆
   - 类似 ChatGPT 的 Memory，用于跨会话共享稳定偏好、称呼、长期事实和工作习惯。
   - 必须能查看、编辑、禁用和删除。

4. 临时检索片段
   - 每次请求前从本地存储检索相关会话摘要、项目事实和共享记忆。
   - 只把相关片段注入模型上下文，不把整个历史聊天塞进请求。

## Runtime 边界

记忆不是新的执行层。它只给现有执行链提供上下文：

```text
Chat UI / Bubble / Live2D
→ ChatSession
→ TaskRunner / Task API
→ NativeAgentExecutor
→ NativeRunEngine
→ ModelProfile / ToolBroker / Approval / RunEvent
```

因此：

- MemoryStore 保存用户可管理的长期上下文。
- ChatSession 继续保存用户可见 transcript。
- TaskRunner 继续管理产品级任务生命周期。
- NativeRunEngine 继续管理模型、工具、审批、Run 和 RunEvent。
- RunEvent replay 可以生成候选摘要，但不成为长期记忆主存储。
- AstrBot 只通过本地 Bridge 读写显式授权的摘要/事实，不拥有独立记忆系统。

## 数据模型建议

继续使用 SQLite 作为第一阶段的控制层存储，避免为了 MVP 引入新依赖。

建议新增表：

| 表 | 用途 |
| ---- | ---- |
| `memory_items` | 保存可管理的长期记忆条目。字段包括 `memory_id`、`scope`、`kind`、`content`、`source_session_id`、`source_message_id`、`source_task_id`、`source_run_id`、`confidence`、`pinned`、`user_confirmed`、`created_at`、`updated_at`、`deleted_at`。 |
| `memory_projects` | 保存项目/目的上下文。字段包括 `project_id`、`name`、`description`、`created_at`、`updated_at`。 |
| `memory_project_sessions` | 建立会话与项目的关系。一个会话默认只属于一个项目，后续可扩展多项目标签。 |
| `memory_events` | 记录记忆创建、更新、删除、用户确认等审计事件。 |

`memory_items.scope` 建议取值：

| scope | 含义 |
| ---- | ---- |
| `global` | 跨所有会话共享的助手记忆。 |
| `project` | 仅在某个项目/目的下生效。 |
| `session` | 当前会话内的临时摘要或事实。 |

`memory_items.kind` 建议取值：

| kind | 含义 |
| ---- | ---- |
| `preference` | 用户偏好，例如回复语言、称呼、常用格式。 |
| `fact` | 稳定事实，例如项目背景、长期目标。 |
| `task` | 待办、承诺、长期任务线索。 |
| `summary` | 会话或项目摘要。 |

## 写入链路

1. 用户完成一轮对话、Agent Run 或 Workflow Run。
2. 记忆候选提取器读取 ChatSession、Task result、Run result 和 RunEvent replay。
3. 提取候选记忆：偏好、事实、项目线索、可复用总结。
4. 根据风险分级处理：
   - 低风险偏好可自动暂存为候选。
   - 涉及身份、隐私、账号、敏感内容的记忆必须等待用户确认。
5. 用户可在设置页查看、确认、编辑、禁用和删除。
6. 通过 `memory_events` 记录来源与操作。

写入链路不得绕过 secret redaction。候选内容进入 MemoryStore 前必须走和 ChatStore / RunEvent / artifact 一致的敏感信息清洗策略。

## 召回链路

1. 收到新的用户请求。
2. 判断当前会话所属项目/目的。
3. 检索相关 `global` 记忆、当前项目记忆、当前会话摘要和最近 Run 摘要。
4. 去重，避免同一条事实同时来自会话摘要、项目记忆和 RunEvent 摘要。
5. 按优先级组装模型上下文：
   - persona
   - user address
   - relevant shared memories
   - project context
   - current session summary
   - recent task/run facts
   - user request
6. 将组装后的请求交给现有 NativeRunEngine 执行路径。

召回链路只影响模型上下文，不改变 Task、Run 或 ChatSession 生命周期。

## 检索策略

第一阶段建议使用 SQLite FTS5 或普通关键词检索：

- 不引入 embedding 依赖。
- 使用 `kind`、`scope`、`project_id`、更新时间和关键词命中打分。
- 对短期 MVP 足够透明，也便于测试。

第二阶段再考虑可选本地 embedding：

- embedding 必须是可关闭能力。
- 向量文件仍保存在本地用户目录。
- 没有 embedding 时系统应自动回退关键词检索。

## 用户体验

- 主设置增加“记忆”区域，默认显示当前状态、共享记忆数量、项目数量。
- 提供“管理记忆”入口，用户可以搜索、编辑、禁用、删除记忆。
- 新建会话时可选择“普通对话”或某个项目/目的。
- Chat、Bubble 和 Live2D 共享同一套记忆召回结果。
- AstrBot 只转发和查询本地 Bridge，不拥有独立记忆脑。
- 默认不把远程聊天自动写入全局记忆，除非用户启用或确认。

## 安全与默认值

- 共享记忆应默认关闭或以“候选待确认”模式启动。
- 删除记忆必须软删除并记录事件，后续再提供清理按钮。
- 高风险内容不得自动写入长期记忆。
- Bridge 只能操作本地 Oha-Yachiyo 暴露的记忆 API，AstrBot 不直接读写 SQLite。
- MemoryStore、ChatStore、RunEvent 和 ActivityStore 的用户可见内容必须保持一致的 secret redaction 边界。

## MVP 切分

1. 新增 `MemoryStore` 控制层表。
2. 给会话增加可选 `project_id`，并提供项目列表。
3. 增加手动记忆管理 API 和 UI，先不做自动抽取。
4. 在 NativeAgentExecutor 构造模型上下文前注入用户确认的记忆片段。
5. 增加低风险自动候选记忆提取。
6. 从 RunEvent replay 生成可确认的会话/项目摘要候选。
7. 再评估本地 embedding 检索。
