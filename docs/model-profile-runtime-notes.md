# 模型 Profile 与执行后端阶段记录

记录日期：2026-05-19

这份文档记录 Phase 4 中围绕模型配置、Native provider 适配、Oha Agent runtime 和 TTS 入口的阶段性改动，方便后续继续开发时快速恢复上下文。

## 当前结论

- Profile 是 Oha-Yachiyo 的唯一模型配置中心。
- NativeRunEngine 是主对话、Agent、Workflow、委派和会话总结的唯一 Native Agent runtime。
- 设置页主模型只选择已经测试通过、且可作为 Native chat provider 的 `chat` Profile。
- 图片识别只选择已经通过真实图片测试的 `vision` Profile。
- Agent Studio 只管理持久自定义 Agent / Workflow，不管理主 Agent 本身。
- Agent Studio 不再让用户选择执行后端；旧 `execution_backend` 字段保留为数据兼容层，运行时统一归一到 Oha Agent Runtime。
- 本地命令能力只能通过受控 `terminal.run` 工具授权进入，不再提供 `external_cli` 执行路径。
- 主 Agent 可以通过 Oha 内部委派桥调用已启用的持久 Agent / Workflow；这不同于旧临时 subagent 注册表。
- TTS 与对话、图片转述分离，不复用 OpenRouter 模型目录。

## 已落地内容

### Native provider 映射

- 新增 `apps/shell/model_provider_adapters.py`，集中维护 Native provider、API Key 环境变量、provider alias 和 Base URL host hint。
- OpenRouter 返回的模型厂商前缀只作为模型分组，不直接写成运行时 provider id。
- 自定义 OpenAI-compatible 源若不能映射到已知 provider，会落到 `custom`，避免生成 Native provider 不认识的 provider id。
- 已修复 Xiaomi MiMo、DeepSeek 等源写入运行时配置后 provider 不匹配的问题。

### 模型源与 Profile

- 模型配置页按能力拆分为 `对话`、`图片转述`、`文字转语音` 三套独立来源。
- 新增/返回列表时会检查未保存草稿，避免误丢 API Key、Base URL 或模型选择。
- 交互收敛为：
  - 保存并获取模型列表。
  - 选择模型。
  - 测试连接并保存。
  - 测试成功后自动标记 `available`。
- 测试失败不会把模型保存为可用 Profile。
- 左侧状态会展示正在使用、Native provider、可用/失败、密钥是否配置、是否暂未选择模型。

### OpenRouter 与目录同步

- OpenRouter 的 `/api/v1/models` 只用于动态 OpenRouter 模型目录，不替代本地服务商源预设。
- 本地预设仍维护官方 Base URL、Native provider 映射、默认 icon 和说明。
- 新增 `apps/shell/provider_catalog_sync.py`，可手动同步主流 provider 的 `/models` 元数据到 `OHA_YACHIYO_HOME/provider-capabilities.json`。
- 目录缓存只作为能力提示和排序依据，最终可用性仍以真实连接测试为准。

### 视觉模型校验

- 视觉 Profile 不再强依赖远端 metadata 的 `input_modalities=image`。
- 远端 metadata 和本地已知能力表只作为“视觉/文本/未知”提示。
- 保存 vision Profile 前必须发送真实最小图片测试。
- 只有模型能正确读取图片内容，才保存为 `available + vision`。
- 针对不同 provider 的 Base URL、鉴权 header 和模型 ID 规范，后续应继续沉淀到 provider adapter，而不是在 UI 写临时规则。

### Agent runtime

- Agent spec 保留 `execution_backend` 兼容旧数据，但当前运行时统一归一为 `oha_profile`。
- Agent run 增加 `run_group_id`，`@Agent`、Workflow 和后续自动编排都挂到同一种 RunGroup 数据结构。
- `@Agent` 不走主聊天普通消息分支，而是进入 Oha router。
- Agent Studio Agent 是持久岗位，不是旧临时 subagent 注册表。
- 运行时会根据 Agent category、instructions、Skills、workspace policy 和 output contract 编译运行 prompt、工具白名单、审批策略和 context artifact。
- 默认工具策略按 category 推断：research/design/office/orchestrator 偏读工作区和写 artifacts，coding/review 可申请写入和终端，custom 默认最小权限。
- `terminal.run` 与 `workspace.write_patch` 默认需要审批，Agent prompt 不能绕过权限边界。
- 每次 Agent Run 会记录 context artifact、timeline、progress events 和 final result；挂载 Skill 缺失时会在运行前失败。
- 主 Agent 自动委派第一版走内部桥 `run_oha_agent` / `run_oha_workflow`，只接受已保存、已启用目标，并限制单轮最多 3 次。
- Chat 群组中的主模型协调不再复用普通委派桥：群组上下文会注入成员清单，主模型只输出内部 `dispatch_group_agent` 协议，Chat 层负责隐藏 JSON、创建对应 AgentRun、保留主模型自然说明并展示派发 activity。
- 群组派发的 AgentRun 失败后可按单条 Agent 气泡重试，重试只重跑该 Agent 的 `delegated_goal`，不会重新触发主模型整轮规划。
- AgentRun 在 Chat 中进入 `approval_required` 时继续保持 processing，并把待审批工具、脱敏输入摘要和批准 / 拒绝入口直接展示在消息气泡中；原始 pending tool input 仍只保留在后端。

