# Current State

## 已完成

### Milestone 92 — Runs 顶层历史与 Workflow 步骤产物

- ✅ 按真实用户流程重新创建 demo Skills、Design / Coding / Review Agents 和线性 Workflow，并用已配置默认 Chat Profile 跑通真实 Workflow：`workflow_run_8254dd42d09c` completed，三个子 Agent 分别产出 `DESIGN_DEMO_OK`、`CODING_DEMO_OK`、`REVIEW_DEMO_OK`。
- ✅ 修复真实多 Agent 串联暴露的问题：OpenAI-compatible chat 读取超时从 20 秒改为 60 秒常量；Workflow 后续 Agent 的 `user_goal` 保持原始目标，上一节点结果只进入 `Upstream Context`，避免上下文重复膨胀。
- ✅ Runs 列表语义改为顶层历史：Workflow 子 Agent Run 不再出现在主列表或 Agents 分类里；`Workflows` 只展示 Workflow root run，`Agents` 只展示用户单独运行 Agent 的 run。
- ✅ Workflow Run 详情新增 `Final Result` 与 `Workflow Steps`，按顺序展示每个子 Agent 的状态、输出、artifact 入口和 Open Run 入口；中间产物不再只能从 timeline 手动跳转查找。
- ✅ 已确认下一阶段产品方向：Agent / Workflow 需要从文本 demo 走向真实产物契约，Design Agent 产出原型或 Markdown，Coding Agent 产出代码或 patch，Review Agent 产出 Markdown review；Runs 要成为所有入口触发任务的统一产物查看面板。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_model_profiles.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 131 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。

### Milestone 91 — 真实模型 E2E 与 Workflow 缺陷收口

- ✅ 使用已配置默认 Chat Profile（`xiaomi_mimo/mimo-v2-pro`）完成真实 E2E：导入本地 Skill、挂载到 Agent、直接运行 Agent、API 运行 Workflow、Runs 页面触发 Workflow，均能创建真实 Run / 子 Run 并得到模型结果。
- ✅ Agent Runtime 现在尊重显式空工具集；`tool_policy.allowed_tools: []` 不再被强行补成 `artifact.write`，真实回归中两个子 Agent 的 compiled `allowed_tools` 均为 `[]`。
- ✅ Agent 模型调用改为 system message 承载运行时规则，明确精确输出要求优先；真实回归中 Skill Agent 能稳定返回 `HY_REAL_AGENT_OK HY_REAL_SKILL_MARKER_20260527`。
- ✅ Workflow 在子 Agent 初次执行失败或取消时会立即让父 Workflow fail/cancel，不再把失败结果当作正常上下文继续传递；取消子 Run 也会同步唤醒等待中的父 Workflow。
- ✅ Runs 详情 timeline 增加 child run 跳转按钮和节点状态；Workflow Studio 的 React Flow MiniMap / Controls / attribution 白底样式已统一到暗色主题。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 107 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。

### Milestone 90 — Workflow 子 Run 审批恢复

- ✅ Workflow 子 Agent Run 进入 `approval_required` 后，父 Workflow Run 会保持暂停并记录对应 `child_run_id`。
- ✅ 审批通过子 Agent Run 后，Agent Runtime 会找到同一 RunGroup 中等待该子 Run 的父 Workflow，从暂停节点之后继续执行后续 Agent / Approval / Artifact 节点。
- ✅ 子 Agent 审批后再次请求高风险工具时，父 Workflow 会继续停在 `approval_required`；子 Agent 审批后失败或被拒绝时，父 Workflow 会同步失败或取消。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py::test_workflow_resumes_after_child_agent_approval -q` → 1 passed；`.venv/bin/python -m pytest tests/test_agent_runtime.py -q` → 39 passed。

### Milestone 89 — Workflow Studio 基础补强

- ✅ Workflow seed 逻辑修正：默认 Workflow 会独立补种，已有 Agent 的数据库也能获得缺失的默认 Workflow。
- ✅ 新增 `Phase 4 Agent 全线流通测试` 默认 Workflow，线性调用 Orchestrator、Research、Design、Coding、Review、Office，并把最终上下文写入 Flow Summary artifact。
- ✅ 默认 Agent / `follow_main` Agent 可跟随默认 Chat Profile；旧数据中的默认 Agent 即使未显式绑定 `model_profile_id`，也能参与 Workflow Run。
- ✅ Workflow Studio 增加“全线测试模板”按钮，按当前默认 Agent 自动生成节点与边；手动新增 Agent / Approval / Artifact 节点会自动接到当前线性链末端。
- ✅ 节点设置区显示 node/edge 数量，Agent 节点可选择具体 Agent 或移除；移除中间节点时会自动桥接前后节点。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py -q` → 37 passed；`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 103 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed。

### Milestone 88 — Skill Folder / Collection

- ✅ 新增一层 Skill Folder 元数据层：`skill_folders` 表保存文件夹名称、说明、来源范围与排序；`skills.folder_id` 保存归属，默认显示为“无需分组”。
- ✅ Skill Folder 只作为管理和筛选维度，不移动 Hermes Agent 原路径，也不强制改动 Yachiyo 已导入 Skill 的本地快照路径。
- ✅ Skill Groups 独立成 Agent Studio 页面，负责文件夹新建、重命名、查看与删除；Skill Library 左侧只保留安装/上传时的目标文件夹选择。
- ✅ 删除文件夹会把 Skill 归回“无需分组”。
- ✅ Skill Library 卡片支持移动 Skill 到其他文件夹；Agent Mounted Skills 增加文件夹筛选，便于按 Laravel / Design 等主题为 Agent 挑选 Skill。
- ✅ Agent Mounted Skills 支持对当前筛选结果一键全选/清空；安装完成后不再显示 stdout/stderr 结果框，只保留同步结果提示。
- ✅ 修复 Agent Studio stale state：开发态 HMR 或临时刷新导致左侧 Agent 列表为空但右侧仍有 draft 时，会自动重新拉取 Agent 列表；`list_agents` 增加 row factory 回归覆盖，避免连接状态漂移后 `/ui/agents` 列表转换崩溃。
- ✅ Skill Groups 后续 TODO 已收口：`#/agents/skill-groups` 可直达，保留旧 `#/agents/<run_id>` Run 详情链接兼容；从 Skill Groups 点击“查看”会进入 Skill Library 并保留对应文件夹筛选。
- ✅ Skill Folder 创建/重命名新增前后端名称校验：拒绝空名、重复名和超过 120 字符的名称；删除文件夹前会确认并说明 Skill 会回到“无需分组”。
- ✅ “无需分组”现在拆分显示总数、Yachiyo 与 Hermes 计数，避免 Hermes 自带 Skills 让默认组看起来异常庞大。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 97 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed；浏览器打开 `http://127.0.0.1:5174/#/agents/skill-groups` 确认 Skill Groups 直达、Skill Library tab 跳转和 console error 为空。
- ✅ 最新实现提交：`bb4436b feat(agent): finish skill groups todo`。

### Milestone 87 — Yachiyo / Hermes 双 Skill 库与受限安装入口

