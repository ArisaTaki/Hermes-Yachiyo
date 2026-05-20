# Phase 4 重构计划：Agent Studio + Workflow Studio + Skill Import

## Summary

Phase 4 放弃旧 Coding/Provider 集成路线。Yachiyo 不再管理第三方 CLI/daemon，也不再提供专门的 Coding Job runtime。

新方向是把 Yachiyo 做成本地个人 Agent 的 GUI 编排中心：

- Agent Studio：用 GUI 创建、编辑、测试和运行 Agent。
- Skill Library：导入本地 Skill，并挂载到 Agent。
- Workflow Studio：用可视化节点把多个 Agent 编排成线性可运行流程。
- Model Profiles：按服务商源保存、测试和复用文本 / Vision / TTS 配置；不再生成“本地主模型”快照。
- Chat 入口：普通消息继续走 Hermes Chat；`@Name 需求`、Composer 选择器或主 Agent 自动委派会启动已启用的持久 Agent / Workflow。

## 已实现批次

### Batch 1：删除旧 Coding 系统

- 删除后端旧受控编码服务、旧编码 routes、旧编码 tests。
- 删除前端 Coding 页面、coding client、Coding 导航入口。
- 移除 Chat 旧编码指令入口，普通 Chat 行为保持不变。
- Tool Center 与 Diagnostics 不再展示第三方 CLI/daemon 的安装/登录/升级状态。

### Batch 2：AgentRuntimeService

- 新增 `apps/shell/agent_runtime.py`。
- 落地 `~/.hermes/yachiyo/agent-runtime.db`。
- 管理 Agent、Skill、Workflow、AgentRun、WorkflowRun。
- API Key 仅保存在后端；前端只读到 `api_key_configured`。
- 空 API Key 更新不会覆盖已保存密钥。
- 内置 Agent 模板：
  - Yachiyo Orchestrator
  - Coding Agent
  - Design Agent
  - Review Agent
  - Research Agent
  - Office Agent
  - Custom Agent

### Batch 3：Skill Library

- 支持从本地目录或 ZIP 导入 Skill。
- 根目录必须包含 `SKILL.md`。
- ZIP 导入拒绝路径穿越。
- `assets/`、`templates/`、`examples/` 作为可引用 artifact 路径记录。
- Skill 运行时只注入 `SKILL.md` 内容，不执行 `scripts/` 或任意命令。

### Batch 4：Workflow Studio v1

- 新增 Workflow CRUD。
- 使用 `@xyflow/react` 做可视化节点编辑。
- v1 保存时强制线性：
  - 一个 Start。
  - 无环。
  - 无分支。
  - 无断链。
  - 每个节点最多一个下一步。
- 内置“网页点子全流程”模板。

### Batch 5：Chat Agent 入口

- `/ui/chat/messages` 支持可选 `runnable_id`。
- Chat 文本支持 `@Name 需求` 解析 Agent / Workflow。
- 名称要求全局唯一，避免歧义。
- 启动后创建 AgentRun / WorkflowRun，并在 Chat 中插入结果摘要。
- 普通消息不带 `@Name` 且未选择 runnable 时仍走原 Hermes task。

### Batch 6：Model Profiles

- 新增 `apps/shell/model_profiles.py`。
- 落地 `~/.hermes/yachiyo/model-profiles.db`。
- 模型配置页改为服务商源 + Profile 管理：
  - 对话模型来自 OpenAI-compatible 服务商源。
  - 图片识别模型来自支持 `image` 输入的多模态模型。
  - TTS Profile 来自独立语音来源，不复用 OpenRouter 模型目录。
