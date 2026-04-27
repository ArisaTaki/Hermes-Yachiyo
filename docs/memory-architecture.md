# Hermes-Yachiyo Memory Architecture

本文整理后续“记忆”能力的产品与技术边界。当前项目已经有 SQLite 聊天记录，但它只是原始会话存档，不等于可召回、可共享、可管理的助手记忆。

如果 Hermes Agent 已经提供自己的记忆链路，Hermes-Yachiyo 不应重新实现一套与之竞争的 agent memory。Yachiyo 的职责应优先是本地桌面侧的记忆控制层：管理用户授权、项目/目的归类、可视化编辑、Bridge 边界和 prompt 注入策略；真正的长期记忆读写应优先通过 Hermes 原生能力或适配器完成。

## 现状

- `apps.core.chat_store.ChatStore` 使用 SQLite 保存 `chat_sessions` 与 `chat_messages`。
- `apps.core.chat_session.ChatSession` 负责当前会话状态，并在重启后恢复当前会话消息与 Hermes session id。
- Chat Window、Bubble、Live2D 和 Control Center 共享同一个 `ChatSession`，因此它们看到的是同一条当前对话链。
- 现有存储不做事实抽取、长期召回、跨会话筛选，也没有用户可编辑的记忆条目。

## 目标形态

记忆系统应保持本地优先，并分成四层：

1. 当前会话上下文
   - 用于持续对话和 Hermes `--resume`。
   - 来源是当前 `ChatSession` 和最近消息。

2. 项目/目的上下文
   - 用户可以把会话归入一个项目或目的，例如“Hermes-Yachiyo 开发”“日语学习”“个人日程”。
   - 项目上下文优先影响同项目的新会话，不自动污染所有对话。

3. 共享助手记忆
   - 类似 ChatGPT 的 Memory，用于跨会话共享稳定偏好、称呼、长期事实和工作习惯。
   - 必须能查看、编辑、禁用和删除。

4. 临时检索片段
   - 每次请求前从本地存储检索相关会话摘要、项目事实和共享记忆。
   - 只把相关片段注入 prompt，不把整个历史聊天塞给 Hermes。

## 与 Hermes 原生记忆的关系

优先级应是：先复用 Hermes 原生记忆，再补 Yachiyo 桌面侧缺口。

| 层 | 归属 | 说明 |
| ---- | ---- | ---- |
| Hermes 原生记忆 | Hermes Agent | 如果 Hermes 已有长期记忆、召回和写入机制，它应是 agent 侧事实记忆的主系统。Yachiyo 不复制其内部存储，也不绕过它写另一套事实。 |
| Yachiyo 记忆控制层 | Hermes-Yachiyo | 保存用户可见的范围、开关、项目归属、候选确认状态、审计事件，以及 Hermes 记忆条目的引用。 |
| Yachiyo 会话记录 | Hermes-Yachiyo | SQLite `chat_sessions` / `chat_messages` 是 UI 和历史会话存档，不自动等同于长期记忆。 |
| AstrBot 桥接 | AstrBot plugin | 只转发用户请求和显式授权的摘要/事实，不拥有独立记忆系统。 |

因此不冲突，但需要一个适配层避免重复：

1. 检测 Hermes 是否暴露 memory API、CLI 子命令或可配置记忆目录。
2. 若可用，新增 `HermesMemoryAdapter`，把读取、写入、搜索、删除委托给 Hermes。
3. Yachiyo 本地 SQLite 只保存 UI 元数据，例如 `scope`、`project_id`、`enabled`、`external_ref`、`user_confirmed`、`last_used_at`。
4. 若 Hermes 当前没有可调用的记忆接口，再使用 Yachiyo 本地 `MemoryStore` 作为 fallback。
5. prompt 注入时避免重复：同一条记忆如果已由 Hermes 原生上下文召回，Yachiyo 不再额外塞进 `[relevant shared memories]`。

## 数据模型建议

继续使用 SQLite 作为第一阶段的控制层存储，避免为了 MVP 引入新依赖。若 Hermes 原生记忆可用，SQLite 表应保存 Hermes 记忆条目的引用和用户管理状态，而不是复制另一份事实主存储。

建议新增表：

| 表 | 用途 |
| ---- | ---- |
| `memory_items` | 保存可管理的长期记忆条目或 Hermes 原生记忆引用。字段包括 `memory_id`、`provider`、`external_ref`、`scope`、`kind`、`content`、`source_session_id`、`source_message_id`、`confidence`、`pinned`、`user_confirmed`、`created_at`、`updated_at`、`deleted_at`。 |
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

## 处理链路

### 写入链路

1. 用户与 Hermes 完成一轮对话。
2. Yachiyo 判断 Hermes 原生记忆能力是否可用。
3. 若 Hermes 支持记忆写入，优先把用户确认后的记忆交给 Hermes，并在本地保存引用。
4. 若 Hermes 不支持可调用记忆接口，则由 Yachiyo 本地 `MemoryStore` 保存候选记忆。
5. 记忆提取器读取最近消息和任务结果，提取候选记忆：偏好、事实、项目线索、可复用总结。
6. 根据风险分级处理：
   - 低风险偏好可自动暂存为候选。
   - 涉及身份、隐私、账号、敏感内容的记忆必须等待用户确认。
7. 用户可在设置页查看、确认、编辑、删除。
8. 通过 `memory_events` 记录来源与操作。

### 召回链路

1. 收到新的用户请求。
2. 判断当前会话所属项目/目的。
3. 优先调用 Hermes 原生召回能力；如果不可用，再使用 Yachiyo 本地检索。
4. 检索相关 `global` 记忆、当前项目记忆、当前会话摘要。
5. 去重，避免 Hermes 已召回的内容又被 Yachiyo 重复注入。
6. 按优先级组装 prompt：
   - persona
   - user address
   - relevant shared memories
   - project context
   - current session summary
   - user request
7. 将组装后的请求交给 Hermes，Hapi/Codex 路由仍保持原边界。

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
- 提供“管理记忆”入口，用户可以搜索、编辑、删除记忆。
- 新建会话时可选择“普通对话”或某个项目/目的。
- AstrBot 只转发和查询本地 Bridge，不拥有独立记忆脑。
- 默认不把 QQ 原始聊天自动写入全局记忆，除非用户启用或确认。

## 安全与默认值

- 共享记忆应默认关闭或以“候选待确认”模式启动。
- 删除记忆必须软删除并记录事件，后续再提供清理按钮。
- 高风险内容不得自动写入长期记忆。
- Bridge 只能操作本地 Yachiyo 暴露的记忆 API，AstrBot 不直接读写 SQLite。

## MVP 切分

1. 调研并检测 Hermes 原生记忆能力，定义 `HermesMemoryAdapter` 接口。
2. 新增 `MemoryStore` 控制层表，支持 `provider` / `external_ref`，可引用 Hermes 原生记忆。
3. 给会话增加可选 `project_id`，并提供项目列表。
4. 增加手动记忆管理 API 和 UI，先不做自动抽取。
5. 在 Hermes prompt 注入链路中加入去重后的手动记忆检索结果。
6. 增加低风险自动候选记忆提取。
7. 再评估本地 embedding 检索。