- ✅ Skill Library 分成 Yachiyo 管理区与 Hermes Agent 管理区：Yachiyo 上传/安装的 Skill 留在 Yachiyo 工作区，Hermes Agent 自带全局 Skill 只登记 `~/.hermes/skills` 原路径引用，不复制到 Yachiyo 目录；项目级 `.hermes/skills` 暂不纳入本页管理。
- ✅ Skill 数据新增 `source_type`、`origin_path`、`source_ref`、`content_hash`、`last_synced_at`、`sync_status`；同步按 Yachiyo / Hermes 大类隔离去重，hash 变化会更新同一大类内已有 Skill。
- ✅ Skill Library 与 Agent Mounted Skills 都增加 Yachiyo / Hermes Agent 来源筛选和搜索，默认显示 Yachiyo，避免 Hermes 自带大量 Skill 挤占管理视图。
- ✅ 新增受限安装入口：支持直接输入 Skill 来源、`skills@latest add ...`、`npx skills add ...` / `npx -y skills@latest add ...` / `hermes skills install ...`，拒绝 shell 管道、串联和重定向；`skills` CLI 路径会固定使用 `hermes-agent`、补齐 `--copy -y`，在 Yachiyo 的 Skill 安装工作区执行并同步为 Yachiyo Skill。
- ✅ Skill 安装 UI 改成来源/安装命令输入，安装中显示不确定进度条并保留 stdout/stderr 尾部日志；不伪造 CLI 未提供的百分比进度。
- ✅ Agent 列表层级颜色、头像选择控件和 Skill 上传区域已按最新 UI 反馈调整：不再显示 avatar URL，不再显示手动导入路径 textarea。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 92 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed。

### Milestone 86 — Agent Profile 与本地 Skill Library

- ✅ Agent 定义新增 `nickname`、`avatar_url` 与 `persona_prompt`；昵称和头像用于 Agent Studio 展示，也为后续对话框内直接和某个 Agent 聊天预留数据。
- ✅ `instructions` 明确作为功能 prompt，`persona_prompt` 单独作为人设/口吻/角色偏好 prompt；Agent context artifact 会分段写入 `# Functional Instructions` 与 `# Persona Prompt`。
- ✅ Agent Studio 编辑页新增头像预览、昵称输入、头像选择按钮和 Persona Prompt 输入框；头像选择沿用 Electron 图片选择器，保存为可直接渲染的 data URL。
- ✅ Skill Library 改成上传/导入体验：支持选择多个本地 Skill 目录或 ZIP，支持拖放/粘贴路径，导入后逐条显示成功、失败或跳过结果。
- ✅ Skill 数据新增 `local_path` 与 `enabled`；Skill 卡片展示本地路径、启停开关、删除和打开本地路径入口，不再提供下载。
- ✅ Agent 的 Mounted Skills 只从已启用 Skill Library 中选择；后端同时阻止挂载停用 Skill，并在运行前拒绝已挂载但已停用的 Skill。
- ✅ Agent Studio 补充 Output Contract、Capabilities、Default Workdir、Readable Scopes、Writable Scopes 的解释文案，并提示用“测试模型 + Quick Run”进行可行性验证。
- ✅ 验证：`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_model_profiles.py -q` → 107 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed；Computer Use 冒烟确认 Agent 表单、Skill Library 导入、Skill 卡片和 Mounted Skills 显示正常。

### Milestone 85 — ToolBroker 真实执行层与审批恢复

- ✅ Agent Runtime 新增统一 tool-call 循环：优先解析 OpenAI-compatible `message.tool_calls`，并保留 JSON fallback `{"action":"tool","tool":"workspace.list","input":{...}}`。
- ✅ OpenAI tool schema 使用函数名别名，后端映射回 dotted 工具名：`workspace_list`、`workspace_read`、`workspace_write_patch`、`terminal_run`、`artifact_write`。
- ✅ Tool loop 上限为 6 次；超限后 Run 失败。
- ✅ 非授权工具会失败并记录 `agent.tool.denied` timeline，不执行模型 payload。
- ✅ `workspace.list`、`workspace.read`、`artifact.write` 可直接执行；`terminal.run` 和 `workspace.write_patch` 永远不会因为模型 payload 自带 `approved=true` 而执行。
- ✅ 新增 Run 状态 `approval_required` 和 `pending_approval_json`；遇到高风险工具时 Run 与 RunGroup 同步停在 `approval_required`。
- ✅ `pending_approval` 对前端只暴露脱敏/截断后的展示信息；原始 tool input 只保留在后端用于审批后继续执行。
- ✅ 新增 `POST /ui/runs/{run_id}/approval/approve` 与 `POST /ui/runs/{run_id}/approval/reject`；approve 后执行 pending tool 并继续同一个 Run，reject 后 Run 变为 `cancelled`。
- ✅ Runs 详情页在 `approval_required` 时显示待审批工具、脱敏输入和 Approve / Reject。
- ✅ `openai_compatible_chat` 保持原文本返回行为，并新增完整 chat completion message helper 供 Agent Runtime 读取 `tool_calls`。
- ✅ 验证：真实 Electron + fake OpenAI-compatible server 冒烟，`terminal.run` 进入审批，UI Approve 后执行并回填 stdout，Run 最终 completed。

### Milestone 84 — Agent Studio 持久岗位 Runtime

- ✅ Agent Studio 设计收敛为“主 Agent + 持久自定义 Agent”：Hermes/Yachiyo 主助手继续负责总调度，Agent Studio 只管理长期登记的岗位 Agent 与 Workflow。
- ✅ 前端移除 `Execution Backend` 选择体验：用户现在配置岗位名称、职责、instructions、模型 Profile、Skills、工作区范围、能力开关和输出格式，不再看到 `Hermes Runtime` / `External CLI` 后端选项。
- ✅ 后端保留旧 `execution_backend` 字段兼容，但 `hermes_profile`、`external_cli`、空 backend 都归一为 `yachiyo_profile`；自定义 Agent 统一走 Yachiyo Agent Runtime。
- ✅ 删除 `external_cli` 执行路径；本地命令能力只能通过受控 `terminal.run` 工具授权进入，不能由 Agent prompt 绕过权限。
- ✅ Agent 保存/运行时会自动编译 runtime 配置：根据 category、instructions、Skills、workspace policy 和 output contract 生成运行 prompt、工具白名单、审批策略、workspace policy 与进度事件。
- ✅ 高风险工具默认需要审批：`terminal.run` 和 `workspace.write_patch` 会进入 `approval-required` 策略，不会直接执行。
- ✅ Agent Run 自动写入 context artifact，并记录 runtime 编译、artifact 写入、模型响应、工具调用、完成/失败等 timeline/progress 事件。
- ✅ Skill 运行前校验更严格：挂载 Skill 不存在时会在运行前报错，避免静默缺上下文。
- ✅ 主 Agent 新增 Yachiyo 委派桥：主会话上下文会注入已启用 Agent/Workflow 名录，可通过 `run_yachiyo_agent` / `run_yachiyo_workflow` 创建普通 Run，结果回填后继续整合最终回复。
- ✅ 委派安全边界已落地：未知目标、空目标、停用 Agent/Workflow 会拒绝；单轮自动委派最多 3 次，避免循环调用。
- ✅ 验证：`pytest` → 610 passed，1 warning；`npm run build`（`apps/frontend`）通过；`git diff --check` 通过；本地浏览器打开 Agent Studio 确认旧 backend 文案不可见，新 `Model` / `Capabilities` 配置可见。

### Milestone 83 — Agent Studio MVP 运行闭环