- 模型列表不再拼接 Hermes 当前主模型；主模型只是运行链路配置，不作为本地 provider/source 展示。
- 服务商预设包含 Xiaomi MiMo，并允许 Agent Runtime 引用这类 OpenAI-compatible provider source Profile。
- 远端模型资料优先使用 `/models` 返回的 OpenRouter-style metadata：
  - `input_modalities` 包含 `image` 的模型才适合作为 Vision Profile。
  - 文本模型仍按服务商源登记和测试。
  - TTS 使用 GPT-SoVITS / HTTP TTS / Command TTS 等语音专用来源。
- Profile API Key 仅保存在后端；前端只显示 `api_key_configured`。
- 空 API Key 更新不会覆盖旧密钥。
- Agent 可选择 `follow_main` 或引用已保存的 `model_profile_id`。
- 设置页“模型”区域改为新版模型配置入口，不再直接承担连接测试表单。

### Batch 7：Profile 统一化、执行后端与视觉/TTS 收口

- 新增 Hermes provider adapter 层，集中维护 Hermes 可执行 provider、API Key env、alias、Base URL host hint 和 OpenRouter 模型前缀边界。
- OpenRouter `/api/v1/models` 只替代 OpenRouter 模型列表硬编码；各厂商源的 Base URL、Hermes provider 映射和官方 icon 仍由本地预设维护。
- 模型配置页按 `chat` / `vision` / `tts` 分离服务商源，避免对话和图片转述共用同一来源。
- 模型保存流程收敛为“保存并获取模型列表”与“测试连接并保存”；测试失败不保存为可用 Profile。
- Vision Profile 改为真实图片测试通过后才可用，远端 metadata 与本地已知能力表只作为提示，不作为唯一准入条件。
- 新增 `apps/shell/provider_catalog_sync.py`，为后续每日同步 provider `/models` 元数据准备缓存能力。
- Agent spec 增加 `execution_backend`，支持 `hermes_profile` / `yachiyo_profile` / `external_cli`；Agent run 增加 `run_group_id`，为 `@Agent`、Workflow 和自动编排统一 RunGroup 数据结构。
- TTS tab 改为独立语音来源入口；`GSV TTS(Local)` / 旧 `GPT-SoVITS` 入口跳转到“主动关怀与桌面观察”页维护完整本地 TTS 参数。
- 侧栏原 `GPT-SoVITS` 改名为 `主动关怀`，Hugging Face 和 TTS 预设补充厂商品牌 icon。
- 详细阶段记录见 `docs/model-profile-runtime-notes.md`。

### Batch 8：Agent Studio 第一阶段稳定化

- Agent Studio 数据加载改为初始 bootstrap + 操作后按需刷新，选择 Agent / Workflow 不再触发全页 `busy` 和列表重载。
- 修复“新建 Agent 闪一下无事发生”：点击新建会进入明确的空白草稿状态，不再被刷新逻辑自动选回第一个模板 Agent。
- 保存 Agent 后显式保留新建/编辑后的 Agent 选中项；删除 Agent 后保留空白草稿状态，方便继续创建。
- Workflow 新建/保存/删除同样使用显式选择状态，避免画布在非保存操作中被刷新重置。
- Run 创建后显式选中新 Run；通过 URL 打开的历史 Run ID 会继续保留并触发详情补取，不会被最近 Run 列表覆盖。
- 加载状态与操作状态拆分：初次读取显示“正在读取 Agent Studio...”，保存/删除/导入/运行等操作使用局部 action 状态，不再因为切换列表项造成页面闪烁。

### Batch 9：Execution Backend 状态 UI

- Agent 编辑页的 `Execution Backend` 从普通下拉改为三张能力状态卡片。
- `Hermes Runtime` 标注为实验：默认创建 RunGroup 与 Agent 上下文，真实 Hermes CLI 执行需要后端开关。
- `Yachiyo Profile` 标注为 MVP 推荐/可运行路径：直连模型配置中已经测试通过的 `chat` Profile；没有可用 Profile 时显示“需要 Profile”。
- `External CLI` 标注为占位：保留 Codex / Claude Code / OpenDesign daemon 等后续 adapter 入口，但 MVP 不从 UI 提交任意 shell command。
- 选择 `Yachiyo Profile` 后只展示 `Chat Profile` 选择器；选择 `Hermes Runtime` 后展示主模型管理入口；选择 `External CLI` 后仅展示占位说明。
- 这一步只改变能力表达与选择体验，不改变后端执行语义；下一步再补 Agent 快速运行、Skill 挂载反馈和 Run/artifact 体验闭环。

