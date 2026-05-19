# 模型 Profile 与执行后端阶段记录

记录日期：2026-05-19

这份文档记录 Phase 4 中围绕模型配置、Hermes provider 映射、Yachiyo Agent runtime 和 TTS 入口的阶段性改动，方便后续继续开发时快速恢复上下文。

## 当前结论

- Profile 是 Yachiyo 的唯一模型配置中心。
- Hermes CLI 仍是主对话的执行适配器，不在本阶段替换。
- 设置页主模型只选择已经测试通过、且 Hermes 可执行的 `chat` Profile。
- 图片识别只选择已经通过真实图片测试的 `vision` Profile。
- Agent Studio 可以选择执行后端：
  - `hermes_profile`：适合需要 Hermes 原生工具、联网、会话和复杂执行能力的 Agent。
  - `yachiyo_profile`：直接调用 Yachiyo 已保存 Profile，工具能力后续由 Yachiyo ToolBroker 补齐。
  - `external_cli`：预留给 Codex、Claude Code、OpenDesign daemon 等专用外部执行器。
- TTS 与对话、图片转述分离，不复用 OpenRouter 模型目录。

## 已落地内容

### Hermes provider 映射

- 新增 `apps/shell/model_provider_adapters.py`，集中维护 Hermes 可执行 provider、API Key 环境变量、provider alias 和 Base URL host hint。
- OpenRouter 返回的模型厂商前缀只作为模型分组，不直接写成 Hermes provider。
- 自定义 OpenAI-compatible 源若不能映射到 Hermes 原生 provider，会落到 `custom`，避免生成 Hermes 不认识的 provider id。
- 已修复 Xiaomi MiMo、DeepSeek 等源写入 Hermes config 后 provider 不匹配的问题。

### 模型源与 Profile

- 模型配置页按能力拆分为 `对话`、`图片转述`、`文字转语音` 三套独立来源。
- 新增/返回列表时会检查未保存草稿，避免误丢 API Key、Base URL 或模型选择。
- 交互收敛为：
  - 保存并获取模型列表。
  - 选择模型。
  - 测试连接并保存。
  - 测试成功后自动标记 `available`。
- 测试失败不会把模型保存为可用 Profile。
- 左侧状态会展示正在使用、Hermes provider、可用/失败、密钥是否配置、是否暂未选择模型。

### OpenRouter 与目录同步

- OpenRouter 的 `/api/v1/models` 只用于动态 OpenRouter 模型目录，不替代本地服务商源预设。
- 本地预设仍维护官方 Base URL、Hermes provider 映射、默认 icon 和说明。
- 新增 `apps/shell/provider_catalog_sync.py`，可手动同步主流 provider 的 `/models` 元数据到 `~/.hermes/yachiyo/provider-capabilities.json`。
- 目录缓存只作为能力提示和排序依据，最终可用性仍以真实连接测试为准。

### 视觉模型校验

- 视觉 Profile 不再强依赖远端 metadata 的 `input_modalities=image`。
- 远端 metadata 和本地已知能力表只作为“视觉/文本/未知”提示。
- 保存 vision Profile 前必须发送真实最小图片测试。
- 只有模型能正确读取图片内容，才保存为 `available + vision`。
- 针对不同 provider 的 Base URL、鉴权 header 和模型 ID 规范，后续应继续沉淀到 provider adapter，而不是在 UI 写临时规则。

### Agent runtime

- Agent spec 增加 `execution_backend`。
- Agent run 增加 `run_group_id`，`@Agent`、Workflow 和后续自动编排都挂到同一种 RunGroup 数据结构。
- `@Agent` 不直接走普通 Hermes Chat，而是进入 Yachiyo router。
- `yachiyo_profile` 不是 Hermes Agent 的等价替代；它可以直连模型，但工具调用、联网查询和复杂协作能力要依赖 Yachiyo ToolBroker 后续补齐。

### Agent Studio 第一阶段稳定化

- Agent Studio 的刷新边界已从“选择态驱动全量刷新”改为“初始加载 + 操作后显式刷新”。
- 切换 Agent / Workflow 只更新本地编辑 draft，不再触发全页 `busy`、列表重载或表单闪烁。
- 新建 Agent 会进入稳定的空白草稿；刷新逻辑不会再因为 `selectedAgentId` 为空自动选回第一个模板。
- 保存 Agent / Workflow 后通过刷新参数保留刚保存的选中项；删除后保留空白草稿，方便继续创建。
- Run 创建后显式选中新 Run；URL 中带来的 `run` 参数会被保留，允许详情补取。
- 下一阶段应把 `hermes_profile`、`yachiyo_profile`、`external_cli` 从普通 select 改成带能力状态的执行后端卡片，明确哪些已可运行、哪些是实验/占位。

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
5. 为 `yachiyo_profile` 补 ToolBroker：优先支持 OpenAI tool_calls；不支持 tool_calls 的模型走 JSON fallback。
6. 设计 Agent Studio 第二阶段的执行后端状态 UI：Hermes Runtime / Yachiyo Profile / External CLI 分别展示成熟度、配置要求和下一步动作。
7. 更新用户手册中的旧“主动关怀语音”命名，统一为“主动关怀与桌面观察”，并保留 GPT-SoVITS 作为该页内的本地 TTS 服务模块。