- ✅ Agent 编辑页新增 `Quick Run`：保存后的 Agent 可直接输入目标创建 Agent Run，完成后自动切到 Runs 详情。
- ✅ Workflow Studio 新增 `Workflow Run`：保存后的 Workflow 可直接输入目标创建 Workflow Run；新建未保存时按钮禁用并提示先保存。
- ✅ Skill 挂载反馈更清楚：Agent 编辑页显示 `mounted / skills` 计数；Skill Library 中已挂载 Skill 会显示 mounted 状态。
- ✅ Runs 详情整理为 MVP 查看面板：展示 runnable、goal、状态 pill、run kind、更新时间、RunGroup、run id、Result、Timeline 和 Artifacts。
- ✅ 无 Run 空状态已说明后续会展示 Result、Timeline 和 Artifacts，避免 Runs 页看起来像坏掉。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed；本地浏览器验证 Quick Run、Workflow Run、Skill 挂载计数和 Runs 空状态。

### Milestone 82 — Agent Studio Execution Backend 状态 UI

- ✅ Agent 编辑页的 `Execution Backend` 已从普通下拉改为三张能力状态卡片。
- ✅ `Hermes Runtime` 明确标注为实验能力：当前默认创建 RunGroup 与上下文，真实 Hermes CLI 执行需要显式后端开关。
- ✅ `Yachiyo Profile` 明确标注为可运行路径：依赖模型配置中已经测试通过的 chat Profile；无可用 Profile 时显示“需要 Profile”。
- ✅ `External CLI` 明确标注为占位能力：MVP 不暴露 command 输入，避免从 UI 提交任意 shell 命令。
- ✅ Backend 选择后的下方配置区按当前能力切换：Hermes 显示主模型管理入口，Yachiyo 显示 Chat Profile 选择器，External CLI 显示占位说明。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed；本地浏览器验证 backend 卡片切换、Yachiyo Profile 字段和 External CLI 无命令输入入口。

### Milestone 81 — Agent Studio 第一阶段稳定化

- ✅ Agent Studio 选择态已从数据刷新依赖中拆出：切换 Agent / Workflow 不再触发全页重新读取、`busy` notice 或表单闪烁。
- ✅ 修复“新建 Agent 闪一下无事发生”：新建现在会稳定进入空白 Agent 草稿，不会被初始化/刷新逻辑自动选回第一个内置模板。
- ✅ Agent 保存后显式保留刚保存的 Agent；删除后保留空白草稿，便于继续创建。
- ✅ Workflow 新建/保存/删除也使用显式选择状态，避免画布在非保存操作中被刷新重置。
- ✅ Run 创建后显式选中新 Run；通过 URL 进入的历史 Run ID 会继续保留并补取详情。
- ✅ 初始加载状态与操作状态拆分：只有首次读取显示加载提示，保存/删除/导入/运行等操作后再按需刷新列表。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed。

### Milestone 80 — 模型 Profile 统一化、Agent 执行后端与 TTS 入口整理

- ✅ Profile 已作为模型配置中心推进：模型配置页按 `对话`、`图片转述`、`文字转语音` 分离服务商源，测试通过后才进入对应场景选择列表。
- ✅ Hermes CLI 仍保留为主对话执行适配器；默认主模型只同步 Hermes 可执行的 `chat` Profile，避免把 OpenRouter 模型厂商误写成 Hermes provider。
- ✅ 新增 Hermes provider adapter 层：集中维护 provider id、API Key env、alias、Base URL host hint 和 OpenRouter 模型前缀边界，修复 Xiaomi MiMo / DeepSeek 等源同步到 Hermes config 的 provider mismatch。
- ✅ OpenRouter `/api/v1/models` 用于动态 OpenRouter 模型目录；本地仍维护各厂商源预设、Base URL、Hermes provider 映射和官方 icon。
- ✅ 新增 provider catalog 同步模块 `apps/shell/provider_catalog_sync.py`，可把主流 provider `/models` 元数据同步到本地缓存，为后续每日订阅更新打基础。
- ✅ Vision Profile 改为真实图片测试通过后才保存为 `available + vision`；远端 metadata 与本地已知能力表只作为“视觉/文本/未知”提示。
- ✅ Agent spec 增加 `execution_backend`，支持 `hermes_profile`、`yachiyo_profile`、`external_cli`；Agent run 增加 `run_group_id`，为 `@Agent`、Workflow 和后续自动编排统一运行组结构。
- ✅ 模型配置页交互修复：新增/返回列表会提示未保存变更；详情页有返回列表；保存按钮收敛为“保存并获取模型列表”和“测试连接并保存”；左侧状态会及时显示可用、失败、密钥配置和暂未选择模型。
- ✅ TTS tab 改为独立语音来源入口，补充 GSV TTS(Local)、HTTP TTS、Command TTS、OpenAI、MiMo、Edge、FishAudio、阿里云百炼、Azure、MiniMax、火山、Gemini 等预设。
- ✅ 侧栏原 `GPT-SoVITS` 改名为 `主动关怀`；该页定位为“主动关怀与桌面观察”，承载桌面观察、提醒触发、语音播报链路、音色资源与本地 GPT-SoVITS 服务。
- ✅ Provider icon 修正为厂商品牌图标，Hugging Face 已不再落到 OpenAI icon。
- ✅ 阶段说明已写入 `docs/model-profile-runtime-notes.md`，并在 `docs/phase-4-hermes-sync-plan.md` 记录 Batch 7。
- ✅ 验证：多轮 `npm --prefix apps/frontend run build` passed；模型配置页本地预览检查通过；相关后端迁移/Agent runtime/model profile/vision 测试在本轮变更中分批通过；最新文档同步仅涉及 Markdown。

### Milestone 79 — macOS 发布链路、应用更新器与安装体验收口