### Batch 10：Agent Studio MVP 运行闭环

- Agent 编辑页新增 `Quick Run`：保存后的 Agent 可直接输入目标并创建 Agent Run，完成后自动切到 Runs 详情。
- Workflow Studio 新增 `Workflow Run`：保存后的 Workflow 可直接输入目标并创建 Workflow Run；新建未保存时按钮禁用并提示先保存。
- Skill 挂载反馈更明确：Agent 编辑页显示 `mounted / skills` 计数；Skill Library 中已挂载 Skill 会以 mounted 状态显示。
- Runs 详情整理为 MVP 查看面板：顶部展示 runnable、goal、状态 pill、run kind、更新时间、RunGroup 和 run id；Result、Timeline、Artifacts 分区显示数量。
- 无 Run 时的空状态说明后续会展示 Result、Timeline 和 Artifacts，减少用户进入 Runs 页后的空白感。
- 这一步仍复用既有后端同步执行语义，不引入 streaming、取消中的实时轮询或复杂审批流程。

### Batch 11：持久 Agent 岗位模型与 Yachiyo Runtime 收口

- Agent Studio 正式收敛为“持久岗位”配置，不再等同 Hermes 临时 subagent；Hermes/Yachiyo 主助手是全局调度者，不放进 Agent Studio 列表。
- 前端移除 `Execution Backend` 选择，用户只看到岗位配置、模型 Profile、Skills、workspace 范围、能力开关和输出格式。
- 后端保留旧 `execution_backend` 字段兼容，但所有旧值都会归一到 `yachiyo_profile`；`hermes_profile` / `external_cli` 不再作为可选运行后端。
- 删除 `external_cli` 执行路径；本地命令只能通过受控 `terminal.run` 工具能力进入，并继续受审批策略约束。
- Agent Runtime 会在保存和运行时编译工具策略、workspace policy、运行 prompt、进度事件标签和 context artifact。
- 默认工具策略按 category 推断：research/design/office/orchestrator 偏 artifacts 与工作区读取，coding/review 可申请写入和终端，custom 默认最小权限。
- `terminal.run` 与 `workspace.write_patch` 作为高风险工具默认需要审批；Agent prompt 不能绕过该策略。
- 每次 Agent Run 都会生成 context artifact、timeline、progress events、final result；缺失 Skill 会在运行前失败。
- 主 Agent 上下文会注入已启用 Agent/Workflow 名录，并可通过内部桥 `run_yachiyo_agent` / `run_yachiyo_workflow` 创建普通 Run；结果回填给主 Agent 后继续整合回复。
- 委派桥只接受已保存、已启用的 Agent/Workflow；未知、空目标、停用对象都会拒绝；单轮自动委派最多 3 次。

## 新增接口

