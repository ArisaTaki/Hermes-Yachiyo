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

### Batch 12：ToolBroker 真实执行层与审批恢复

- Agent Runtime 新增统一 tool-call 循环，优先读取 OpenAI-compatible `message.tool_calls`，并保留旧 JSON fallback：`{"action":"tool","tool":"workspace.list","input":{...}}`。
- OpenAI tool schema 使用函数名别名，后端映射回 dotted 工具名：
  - `workspace_list` -> `workspace.list`
  - `workspace_read` -> `workspace.read`
  - `workspace_write_patch` -> `workspace.write_patch`
  - `terminal_run` -> `terminal.run`
  - `artifact_write` -> `artifact.write`
- Tool loop 上限为 6 次；超限后 Run 标记为 failed，并记录 timeline。
- 未授权工具直接失败，记录 `agent.tool.denied`，不会执行工具 payload。
- `workspace.list`、`workspace.read`、`artifact.write` 可直接执行；`terminal.run`、`workspace.write_patch` 永远不会因为模型 payload 自带 `approved=true` 而执行。
- 新增 Run 状态 `approval_required`；遇到高风险工具时，Run 写入 `pending_approval_json`，RunGroup 同步停在 `approval_required`。
- 前端只读取脱敏/截断后的 `pending_approval` 展示信息；原始 tool input 只保留在后端用于审批后继续执行。
- 新增 approve/reject API：审批通过后执行当前 pending tool，把结果回填给模型并继续同一个 Run；拒绝后 Run 标记为 `cancelled` 并记录原因。
- Runs 详情页显示待审批工具、脱敏输入和 Approve / Reject 按钮。
- `openai_compatible_chat` 保留原有文本返回行为；新增完整 chat completion message helper 供 Agent Runtime 读取 `tool_calls`。

### Batch 13：Agent Profile、Persona Prompt 与本地 Skill Library

- Agent 定义新增 `nickname`、`avatar_url` 和 `persona_prompt`；头像用于 Agent Studio 列表与未来对话入口，昵称用于未来直接与 Agent 聊天时的显示名。
- `instructions` 收敛为功能 prompt；`persona_prompt` 单独进入运行上下文，用于人设、口吻和角色偏好。
- Agent context artifact 会分段写入 `# Functional Instructions` 与 `# Persona Prompt`，避免功能约束和角色设定混杂。
- Agent Studio 编辑页新增头像预览、昵称输入、头像选择按钮和 Persona Prompt textarea。
- Skill Library 改为本地上传/导入体验：支持选择多个本地 Skill 目录或 ZIP，也支持拖放/粘贴路径；导入后逐条展示成功、失败或跳过结果。
- Skill 数据新增 `local_path` 与 `enabled`；Skill 卡片展示本地路径、启停开关、删除和“打开路径”入口，不再提供下载按钮。
- Agent 的 Mounted Skills 只从已启用 Skill Library 里选择；后端同时阻止挂载停用 Skill，并在运行前拒绝已挂载但已停用的 Skill。
- Agent Studio 补充 Output Contract、Capabilities、Default Workdir、Readable Scopes、Writable Scopes 的解释文案，并提示用“测试模型 + Quick Run”做可行性验证。

### Batch 14：Yachiyo / Hermes 双 Skill 库与受限安装入口

- Skill Library 分成 Yachiyo 管理区与 Hermes Agent 管理区：Yachiyo 上传/安装的 Skill 留在 Yachiyo 工作区，Hermes Agent 自带全局 Skill 只登记 `~/.hermes/skills` 原路径引用，不复制到 Yachiyo 目录；项目级 `.hermes/skills` 暂不纳入本页管理。
- 后端新增 Skill 来源字段：`source_type`、`origin_path`、`source_ref`、`content_hash`、`last_synced_at`、`sync_status`；同步时按来源大类隔离去重，hash 变化会更新同一大类内已有 Skill。
- Skill Library 与 Agent Mounted Skills 都增加 Yachiyo / Hermes Agent 来源筛选和搜索，默认显示 Yachiyo，避免 Hermes 自带大量 Skill 挤占管理视图。
- 新增受限安装入口：支持直接输入 Skill 来源，也支持 `skills@latest add ...`、`npx skills add ...`、`npx -y skills@latest add ...` 与 `hermes skills install ...`；禁止 shell 管道、串联和重定向。`skills` CLI 路径会固定补齐 `hermes-agent` 目标、`--copy` 与 `-y`，命令在 Yachiyo 的 Skill 安装工作区执行，安装结果同步为 Yachiyo Skill。
- Skill 安装 UI 显示不确定进度条和 stdout/stderr 尾部日志；当前 CLI 没有稳定机器可读百分比事件，因此不显示假百分比。
- Agent Run 和模型工具调用不能触发 Skill 安装；安装只能来自 UI 用户操作。

### Batch 15：Skill Folder / Collection