- ✅ macOS release workflow 现在覆盖 `main` 与 `develop` 两条渠道：`main` 生成正式版 stable DMG，`develop` 生成实验版 experimental prerelease DMG；滚动 release 分别维护 `main-latest` 与 `develop-latest`。
- ✅ 固定下载资产已统一：`Hermes-Yachiyo-main-latest.dmg`、`Hermes-Yachiyo-develop-latest.dmg`，并同步上传 `.sha256` 与 `.json` 元数据；latest JSON 包含 channel、branch、version、commit、build number、DMG 名称、SHA256、download URL 和 published time。
- ✅ CI 在构建前写入 `apps/frontend/public/hermes-yachiyo-build.json`，打包后的应用可知道自己所属渠道、当前版本、commit、build number 与对应 latest JSON URL。
- ✅ 免费分发签名策略已确认并落地：`.app` 自签名，`.dmg` 保持未签名；避免自签名 DMG 被 macOS 挂载前直接拒绝。首次启动仍需用户通过 Finder Control-click -> Open 或系统设置允许未知开发者应用。
- ✅ 新增 `scripts/create_macos_self_signed_cert.sh` 与 `scripts/build_macos_self_signed_dmg.sh`，支持本地生成自签名证书、导出 GitHub Secrets 辅助 env、签名 `.app` 并创建未签名 DMG。
- ✅ 打包版 Bridge 默认端口与开发环境拆开：开发默认 `8420`，打包默认 `18420`；打包版若发现 `18420` 已被占用，会临时分配空闲本地端口并传给内置 backend，避免误连本地 develop backend。
- ✅ 应用内更新器已接入通用设置页：按当前渠道检查对应 latest JSON，比较版本/build/commit，下载 DMG，校验 SHA256，退出当前应用后挂载 DMG、覆盖当前 `.app` 并重新打开。
- ✅ 更新器请求 latest JSON 时加 cache-busting query 与 `Cache-Control: no-cache` / `Pragma: no-cache`，避免 GitHub rolling asset/CDN 在 release 刚更新时返回旧 JSON，导致 `0.1.31` 误判为最新。
- ✅ 更新下载有实时进度：Electron main 通过 IPC 推送 `starting/downloading/verifying/completed/failed` 状态，设置页显示百分比或已下载大小；下载完成后按钮变为“安装并重启”。
- ✅ 已下载但未安装的更新会持久化到 Electron `userData/updates/downloaded-update.json`；重新进入设置页或重启后会自动识别本地 DMG 是否仍是当前渠道的更高版本，并直接提供“安装并重启”。
- ✅ release 更新日志已接入 git commit 同步：CI 以当前渠道上一条 `stable-v*` / `experimental-v*` tag 为基线生成 changelog，写入 GitHub release notes 与 latest JSON；应用内“应用更新”区会展示 latest JSON 中的更新内容和提交对比入口。
- ✅ 安装向导在更新后 backend/Bridge 尚未完全启动时，不再直接显示红色“无法连接本地 Bridge”；会进入“正在启动本地 Bridge”状态，并每 1.2 秒自动重新检测，Bridge 可用后恢复正常安装/就绪流程。
- ✅ Hermes Agent 检测修复：当 `~/.local/bin/hermes` 是 bash wrapper 且实际 `exec ~/.hermes/hermes-agent/venv/bin/hermes` 时，Yachiyo 会继续解析真实 venv launcher，定位 Hermes Agent 自带 Python，避免图片链路测试误报“无法定位 Hermes Agent 的 Python 环境”。
- ✅ Hermes 安装检测更稳：若存在 `~/.hermes/hermes-agent` 但 `hermes` 命令缺失或 wrapper 损坏，会返回可修复的 not installed/repair 指引，而不是把脏安装误判为 ready。
- ✅ 图片链路执行修复：`hermes_stream_bridge.py` 的 shebang 解析不再把 `/usr/bin/env` 当成脚本执行，修复打包临时目录中出现 `env: ...hermes_stream_bridge.py: Permission denied` 的问题。
- ✅ 验证：`python scripts/generate_release_changelog.py --channel experimental ...` 本地生成 changelog JSON/Markdown passed；`python -m py_compile scripts/generate_release_changelog.py` → passed；`PATH=<Node 20.19 runtime> npm --prefix apps/frontend run build` → passed（保留 Vite large chunk warning）；`python -m pytest tests/test_hermes_installer.py tests/test_runtime.py tests/test_executor.py tests/test_main_api_modes.py` → 134 passed；`ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-macos.yml")'` → passed；`git diff --check` → passed。

### UX Fixes — 首用体验报告修复

- ✅ 新增 `/ui/tts/status`，主动关怀语音页可以显示最近一次自动播报的生成中、成功或失败状态，便于定位 GPT-SoVITS 自动播报 HTTP 400 等问题。
- ✅ 工具中心已区分 Hermes Agent 的 `tts` 工具与 Yachiyo 主动关怀 TTS；无 Hermes 原生配置卡片时会引导用户打开“主动关怀语音”页面。
- ✅ 备份策略和备份操作区已提示 Live2D/GPT-SoVITS/附件缓存会进入备份，资源越大备份越大、耗时越久。
- ✅ 图片附件读取时新增极小尺寸保护，低于 16x16 的图片会提示换用正常尺寸截图，减少上游视觉模型“图片不可处理”的失败体验。
- ✅ 验证：相关 TTS route tests 4 passed；`npm --prefix apps/frontend run build` passed（保留既有 Vite large chunk warning）；`git diff --check` passed。

### Documentation — DMG 首用走查与 VitePress 素材

- ✅ 使用 `/Applications/Hermes-Yachiyo.app` 发布包，在隔离 HOME/Profile 下完成一次真实“第一次用户”走查。
- ✅ 覆盖并截图：安装向导、Hermes Agent 检测、Xiaomi MiMo 模型配置、连接测试、工作空间初始化、主控台、图片链路、文本对话、图片附件、Bubble、Live2D 导入与渲染、GPT-SoVITS 导入与 TTS 测试、主动关怀、工具中心、诊断、更新检查、备份和卸载预览。
- ✅ 新增 43 张截图到 `docs/public/images/hermes-yachiyo/first-run/`，VitePress 可直接通过 `/images/hermes-yachiyo/first-run/<file>.png` 引用。
- ✅ 新增/更新文档：`docs/user-manual.md`、`docs/screenshot-index.md`、`docs/experience-report-2026-05-05.md`、`docs/first-run-smoke-test-2026-05-05.md`。
- ✅ 真实边界已记录：GUI 安装遇到 GitHub 克隆中断后可手动安装并重新检测；Web/CDP/Image Gen 缺外部 Key 时工具中心按预期受限；GPT-SoVITS 手动测试成功但一次主动关怀自动播报返回 HTTP 400。
- ✅ 测试环境已清理，未把一次性 API Key 明文写入文档。

### Milestone 78 — Release 重跑幂等修复

- ✅ `Build macOS DMG` workflow 的发布步骤改为 `Create or update GitHub release`：当目标 release tag 已存在时，会用 `gh release upload --clobber` 覆盖同名 DMG asset，并用 `gh release edit` 刷新标题、目标 commit 和 release notes；首次运行仍走 `gh release create`。
- ✅ 修复 GitHub Actions 重跑同一个 run 时因 `ReleaseAsset.name already exists` / HTTP 422 导致 `Create GitHub release` 失败的问题。

### Milestone 77 — Live2D 导入编码、Vision Key 兼容与 GPT-SoVITS 部署入口

- ✅ Live2D ZIP 导入改为自定义解包：当压缩包文件名缺少 UTF-8 标记时，会尝试按 UTF-8 / GB18030 / 日文/韩文编码恢复真实文件名，并把可疑乱码目录名替换为安全的导入目录名，避免 `~/.hermes/yachiyo/assets/live2d/` 后出现 box drawing 乱码路径。
- ✅ Live2D 资源下载入口统一走系统默认浏览器，并明确指向资源 release：`https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/tag/live2d-assets-20260423`；不会再把 Live2D release 打进内置窗口。
- ✅ 图片识别链路补上 OpenRouter 旧配置兼容：当 Hermes/Yachiyo 仍保存的是 `AUTO_API_KEY`，但 provider 推断为 OpenRouter 时，原生图片输入与 vision 预分析都会把它视为可用 key；UI 仍只显示 `OPENROUTER_API_KEY` 的配置状态，不泄漏或展示 `AUTO_API_KEY` 明文。
- ✅ 主动关怀 TTS 超时上限从 120 秒放宽到 600 秒，默认值调整为 180 秒；GPT-SoVITS 权重切换、`/tts` 生成和音频播放都使用同一超时设置，适配本地模型首次加载较慢的情况。
- ✅ 主动关怀 TTS 触发后会先进入 `tts_pending` 状态：Bubble/Live2D 不再提前显示文本提醒，等异步 TTS 完成并把音频附件写回会话后，下一轮 launcher 轮询才把主动消息作为可见提醒推出。
- ✅ 主动关怀语音页补齐 GPT-SoVITS 本地服务部署入口：新增“部署本地服务”按钮，会打开系统终端，经过用户确认后克隆 `RVC-Boss/GPT-SoVITS`、创建 `.venv`、安装依赖并启动 `127.0.0.1:9880` API；“安装开机自启”仍只负责把已配置的服务目录/命令写入 LaunchAgent。
- ✅ GPT-SoVITS 语音资源面板布局收紧为紧凑按钮栏，避免三个资源按钮被 CSS grid 拉成异常高的大块；语音资源下载仍走外部默认浏览器并指向独立的 `tts-assets-yachiyo-gpt-sovits-v4` release。
- ✅ 验证：`python -m pytest tests/test_ui_bridge_routes.py::test_launcher_tts_only_triggers_for_proactive_attention tests/test_ui_bridge_routes.py::test_launcher_tts_triggers_without_probability_gate tests/test_ui_bridge_routes.py::test_launcher_hides_proactive_reply_while_tts_audio_is_generating tests/test_ui_bridge_routes.py::test_live2d_zip_member_name_recovers_utf8_without_flag tests/test_tts.py::test_import_tts_voice_archive_returns_gpt_sovits_settings` → 5 passed；`python -m pytest tests/test_executor.py::TestHermesStreamBridgeImageRouting::test_xiaomi_text_model_vision_fallback_inherits_configured_base_url tests/test_main_api_modes.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py` → 93 passed；`python -m pytest tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_executor.py` → 165 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`git diff --check` → passed。