- `GET/POST /ui/model-profiles`
- `GET/PATCH/DELETE /ui/model-profiles/{profile_id}`
- `POST /ui/model-profiles/{profile_id}/test`
- `PATCH /ui/model-profiles/defaults`
- `GET/POST /ui/model-sources`
- `GET/PATCH/DELETE /ui/model-sources/{source_id}`
- `POST /ui/model-sources/{source_id}/test`
- `POST /ui/model-sources/{source_id}/models/fetch`
- `GET/POST /ui/model-sources/{source_id}/models`
- `GET/POST /ui/agents`
- `GET/PATCH/DELETE /ui/agents/{agent_id}`
- `POST /ui/agents/{agent_id}/test-model`
- `GET/POST /ui/skills`
- `POST /ui/skills/import`
- `GET/DELETE /ui/skills/{skill_id}`
- `POST /ui/agents/{agent_id}/skills`
- `DELETE /ui/agents/{agent_id}/skills/{skill_id}`
- `GET/POST /ui/workflows`
- `GET/PATCH/DELETE /ui/workflows/{workflow_id}`
- `GET /ui/runnables`
- `GET /ui/runs`
- `POST /ui/agent-runs`
- `GET /ui/agent-runs/{run_id}`
- `POST /ui/workflow-runs`
- `GET /ui/workflow-runs/{run_id}`
- `POST /ui/runs/{run_id}/cancel`

## 安全边界

- 前端不能提交任意 shell command。
- Agent Studio 不暴露底层 backend 名称；旧 backend 字段只是数据兼容层。
- Tool Broker 只暴露受控工具：
  - `workspace.list`
  - `workspace.read`
  - `workspace.write_patch`
  - `terminal.run`
  - `artifact.write`
- `terminal.run` 默认需要审批。
- `workspace.write_patch` 默认需要审批。
- 文件读写必须落在 Agent workspace policy 范围内。
- Artifact 写入有路径越界保护。
- Skill scripts 不执行。
- API Key 和命令日志走脱敏。

## 当前限制

- Workflow v1 只做线性流程，不做分支、并行、条件表达式和失败回退。
- 旧 `execution_backend` 数据仍能读取，但产品语义统一归一到 Yachiyo Agent Runtime。
- Agent Studio Agent 是持久岗位，不是 Hermes 原生 `delegate_task` 临时 subagent 注册表。
- Custom API 作为高级模型配置兼容路径保留，但仍走同一个 Yachiyo Agent Runtime。
- ToolBroker 仍需补真实工具调用循环、审批恢复、运行中取消、streaming/轮询和失败重试。
- 主 Agent 自动委派第一版走 Yachiyo 内部桥，不改 Hermes 原生 `delegate_task` 实现。
- TTS Profile 首版做统一保存与复用入口，具体语音合成、服务检测和连接测试仍由主动关怀 / TTS 专用链路执行。
- Provider 目录同步目前是可手动运行的缓存能力；每日自动订阅更新机制尚未接入应用 lifecycle。
- Skill v1 只支持本地目录/ZIP，不做远程 marketplace，也不自动扫描用户全局 skills。
- 第三方 CLI/daemon 由用户自行管理，不再由 Yachiyo 安装、登录、升级或托管。

## 验证目标

- 删除回归：
  - 业务代码不再包含旧编码服务、旧编码 routes、旧编码页面和第三方 CLI provider ID。
- 后端：
  - Agent CRUD。
  - Model Profile CRUD、密钥脱敏、空 key 不覆盖、默认 Profile 校验。
  - Model Source CRUD、远端模型列表拉取、OpenRouter metadata 保留。
  - Agent 引用 Model Profile 后可创建 run。
  - Agent 引用 Xiaomi MiMo 等 OpenAI-compatible provider source Profile 后可创建 run。
  - Skill 导入、ZIP 路径穿越拒绝。
  - Workflow 线性校验。
  - Tool Broker 越界与审批保护。
  - Chat `@Agent` 创建 run 且不创建普通 Hermes task。
- 前端：
  - Agent Studio 创建/编辑 Agent，挂载 Skill。
  - Model Providers 不展示本地主模型快照。
  - Vision 模型列表只登记支持图片输入的多模态模型。
  - TTS tab 使用独立语音来源，不复用对话模型提供商界面。
  - Skill Library 导入、预览、删除 Skill。
  - Workflow Studio 拖拽、连线、保存、运行。
  - Chat 选择 Agent / Workflow 或输入 `@Name` 能创建 run。
  - `npm --prefix apps/frontend run build` 通过。