- 新增一层 Skill Folder 元数据层：`skill_folders` 表保存文件夹名称、说明、来源范围与排序；`skills.folder_id` 保存归属。
- Skill Folder 只作为管理和筛选维度，不移动 Hermes Agent 原路径，也不强制改动 Yachiyo 已导入 Skill 的本地快照路径。
- Skill Groups 收进 Skill Library 二级页面：顶层 Agent Studio 只保留 `Skill Library`，内部用 `Skills 列表 / 分组管理` 切换；Skill Library 左侧只保留安装/上传时的目标文件夹选择。
- 删除文件夹默认会把其中 Skill 归回“无需分组”，也可以在同一个删除操作区打开“连带 Skills”后一起删除文件夹内 Skill。
- Skill Library 卡片可直接移动 Skill 到其他文件夹；Agent Mounted Skills 增加文件夹筛选，便于给 Coding / Design 等 Agent 按主题挑选 Skill。
- Agent Mounted Skills 支持对当前筛选结果一键全选/清空；安装完成后不再显示 stdout/stderr 结果框，只保留导入/同步结果。
- Agent Studio 增加 Agent 列表 stale state 自愈；Agent 列表读取增加 row factory 回归覆盖，避免开发态连接状态漂移后 `/ui/agents` 列表转换崩溃。
- `#/agents/skill-groups` 兼容直达 `Skill Library > 分组管理`，旧 `#/agents/<run_id>` Run 详情链接继续兼容。
- Skill Folder 创建/重命名拒绝重复名和超过 120 字符的名称；前端提供 inline validation。删除、恢复、覆盖、卸载、中断终端/更新等高风险操作统一使用 `ConfirmDialog`，不再依赖 `window.confirm`。
- “无需分组”计数拆成总数 / Yachiyo / Hermes，避免 Hermes Agent 全局 Skills 干扰默认组判断。
- 当前剩余决策：Hermes Agent skills 是否可归入 Yachiyo 分组、是否做手动排序；`source_scope` 暂时保持后端内部字段，不暴露到 UI。

### Batch 16：Workflow Studio 基础可用性与全线测试模板

- 默认模板补种逻辑拆开 Agent 与 Workflow：已有 Agent 的数据库启动时也会补齐缺失的默认 Workflow，不再因为 `agents` 表非空而跳过。
- 新增默认 Workflow：`Phase 4 Agent 全线流通测试`，按 `Yachiyo Orchestrator -> Research -> Design -> Coding -> Review -> Office -> Flow Summary artifact` 线性执行。
- 默认 Agent 和 `follow_main` Agent 在没有显式 Chat Profile 时会使用模型配置里的默认 Chat Profile；旧数据里 `agent_coding` 仍是 `profile` 但未绑定 Profile 时，也能作为默认 Agent 跟随默认 Chat Profile 跑通。
- Workflow Studio 增加“全线测试模板”按钮，可按现有 Agent 自动生成线性节点和边；手动新增 Agent / Approval / Artifact 节点时会自动接到当前线性链末端。
- Workflow 节点设置区显示 node/edge 数量，Agent 节点可直接选择 Agent 或从链路中移除，移除时会自动桥接前后节点。
- 已增加 deterministic 流通性测试：用 fake 默认 Chat Profile 跑完整 `workflow_phase4_agent_line_smoke`，验证 6 个 Agent 子 Run、RunGroup 和最终 Workflow artifact 都完成。

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
- `GET /ui/skills/sources`
- `POST /ui/skills/sync`
- `POST /ui/skills/install`
- `GET/PATCH/DELETE /ui/skills/{skill_id}`
- `GET/POST /ui/skill-folders`
- `PATCH/DELETE /ui/skill-folders/{folder_id}`
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
- `POST /ui/runs/{run_id}/approval/approve`
- `POST /ui/runs/{run_id}/approval/reject`

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
- 模型 payload 里的 `approved=true` 不会绕过审批；只有后端 approve API 能传入运行时审批许可。
- Run 进入 `approval_required` 时，前端只展示脱敏/截断后的 pending approval 信息。
- 文件读写必须落在 Agent workspace policy 范围内。
- Artifact 写入有路径越界保护。
- Skill scripts 不执行。
- Skill 安装命令不走 shell，只接受白名单 argv；模型与 Agent Run 不能提交安装命令。
- API Key 和命令日志走脱敏。

## 当前限制

- Workflow v1 只做线性流程，不做分支、并行、条件表达式和失败回退。
- 旧 `execution_backend` 数据仍能读取，但产品语义统一归一到 Yachiyo Agent Runtime。
- Agent Studio Agent 是持久岗位，不是 Hermes 原生 `delegate_task` 临时 subagent 注册表。
- Custom API 作为高级模型配置兼容路径保留，但仍走同一个 Yachiyo Agent Runtime。
- ToolBroker 已支持真实 tool-call 循环和单个 Agent Run 审批恢复；Workflow 子 Run 遇到审批后父 Workflow 会暂停为 `approval_required`，审批完成后自动继续父 Workflow 仍待增强。
- 运行中取消、streaming/轮询、失败重试和复杂 artifact viewer 仍待补齐。
- 主 Agent 自动委派第一版走 Yachiyo 内部桥，不改 Hermes 原生 `delegate_task` 实现。
- TTS Profile 首版做统一保存与复用入口，具体语音合成、服务检测和连接测试仍由主动关怀 / TTS 专用链路执行。
- Provider 目录同步目前是可手动运行的缓存能力；每日自动订阅更新机制尚未接入应用 lifecycle。
- Skill Library 已支持 Yachiyo / Hermes 双库、Hermes roots 同步、受限安装命令和本地 ZIP/目录上传；仍不做远程 marketplace 浏览器或任意包管理协议。
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
  - Tool Broker 原生 `tool_calls`、JSON fallback、未授权工具拒绝、越界拒绝、审批暂停、审批恢复和拒绝取消。
  - Chat `@Agent` 创建 run 且不创建普通 Hermes task。
- 前端：
  - Agent Studio 创建/编辑 Agent，挂载 Skill。
  - Model Providers 不展示本地主模型快照。
  - Vision 模型列表只登记支持图片输入的多模态模型。
  - TTS tab 使用独立语音来源，不复用对话模型提供商界面。
  - Skill Library 批量导入、启停、打开本地路径、删除 Skill。
  - Runs 详情可显示 `approval_required` 并执行 Approve / Reject。
  - Workflow Studio 拖拽、连线、保存、运行。
  - Chat 选择 Agent / Workflow 或输入 `@Name` 能创建 run。
  - `npm --prefix apps/frontend run build` 通过。