### Milestone 76 — 主动关怀截图链路、首启回退与发布自动化收口

- ✅ 主动关怀桌面观察的截图附件改为只作为内部附件传给对话链路，不再把“主动桌面观察”的系统指令文本写入用户消息；对话中仍可看到生成的桌面截图附件，方便用户确认本轮观察依据。
- ✅ 聊天附件读取改为 `inline` 响应，并移除图片查看器中的“打开原图”外部浏览器入口，避免主动关怀截图触发后自动弹出 Chrome/默认浏览器预览窗口，同时保持图片识别链路可继续读取本地附件。
- ✅ Hermes provider 推断补强：当配置为 `auto` 但 Base URL/模型指向 OpenRouter 时，Yachiyo 会按有效 provider 写入 `OPENROUTER_API_KEY` 并使用对应模型缓存判断图片原生输入能力，避免误报“API Key 无效”或错误回退到 vision 预分析。
- ✅ Electron 首启/激活流程继续加固：只要用户已经进入过主控台或安装信息显示 ready，Dock 图标激活就不会再用旧的 `lastInstallReady=false` 打回安装向导；进入主控台时会恢复配置中的 Bubble/Live2D 表现态，Live2D 无资源时自动回退 Bubble。
- ✅ Live2D 资源 gate 前后端双重兜底：设置页保存 `display_mode=live2d` 时如果没有有效资源，会返回 `redirect` 到 Live2D 设置页并保持 Bubble；Electron 表现态打开也会先检查资源状态，避免无资源透明窗口把用户困住。
- ✅ 主动关怀语音页新增 GPT-SoVITS 本地服务状态/安装/移除路由：可查看 API 是否可达、服务目录是否存在、LaunchAgent 是否安装/运行，并可把当前服务目录和命令写成当前用户的 macOS LaunchAgent；不会下载或改写 GPT-SoVITS 项目本体。
- ✅ Release workflow 改为自动生成带版本号的 stable/experimental release tag 与资产名：版本以 `pyproject.toml` 基础版本加 `GITHUB_RUN_NUMBER` 形成发布版本；应用 release 只发布 DMG，不再把八千代 GPT-SoVITS ZIP 附在每次 develop/main 构建里。
- ✅ 新增独立 `Publish TTS Voice Assets` workflow：只在手动触发时接收已经调配好的语音 ZIP URL，并上传到 `tts-assets-yachiyo-gpt-sovits-v4` 资源 release；不会从仓库重复构建语音包，也不会参与应用 DMG 常规构建。
- ✅ 卸载“删除当前应用本体”改为 macOS Finder 删除优先、shell 删除兜底；仍属于 best-effort，因为运行中的 `.app` 删除受 Finder/权限/签名路径影响，失败时继续提示用户手动从 Applications 移除。
- ✅ 验证：`python -m pytest tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py tests/test_main_api_modes.py tests/test_proactive.py tests/test_hermes_capabilities.py tests/test_executor.py` → 181 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-macos.yml")'` → passed；`git diff --check` → passed。

### Milestone 75 — DMG 首装流程、Live2D Gate 与 TTS 本地服务辅助

- ✅ 基于 `develop` 当前 HEAD `67b7f74` 的 DMG 清机验证反馈，修复安装向导在 Hermes 终端安装完成后的衔接：重新检测到 `installed_needs_setup` / `setup_in_progress` / `installed_not_initialized` 后会滚动到模型配置向导，引导用户填写 Provider、模型、Base URL 和 API Key。
- ✅ 初始化 Yachiyo 工作空间前新增模型/API Key 完整性提示：如果当前 Provider、模型或所需 API Key 缺失，会提示“直接初始化可能导致首次对话不可用”，用户确认后仍可继续，取消则回到模型配置区。
- ✅ Hermes ready / 工作空间初始化成功后，桌面壳会进入主控台并主动打开 Bubble 表现态；macOS 点击 Dock 图标时会先刷新 `/hermes/install-info`，避免使用旧的 `lastInstallReady=false` 把已初始化用户拉回安装向导，同时恢复当前表现态。
- ✅ 通用设置中的 Live2D 模式切换新增资源 gate：若 `mode_settings.live2d.config.model_state` 不是 `path_valid` / `loaded`，不会切换到 Live2D，而是跳到 Live2D 资源配置页要求导入 ZIP 或选择有效模型目录；后端 `apply_settings_changes()` 同步拒绝无资源的 `display_mode=live2d`。
- ✅ Electron 表现态启动也新增 Live2D gate：显式打开 Live2D 且资源未就绪时进入设置页；默认打开表现态时如当前配置是 Live2D 但资源不可用，会回退到 Bubble，避免用户进入不可点击、找不到 Dock 图标的死路。
- ✅ Live2D 真模型渲染增加 Electron/WebGL 保护：加载 runtime 后配置 Pixi WebGL2 偏好并关闭 major performance caveat；遇到 `checkMaxIfStatementsInShader` / `invalid value of 0` 时保留静态预览并显示明确的 WebGL 回退说明，避免把资源导入成功误判成导入失败。
- ✅ 主动关怀 TTS 的 GPT-SoVITS 配置新增本地服务辅助字段：`tts.gsv_service_workdir` 与 `tts.gsv_service_command`；导入八千代语音包后会默认填入 `http://127.0.0.1:9880`、权重/参考音频路径和默认服务启动命令，服务目录可由语音包 manifest 提供或由用户手动填写。
- ✅ 主动关怀语音设置页新增“GPT-SoVITS 本地服务”区块：可填写服务目录与启动命令，并通过受控 `/ui/hermes/terminal-command` 打开终端启动本地服务；说明语音 ZIP 只包含权重/参考音频，本地 API 服务仍需单独运行。
- ✅ 卸载页新增“同时删除当前应用本体”选项：完成工作区/Hermes 数据卸载后，可由 Electron 启动受控 shell 删除当前 `.app` bundle 并退出；失败时会提示手动移除 Applications 中的应用。
- ✅ GitHub Actions DMG workflow 失败原因已定位为 CI 未安装 `pytest-asyncio`，`pyproject.toml` dev extras 已补 `pytest-asyncio>=0.23.0`，workflow 的 async smoke tests 可正常收集执行。
- ✅ 验证：`npm --prefix apps/frontend run build` → passed；`python -m pytest tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_uninstall.py` → 131 passed，1 known duplicate ZIP warning；workflow smoke suite `python -m pytest tests/test_screenshot.py tests/test_proactive.py tests/test_chat_session.py tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py` → 112 passed；`python -m pytest tests/test_hermes_installer.py` → 10 passed；全量 `python -m pytest` → 421 passed，1 known duplicate ZIP warning；`git diff --check` → passed。