### Agent Studio 第一阶段稳定化

- Agent Studio 的刷新边界已从“选择态驱动全量刷新”改为“初始加载 + 操作后显式刷新”。
- 切换 Agent / Workflow 只更新本地编辑 draft，不再触发全页 `busy`、列表重载或表单闪烁。
- 新建 Agent 会进入稳定的空白草稿；刷新逻辑不会再因为 `selectedAgentId` 为空自动选回第一个模板。
- 保存 Agent / Workflow 后通过刷新参数保留刚保存的选中项；删除后保留空白草稿，方便继续创建。
- Run 创建后显式选中新 Run；URL 中带来的 `run` 参数会被保留，允许详情补取。
- 执行后端成熟度表达已进入第二阶段，由普通 select 改成带能力状态的卡片。

### Execution Backend 状态 UI

- 这一阶段曾用三张卡片表达执行后端成熟度，帮助区分旧外部 runtime、Oha Profile 和 external adapter 占位的边界。
- 最新设计已经移除该选择体验：用户不再看到底层 backend 名称，只配置“岗位”和“能力”。
- 旧外部 runtime 不再作为 Agent Studio 自定义 Agent 的后端选项；主 Oha 助手只负责调度和整合。
- External CLI 不再作为执行路径；如需本地命令，由受控 `terminal.run` 工具能力和审批策略承载。
- Oha Profile 的概念也下沉为运行时实现细节：Agent Studio 保存的是业务配置，后端自动编译为 Oha Agent Runtime 配置。

### Agent Studio MVP 运行闭环

- 保存后的 Agent 可在编辑页用 `Quick Run` 直接创建 Agent Run，并自动跳转到 Runs 详情。
- 保存后的 Workflow 可在 Workflow Studio 用 `Workflow Run` 直接创建 Workflow Run；未保存 Workflow 明确要求先保存。
- Skill 挂载区显示挂载数量，Skill Library 中已挂载 Skill 会显示 mounted 状态。
- Runs 详情整理为查看结果的主面板：状态、RunGroup、Result、Timeline 和 Artifacts 在同一页闭环。
- MVP 仍是同步执行模型；后续再考虑 streaming、运行中轮询、审批恢复、失败重试和更完整的 artifact viewer。

### TTS 与主动关怀入口

- 模型配置页的 TTS tab 改为独立语音来源入口。
- TTS 预设扩展为 GSV TTS(Local)、HTTP TTS、Command TTS、OpenAI TTS、MiMo TTS、Edge TTS、FishAudio、阿里云百炼、Azure、MiniMax、火山引擎、Gemini 等。
- `GSV TTS(Local)` 和旧 `GPT-SoVITS` 入口跳转到“主动关怀与桌面观察”页面维护完整参数。
- 侧栏原 `GPT-SoVITS` 改名为 `主动关怀`，该页承载桌面观察、提醒触发、语音播报链路、音色资源与本地 GPT-SoVITS 服务。
- 当前 TTS Profile 更像“语音源登记”，完整合成参数和真实播报测试仍以主动关怀页为主。

### 品牌 icon

- Provider icon 统一使用厂商原始 icon 或已有品牌资源。
- Hugging Face 已修正为真实 Hugging Face icon，不再落到 OpenAI icon。
- TTS provider 也补了 OpenAI、MiMo、MiniMax、Azure、FishAudio、Gemini 等图标映射。

## 重要文件

- `apps/shell/model_profiles.py`
- `apps/shell/model_provider_adapters.py`
- `apps/shell/provider_catalog_sync.py`
- `apps/shell/agent_runtime.py`
- `apps/bridge/routes/model_profiles.py`
- `apps/bridge/routes/agents.py`
- `apps/frontend/src/views/ModelProfilesView.tsx`
- `apps/frontend/src/views/AgentStudioView.tsx`
- `apps/frontend/src/views/ModeSettingsView.tsx`
- `apps/frontend/src/views/ProactiveTtsSettingsView.tsx`
- `apps/frontend/src/components/ProviderBrandIcon.tsx`

## 后续建议

1. 把 `provider_catalog_sync.py` 接入每日主动更新机制：本地定时任务或应用启动后的低频后台刷新都可以，但必须避免阻塞启动。
2. 继续扩展 provider adapter：每个 provider 明确 `/models` 路径、鉴权 header、模型 ID 规范、chat payload、vision payload 和错误归因。
3. 把 Xiaomi MiMo、OpenRouter、Gemini、DashScope、DeepSeek、MiniMax 等常用源的真实图片测试链路逐个手工验收。
4. 完成 TTS API/HTTP/Command 的真实测试语义：TTS 不应只保存 profile id，还应能对 endpoint/voice/timeout/test text 做可证实的连接测试。
5. 继续硬化 Oha Agent Runtime 的 ToolBroker：优先支持 OpenAI tool_calls；不支持 tool_calls 的模型走 JSON fallback，并保留高风险工具审批。
6. 为 Agent Studio 后续补 streaming/轮询、审批恢复、失败重试、Run 取消 UI、Runs 履历聚合和更完整 artifact viewer。
7. 更新用户手册中的旧“主动关怀语音”命名，统一为“主动关怀与桌面观察”，并保留 GPT-SoVITS 作为该页内的本地 TTS 服务模块。
