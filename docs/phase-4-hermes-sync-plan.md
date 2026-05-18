# Phase 4 重构计划：Agent Studio + Workflow Studio + Skill Import

## Summary

Phase 4 放弃旧 Coding/Provider 集成路线。Yachiyo 不再管理第三方 CLI/daemon，也不再提供专门的 Coding Job runtime。

新方向是把 Yachiyo 做成本地个人 Agent 的 GUI 编排中心：

- Agent Studio：用 GUI 创建、编辑、测试和运行 Agent。
- Skill Library：导入本地 Skill，并挂载到 Agent。
- Workflow Studio：用可视化节点把多个 Agent 编排成线性可运行流程。
- Model Profiles：统一保存、测试和复用文本 / Vision / TTS 模型配置。
- Chat 入口：普通消息继续走 Hermes Chat；`@Name 需求` 或 Composer 选择器会启动指定 Agent / Workflow。

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
- 模型配置页改为 Model Profiles 管理：
  - 文本模型。
  - 图片识别模型。
  - TTS Profile。
- Profile API Key 仅保存在后端；前端只显示 `api_key_configured`。
- 空 API Key 更新不会覆盖旧密钥。
- Agent 可选择 `follow_main` 或引用已保存的 `model_profile_id`。
- 设置页“模型”区域改为新版模型配置入口，不再直接承担连接测试表单。

## 新增接口

- `GET/POST /ui/model-profiles`
- `GET/PATCH/DELETE /ui/model-profiles/{profile_id}`
- `POST /ui/model-profiles/{profile_id}/test`
- `PATCH /ui/model-profiles/defaults`
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
- Tool Broker 只暴露受控工具：
  - `workspace.list`
  - `workspace.read`
  - `workspace.write_patch`
  - `terminal.run`
  - `artifact.write`
- `terminal.run` 默认需要审批。
- 文件读写必须落在 Agent workspace policy 范围内。
- Artifact 写入有路径越界保护。
- Skill scripts 不执行。
- API Key 和命令日志走脱敏。

## 当前限制

- Workflow v1 只做线性流程，不做分支、并行、条件表达式和失败回退。
- `follow_main` Agent 首版会整理运行上下文并记录产物；后续再接入更完整的 Hermes orchestrator streaming。
- `profile` Agent 首版支持 OpenAI-compatible Chat Completions 与简单受控工具循环。
- 旧 `custom_api` Agent 作为兼容路径保留，新增 Agent 默认使用 `follow_main` 或 Model Profile。
- TTS Profile 首版做统一保存与复用入口，具体语音服务仍由 TTS 专用链路执行。
- Skill v1 只支持本地目录/ZIP，不做远程 marketplace，也不自动扫描用户全局 skills。
- 第三方 CLI/daemon 由用户自行管理，不再由 Yachiyo 安装、登录、升级或托管。

## 验证目标

- 删除回归：
  - 业务代码不再包含旧编码服务、旧编码 routes、旧编码页面和第三方 CLI provider ID。
- 后端：
  - Agent CRUD。
  - Model Profile CRUD、密钥脱敏、空 key 不覆盖、默认 Profile 校验。
  - Agent 引用 Model Profile 后可创建 run。
  - Skill 导入、ZIP 路径穿越拒绝。
  - Workflow 线性校验。
  - Tool Broker 越界与审批保护。
  - Chat `@Agent` 创建 run 且不创建普通 Hermes task。
- 前端：
  - Agent Studio 创建/编辑 Agent，挂载 Skill。
  - Skill Library 导入、预览、删除 Skill。
  - Workflow Studio 拖拽、连线、保存、运行。
  - Chat 选择 Agent / Workflow 或输入 `@Name` 能创建 run。
  - `npm --prefix apps/frontend run build` 通过。