### Milestone 74 — Tool Center Doctor 分级与工具配置修复

- ✅ 基于当前 `phase-2/feature/repair-tools` 的提交树补齐进度记录：`7307fd3` 合入了 2026-05-01 至 2026-05-02 的 Electron 固定前端、配置诊断、图片附件/vision 路由、图片链路校验缓存和窗口身份持久化等工作；其前序关键提交包括 `1ddba0a`、`41126f9`、`28c23ff`、`eac0dcb`、`0d0aee0`、`254ce91`、`9f55c9f`。
- ✅ `hermes doctor` 输出解析已从只看受限项扩展为同时解析 `available_tools`、`limited_tools`、受限原因和 issue count；旧的三元返回值仍保留兼容安装器调用。
- ✅ Runtime、Dashboard、Settings 和 Tool Center 已透传 Doctor 新字段，工具中心不再只依赖 `hermes.ready` 推断状态。
- ✅ Tool Center 已拆分基础 `browser` 和高级 `browser-cdp`：基础浏览器自动化可按 `browser` 可用状态显示，CDP 端口缺失只影响 `browser-cdp`。
- ✅ 新增工具配置安全接口 `/ui/hermes/tools/config`：按工具返回不同配置项，只展示 env 名和配置状态，不回传任何 token/key 明文；保存统一走 `hermes config set`。
- ✅ 第一批配置目录已覆盖 `web`、`browser`、`browser-cdp`、`image_gen`、Discord、Home Assistant、MoA、RL；Spotify、腾讯元宝和 messaging 先提供 Hermes 原生向导入口；Tool Center 现会读取 `hermes tools list`，只展示当前 Hermes 暴露的工具组。
- ✅ `image_gen` 配置已收敛为当前 Hermes 已知 provider：内置 FAL 与已装 OpenAI/OpenAI Codex/xAI 插件提供模型建议，不再主动列出 Hermes 未暴露的生图后端。
- ✅ 工具配置页新增“保存并测试 / 测试配置”：保存后会做必需配置静态检查，并运行 `hermes doctor` 对应工具状态，不会默认触发发消息、生图、RL 训练等有副作用/成本的真实调用。
- ✅ 新增 Hermes 更新检查与更新入口：Tool Center 可检查 `hermes version` / `hermes update --check`，更新通道跟随 Hermes 官方 updater 的当前 checkout `origin/main`；默认执行 `hermes update --gateway --yes --no-backup`，可勾选完整备份后改走 `--backup`，更新完成会自动刷新 `hermes tools list`、工具配置、Dashboard 与 Doctor 缓存，并展示工具清单变化。
- ✅ `image_gen` provider 列表改为从当前 Hermes `plugins/image_gen/*/plugin.yaml` 读取，确保已安装的 OpenAI、OpenAI Codex、xAI 插件不会被前端压成只剩 FAL。
- ✅ 新增 `/ui/hermes/tools/browser-cdp/launch`：可尝试启动或连接本机 Chrome `9222` 调试端口，成功后写入 `browser.cdp_url=http://127.0.0.1:9222`，失败时返回 Hermes 生成的手动命令。
- ✅ Tool Center React 视图新增 `#/tools/:toolId` 独立配置页，受限/可配置卡片会进入对应配置页而不是在长列表顶部展开；配置页顶部和底部都有保存入口，未保存切换时会弹出“保存并继续 / 弃置更改 / 继续编辑”确认。
- ✅ 诊断缓存指纹已纳入工具配置安全快照，工具配置或 env 配置状态变化后会让旧 Doctor 缓存标记为过期。
- ✅ 验证：`python -m pytest tests/test_hermes_installer.py tests/test_main_api_modes.py tests/test_ui_bridge_routes.py tests/test_hermes_capabilities.py` → 49 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`git diff --check` → passed。

### Milestone 73 — 一键安装错误捕获 hotfix

- ✅ `run_hermes_install()` 不再丢弃带 ANSI 颜色控制序列的安装脚本输出；会清洗控制码并保留可读错误文本，避免 UI 只显示 `exit=1` 而隐藏真正失败原因。
- ✅ 安装脚本非零退出后，兜底检测改为复用 `locate_hermes_binary()`，可识别 Hermes 已落盘但当前 GUI 进程 PATH 尚未刷新的场景。
- ✅ 通过备用路径找到 Hermes 且 `hermes --version` 成功时，将结果视为安装成功，并提示当前应用 PATH 已修复、仍需完成 `hermes setup`。
- ✅ 安装脚本真实失败时，失败文案提示用户查看上方安装日志中的错误详情。
- ✅ 修复 `apps/installer/hermes_install.py` 中已有 `Dict[str, any]` 类型标注问题，相关文件 diagnostics 清零。
- ✅ 新增回归测试覆盖 ANSI 错误日志保留、`exit=1` 后通过备用路径识别已安装 Hermes。
- ✅ 相关测试：`python -m pytest tests/test_hermes_installer.py` → 8 passed。
- ✅ 全量测试：`python -m pytest` → 425 passed，1 warning（已有重复 ZIP entry 警告）。
- ✅ `git diff --check` → passed。

### Milestone 72 — 备份清理与导入源安全收敛

- ✅ `find_backups()` 只纳入严格匹配托管命名规则的 `hermes-yachiyo-backup-YYYYMMDD-HHMMSS[-N].zip`，不再把 `*-draft.zip` / `*-external.zip` 等前缀相似文件纳入管理列表。
- ✅ `cleanup_old_backups()` 删除旧备份时若遇到 `ValueError`，会记录 warning 并跳过该文件，避免自动清理导致 `create_backup(auto_cleanup=True)` 中断。
- ✅ `import_backup()` 恢复 `app-config` 前强制确认备份源是非 symlink 目录；若备份里是文件或非目录形态，会跳过并给出原因，不会替换目标配置目录。
- ✅ `import_backup()` 恢复 `yachiyo-workspace` 前同样强制确认备份源是非 symlink 目录，再检查初始化标识和目标安全性，避免文件替换目标工作空间目录。
- ✅ 新增回归测试覆盖不可管理删除错误跳过、非规范命名 ZIP 不进入 `find_backups()`、文件形态 app-config/workspace 源不会被恢复。
- ✅ 相关测试：`python -m pytest tests/test_uninstall.py` → 45 passed。
- ✅ 全量测试：`python -m pytest` → 423 passed。

### Milestone 71 — 受保护路径集合缓存

- ✅ `protected_paths()` 改为复用按当前 home 路径缓存的受保护路径集合，避免备份导入/卸载安全检查中反复执行多组 `exists()` / `resolve()`。
- ✅ `is_protected_path()` 直接查询缓存的 `frozenset`，不再为每次判断重新构造受保护路径集合。
- ✅ 移除 `protected_paths()` 中不可达且引用未定义 `home` 的旧 return，避免静态检查与后续维护误判。

### Milestone 70 — 备份 ZIP 解压实际写入限流

- ✅ `_extract_zip_safely()` 不再只依赖 `ZipInfo.file_size` 头部声明；解压成员改为分块读写，并按实际写入字节数校验单条目和总解压体积限制。
- ✅ 解压过程中一旦实际写入量超出单条目或总量限制，会中止并删除当前部分输出文件，避免恶意 ZIP 通过虚假 header 触发磁盘填充风险。

### Milestone 72 — Electron 固定前端与 Python Headless 后端

- ✅ 固定桌面壳改为 Electron + React/Vite/TypeScript，前端工作区落在 `apps/frontend/`，不再通过 pywebview 承载新 UI。
- ✅ 新增 `apps/desktop_backend/app.py`，Python 侧只负责 `HermesRuntime`、Bridge lifecycle 与本地能力边界，不创建桌面窗口。
- ✅ 新增 `apps/bridge/routes/ui.py`，提供 `/ui/dashboard`、`/ui/settings`、`/ui/chat/*`、`/ui/modes/{mode}/settings` 给 React renderer 调用。
- ✅ `hermes-yachiyo` 入口改为启动 Electron 前端；`hermes-yachiyo-backend` 可单独启动后端；旧 pywebview 入口保留为 `hermes-yachiyo-legacy-pywebview`。
- ✅ 前端移除 `window.pywebview.api` 调用，改用 HTTP bridge client；新增通用设置、模式设置、聊天和主控台 React 视图。
- ✅ Node 使用 `nvm install/use 20.19.0`，并用 Node 20.19 刷新 latest 前端依赖与 `apps/frontend/package-lock.json`；`npm audit` 当前为 0 vulnerabilities。
- ✅ Electron dev server 固定为 `127.0.0.1:5174` strict port，避免 5173 被占用时 Vite 自动漂移导致 Electron 加载错误端口。
- ✅ `hermes-yachiyo` 默认入口会优先使用 nvm Node 20.19；缺少前端 `node_modules/.bin` 工具时自动执行一次 `npm ci`，然后打开 Electron 前端并拉起 Python backend。
- ✅ `apps/desktop_launcher.py` 已补 Node 20.19+ 版本预检、前端子进程失败提示和 Ctrl-C/验证中断的无 traceback 退出；启动失败时会优先显示可操作原因，而不是裸 Python traceback。
- ✅ 已排查用户运行后仍像旧窗口的问题：当前 venv 的 `hermes-yachiyo` console script 曾残留为 `apps.shell.app:main`；重新 `pip install -e .` 后已刷新为 `apps.desktop_launcher:main`，旧入口仅在 `hermes-yachiyo-legacy-pywebview`。
- ✅ 已修复 React 主控台 `Failed to fetch` 红条成功后不清除的问题，并把网络失败文案改为“无法连接本地 Bridge”。Bridge 卡片兼容 `state/status/running` 字段。
- ✅ Electron main 新增按当前 `display_mode` 自动打开 Bubble/Live2D 透明表现态窗口；React LauncherView 新增第一版 Bubble/Live2D 表现态 UI 与打开对话/设置入口。完整旧 pywebview 表现态能力仍需继续迁移。
- ✅ Bubble/Live2D Electron 表现态已接入真实 Bridge 状态：新增 `/ui/launcher`、`/ui/launcher/ack`、`/ui/launcher/quick-message`，复用 `ChatBridge` 与 `LauncherNotificationTracker` 提供未读、处理中、最近回复和快捷输入；Electron 右键菜单已接入打开对话/主控台/设置/重开表现态/关闭表现态/退出应用。
- ✅ Electron 表现态窗口已支持位置持久化：新增 `/ui/launcher/position`，Electron 在 Bubble/Live2D 移动或缩放后防抖写回配置；Bubble 会按旧 pywebview 逻辑吸附最近屏幕边缘，Live2D 会保存位置和窗口尺寸。
- ✅ `/ui/launcher` 已补 Live2D 资源状态摘要，React 表现态可根据资源是否就绪调整 stage 视觉状态，为后续接入真实 Live2D renderer 准备数据边界。
- ✅ React ChatView 已对照旧 pywebview Chat Window 补回核心体验：500ms 处理中轮询、typewriter 渐进显示、Markdown 渲染、复制按钮、会话下拉、新对话/删除、executor badge，并通过 `/ui/chat/*` HTTP Bridge 接入。
- ✅ Electron Chat Window 已恢复旧 pywebview 单例语义：主控台、Bubble、Live2D 和任意 `openView('chat')` 都打开/置前同一个独立 Chat BrowserWindow，不再把 ChatView 装进主窗口或表现态小窗口；Chat 窗口内的“主控台”按钮会回到主窗口。
- ✅ React renderer 已加入 hash route 层：`#/`、`#/chat`、`#/settings`、`#/settings/bubble`、`#/settings/live2d`、`#/bubble`、`#/live2d` 等路由可在同一窗口内切换，并保留旧 `?view=` 兼容。
- ✅ Bubble/Live2D mode window 已加入 Electron 导航保护：表现态窗口只承载 launcher route，非 launcher 导航会被 Electron 转发到主窗口或 Chat 单例，避免 112×112 气泡里显示完整 ChatView。
- ✅ React 主控台已对照旧 pywebview Control Center 补回 Hermes、Workspace、Runtime/Bridge、Tasks、Integrations、会话摘要和模式入口等主要信息。
- ✅ React 通用设置页已补回旧 pywebview 主要内容：Hermes 诊断、Workspace 详情、显示模式、助手资料、Bridge 状态/漂移/重启、集成状态、应用设置、备份管理和卸载预览/执行入口。
- ✅ UI Bridge 已补旧 MainWindowAPI 操作路由：Hermes terminal/recheck、Bridge restart、backup status/create/restore/delete/open-location、uninstall preview/run，React 只调用 HTTP route，不复制业务逻辑。
- ✅ React 通用设置页已从只读状态页推进为字段级编辑表单：可编辑显示模式、助手称呼、助手人设、Bridge 启用/host/port、托盘入口；只提交与当前配置不同的字段到 `/ui/settings`，保存后重新拉取后端状态。浏览器实机检查确认真实 Bridge 数据能填充表单、待保存状态能正确启用按钮、非法端口会显示自定义错误且修正后自动清除。
- ✅ React Bubble/Live2D 模式设置页已从 JSON 预览推进为字段级编辑表单：Bubble 支持窗口尺寸、默认位置百分比、置顶、吸附、启动展开、头像路径、默认展示、摘要条数、未读灯、自动淡出、透明度和主动观察；Live2D 支持模型/路径、窗口位置尺寸、缩放、置顶/Spaces、回复气泡、启动表现、点击行为、快捷输入、鼠标跟随、动作/表情/物理开关、主动观察和 Live2D TTS。表单只提交差异字段到 `/ui/settings`，保存后重新读取 `/ui/modes/{mode}/settings`。
- ✅ React Live2D 模式设置页已恢复旧 pywebview 的资源操作入口：`选择模型目录` 和 `导入资源包 ZIP` 由 Electron 原生文件选择器选取路径，Bridge 负责验证/导入并返回 `live2d_mode.model_path` 草稿；`打开导入目录` 走 Electron `shell.openPath`，`打开 Releases` 走 Electron `shell.openExternal`。选择/导入不会直接保存配置，仍需用户点击 `保存更改`。
- ✅ 已修复无桌面 preload/IPC 场景的两处回归：Live2D 资源区在没有 Electron 文件选择器时会显示内联“模型目录路径 / 资源包 ZIP 路径”输入框，按钮改为按路径检查/导入；Bubble 点击在无 `openView` IPC 时不再把 ChatView 塞进 112×112 表现态窗口，而是打开新的 `view=chat` 窗口/标签。
- ✅ 已收紧“React renderer ≠ 产品运行态”的边界：产品态必须通过 Electron 桌面壳运行，浏览器/Vite 只作为开发 fallback；`hermes-yachiyo` 在发现 `127.0.0.1:5174` 已有 Vite dev server 时会复用它并直接启动 Electron，不再因为 strict port 占用退出。Live2D 透明 pointer passthrough 改为实验能力，默认关闭，以“表现态可点击/可右键/可操作”优先；Live2D 舞台、角色、资源提示、回复气泡和快捷输入已从 Electron drag 区域中排除，避免 div 点击被窗口拖拽吞掉；需要测试透明穿透时显式设置 `HERMES_YACHIYO_LIVE2D_POINTER_PASSTHROUGH=1`。
- ✅ 已用 Downloads 中真实资源包 `hermes-yachiyo-live2d-yachiyo-20260423.zip` 做模拟导入验证：临时目录导入识别到 1 个 `.model3.json` 和 1 个 `.moc3`，草稿预览 `model_state=path_valid`，`renderer_entry` 指向 `八千代辉夜姬.model3.json`；直接调用 `/ui/live2d/archive/import` 路由函数并将导入根目录替换为临时目录后同样返回成功，真实 `config.live2d_mode.model_path` 保持为空，未持久化用户配置。
- ✅ Electron Bubble 已对照旧 pywebview 表现恢复头像气泡结构：Bridge 返回头像 data URI、`expand_trigger`、`suppress_status_dot`、主动桌面观察状态；React 恢复旧 `.bubble-launcher` / `.portrait` / `.status-dot` 视觉、未读/处理中/失败状态点、auto-hide 透明度公式、title 提示和 6px 拖拽点击阈值。
- ✅ Electron Live2D 已完成第一步旧表现还原：Bridge 返回 preview data URI、resource 状态和 renderer scaffold；React 恢复预览图 fallback、资源提示条、默认打开行为、回复气泡、快捷输入和处理中/有消息发光状态。真实 Pixi/Cubism 模型渲染、鼠标跟随和透明命中区域仍是下一步。
- ✅ Electron Live2D 已接入第一版真模型渲染路径：Bridge 新增 `/live2d/runtime` 与 `/live2d/runtime/{dependency_id}`，复用旧 pywebview 的 Pixi/Cubism 依赖缓存；React 按顺序加载 runtime scripts，使用 `renderer.model_url` 创建 Pixi Application 与 Live2DModel，模型加载成功后淡出 preview，失败时保留静态预览并显示错误；已补窗口内鼠标跟随 focus。透明命中区域、全局鼠标同步、动作/表情细节仍待迁移和实机验证。
- ✅ Electron Live2D 已接入第一版透明命中区域：Electron main 新增 `setLauncherPointerInteractive` 窄 IPC 并用 `BrowserWindow.setIgnoreMouseEvents(..., { forward: true })` 切换空白区域穿透；React 从 preview/canvas 生成 alpha mask，并把资源提示、回复气泡、快捷输入作为 UI 命中区域参与判定。仍需真实模型实机验证穿透、拖拽和全局鼠标同步边界。
- ✅ 文档新增 `docs/desktop-frontend-architecture.md`，`docs/ui-resource-architecture.md` 改为 legacy 记录。
- ✅ 手工启动基线：`hermes-yachiyo` 已确认走当前 venv 的 `apps.desktop_launcher:main`，启动后拉起 Vite `127.0.0.1:5174`、Electron、Python backend 与 Bridge `127.0.0.1:8420`；日志中 `/ui/dashboard` 与 `/ui/launcher?mode=bubble` 返回 200。验证结束时的 exit 130 来自手动中断，不是应用主动崩溃。
- ✅ 验证：`npm --prefix apps/frontend run build` 通过；设置页浏览器实机检查通过，包括通用设置、Bubble 模式设置和 Live2D 模式设置的真实数据填充、待保存状态、非法数值提示与恢复原值同步状态；新增 Live2D 资源入口后再次 `npm --prefix apps/frontend run build` 通过；真实 Downloads Live2D ZIP 临时导入和 Bridge 路由模拟导入通过；无桌面 IPC 浏览器场景验证通过：资源区显示内联 ZIP 路径输入且空路径提示正常，Bubble 点击保持 `view=bubble` 并通过 `window.open(...view=chat)` 打开对话；Electron 运行态短启动验证确认 Vite + Electron 进程能拉起；最新 `npm --prefix apps/frontend run build` → 通过，`dist/assets/index-BB_YwRRT.css` / `dist/assets/index-DklLRZW3.js`；最新 `pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 18 passed；`pytest tests/test_ui_bridge_routes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 45 passed；`pytest tests/test_ui_bridge_routes.py tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 48 passed；`pytest tests/test_bridge_server.py tests/test_ui_bridge_routes.py tests/test_chat_bridge.py tests/test_mode_settings.py tests/test_chat_api.py tests/test_desktop_launcher.py` → 119 passed；相关 VS Code diagnostics 无错误。此前 `pytest tests/test_ui_bridge_routes.py tests/test_bridge_server.py tests/test_chat_api.py tests/test_mode_settings.py tests/test_runtime.py` → 57 passed；`npm --prefix apps/frontend run dev` 已拉起 Electron、Python backend，并看到 renderer 请求 `/ui/dashboard` 200。
- ✅ 最新追加验证：`npm --prefix apps/frontend run build` 通过；`/Users/cxldefontaine/个人项目/Hermes-Yachiyo/.venv/bin/python -m pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 19 passed；VS Code diagnostics 对最新改动文件无错误。

### UI 资源分离第一阶段

- ✅ 新增 `apps/shell/ui/styles/` 作为 pywebview 前端视觉资源目录，主控台、安装页、聊天窗、模式设置、Bubble、Live2D 的视觉覆盖样式已从 Python 字符串迁出。
- ✅ 新增 `read_ui_asset()` / `inject_css()`，Python 只保留窗口创建、JS API 绑定和占位符替换，视觉层通过外部 CSS 注入。
- ✅ `pyproject.toml` 已加入 `apps.shell.ui` package-data，确保 editable / wheel 安装时 CSS 资源随包分发。
- ✅ 清理前期 UI 探索生成的一次性 patch 脚本，仓库只保留正式源码与资源文件。
- ✅ 相关验证：`/usr/local/bin/python3 -m pytest tests/test_chat_window.py tests/test_chat_bridge.py tests/test_mode_settings.py` → 89 passed。
- ✅ 资源加载验证：`read_ui_asset("styles/elegant.css")`、`_CHAT_HTML`、`_BUBBLE_HTML` 均确认能读取/注入外部 CSS。

### UI / Visual Overhaul (Gemini Aesthetic Pass)

- ✅ Refactored the UI across all modules (chat_window, window, settings, mode_settings, bubble, live2d) focusing strictly on visual representation without altering underlying Python execution logic or string injection markers.
- ✅ Replaced the rigid, high-contrast Tsukuyomi cyberpunk design with an elegant macOS-inspired "Glassmorphism" deep dark theme (`--bg-main: #0B0E14`).
- ✅ Implemented radial lighting, smooth transition animations, and subpixel-antialiased typography using `SF Pro Text` / system fonts.
- ✅ Successfully restored broken mode setting configurations (like bubble size and opacity configurations mapping in `settings.py`) by isolating CSS block injection instead of full string replacement.
