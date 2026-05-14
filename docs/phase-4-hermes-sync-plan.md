# Phase 4：受控 Coding Execution Service

## Summary

Phase 4 的方向从“继续同步 Hermes 能力”调整为“建立 Yachiyo 的本地工作流控制层”。

Hermes 可以参与理解需求、整理上下文、调用通用工具，但不承担 coding job runtime。Yachiyo 前端不直接调用 shell。Yachiyo 后端新增受控 `CodingExecutionService`，统一管理编码任务、审批、执行、产物、日志、review 和恢复。

Hapi 保留为未来可替换的外置执行层，不作为当前 Phase 4 的必需依赖。

`CodingExecutionService` 不假设用户一定安装或订阅 Claude Code、Codex、OpenDesign 等外部工具。所有 provider 都必须通过 health check 判断可用性，并向 UI 暴露可用状态、阻塞原因、安装建议和 fallback 选项。

Claude Code 支持 `claude -p` 非交互/headless 模式，并可配合 `--allowedTools`、`--output-format` 等参数使用，适合被后端 provider 受控调用。Codex CLI 支持 review uncommitted changes、review against base branch、review commit 等 review 模式，适合作为可选 review provider。OpenDesign 当前更像 local-first Web/Desktop 设计工作台，因此在 Phase 4 中应作为可选设计 artifact provider，而不是硬依赖。

---

## Progress Log

### 2026-05-14：Phase 4 MVP Implementation

本日完成 Phase 4 从目标说明到首版可运行实现的落地，范围集中在受控 coding runtime、`/start-code` 入口、Provider 配置与 OpenDesign 独立管理。

#### Batch 1：CodingExecutionService 后端与 API

```text
完成：
- 新增 CodingExecutionService，落地 coding.db、artifacts/coding/<job_id>/、runs/coding/<job_id>/。
- 实现 job 状态机、approval gate、manual review fallback、mock provider、local_claude_code provider skeleton、codex_review skeleton。
- 实现 provider registry、health check、installer allowlist、安装进度轮询、日志脱敏、artifact 路径越界保护。
- 实现 git repo 校验、dirty warning、独立分支 ai/coding/<job_id>、writable_scopes 执行后校验和 rollback artifact。
- 新增 /ui/coding/* Bridge API。
```

主要文件：

```text
apps/shell/coding_execution.py
apps/bridge/routes/coding.py
apps/bridge/server.py
tests/test_coding_execution.py
```

#### Batch 2：Chat `/start-code` 入口

```text
完成：
- ChatAPI.send_message() 优先解析 /start-code，避免创建普通 Hermes task。
- 支持 repo/scope/provider/review/task/design flags，并在缺少 repo 时返回 Coding Defaults 配置引导。
- 成功创建 awaiting_approval job 后返回 coding_job_id。
- 前端 Chat 收到 coding_job_id 后跳转 Coding detail。
```

主要文件：

```text
apps/shell/chat_api.py
apps/frontend/src/views/ChatView.tsx
tests/test_chat_api.py
```

#### Batch 3：Coding 配置中心 UI

```text
完成：
- 新增 Coding 页面和导航入口。
- Providers 聚焦 Claude Code CLI 与 Codex CLI。
- Claude/Codex 支持 CLI Login 与 API Env 两种凭据模式。
- API Env 模式保存 ANTHROPIC_* / OPENAI_*，执行时使用隔离 HOME，避免误用本机付费登录态。
- Defaults 仅保留 /start-code 缺省策略，不再承载 provider 凭据配置。
- Job Detail 展示 plan、approval、timeline、artifacts、review、rollback。
```

主要文件：

```text
apps/frontend/src/views/CodingJobsView.tsx
apps/frontend/src/lib/coding.ts
apps/frontend/src/App.tsx
apps/frontend/src/lib/bridge.ts
apps/frontend/src/lib/view.ts
apps/frontend/src/views/OpenDesignView.tsx
apps/frontend/src/styles/app.css
```

#### Batch 4：OpenDesign 独立管理

```text
完成：
- OpenDesign 从通用 provider card 拆出，进入 Coding > OpenDesign 独立面板。
- 支持“本机已有 OpenDesign”：用户填写 Daemon URL，保存并测试 /api/health。
- 支持“安装到 Yachiyo 管辖目录”：clone 官方仓库、Node 24/corepack/pnpm install、后台启动 pnpm tools-dev run web。
- 启动后从 OpenDesign 日志解析 Web 与 Daemon 两个动态端口，并写回配置。
- “打开 WebUI”只使用 Web URL，不再误用 daemon URL。
- “检查版本并升级”仅支持 Yachiyo 管辖目录，对比 GitHub 远端 commit，必要时 pull/install/restart，并重新更新端口。
- OpenDesign scan 只检查项目存在，不再错误探测尚未启动的 daemon。
```

主要文件：

```text
apps/shell/coding_execution.py
apps/frontend/src/views/CodingJobsView.tsx
apps/frontend/src/styles/app.css
tests/test_coding_execution.py
```

#### Validation

```text
python -m py_compile apps/shell/coding_execution.py
uv run pytest tests/test_coding_execution.py
PATH="$HOME/.nvm/versions/node/v20.19.0/bin:$PATH" npm --prefix apps/frontend run build
```

结果：

```text
tests/test_coding_execution.py：16 passed
frontend build：passed
```

备注：

```text
- 本机默认 Node 18 不满足 Vite 要求，前端 build 使用 Node 20.19.0。
- apps/frontend/bin 与 apps/frontend/lib 属于 npm 全局安装误落到项目目录的副产物，已加入 .gitignore。
- OpenDesign 自有项目由用户自行更新；Yachiyo 自动升级只管理 Yachiyo 管辖目录。
```

---

## Core Positioning

Phase 4 的核心不是“多接几个工具按钮”，而是让 Yachiyo 拥有一个受控、可审批、可审计、可恢复、可降级、可展示产物的本地 coding workflow runtime。

角色边界如下：

```text
Hermes
- 理解用户需求
- 整理 coding brief
- 调用通用 Agent/tool 能力
- 作为 capability source 之一

Yachiyo Frontend
- 展示计划
- 展示 provider 状态
- 提供审批入口
- 展示时间线、日志、产物、review 和回滚建议

Yachiyo Backend
- CodingExecutionService
- Job 状态机
- Provider Registry
- Review Provider Registry
- Artifact Store
- Safety Policy
- Health Check / Onboarding / Fallback

Claude Code CLI
- 可选 coding provider

Codex CLI
- 可选 review provider

OpenDesign
- 可选 design artifact provider

Hapi
- 未来外置 coding execution backend
- 当前不作为 Phase 4 blocker
```

---

## Key Changes

### 1. 新增 `CodingExecutionService`

新增后端服务，负责管理 coding job 的完整生命周期。

Job 状态：

```text
draft
planning
blocked
awaiting_approval
running
reviewing
completed
failed
cancelled
```

推荐状态流转：

```text
draft
  -> planning
  -> blocked / awaiting_approval
  -> running
  -> reviewing
  -> completed

任意可中断状态：
  -> failed
  -> cancelled
```

状态含义：

```text
draft：用户刚创建任务，尚未生成计划。
planning：生成 brief、执行计划、风险说明、provider 选择、review 策略和可写范围。
blocked：缺少必要 provider、未登录、无订阅、OpenDesign artifact 缺失、repo 无效等，需要用户处理或选择 fallback。
awaiting_approval：计划已生成，等待用户确认。所有写入型 job 必须经过此状态。
running：coding provider 正在执行。
reviewing：执行完成后进入 review 阶段。可使用 Codex、同 provider 自评、Hermes review、manual checklist 或跳过。
completed：任务完成，产物、diff、review 和回滚建议已生成。
failed：任务失败，但需要保留计划、日志、产物和下一步建议。
cancelled：用户取消任务。
```

---

### 2. 数据与产物路径

持久化数据库：

```text
~/.hermes/yachiyo/coding.db
```

用户可见产物：

```text
~/.hermes/yachiyo/artifacts/coding/<job_id>/
```

原始运行记录：

```text
~/.hermes/yachiyo/runs/coding/<job_id>/
```

推荐目录结构：

```text
~/.hermes/yachiyo/
├── coding.db
├── artifacts/
│   └── coding/
│       └── <job_id>/
│           ├── brief.md
│           ├── plan.md
│           ├── provider-status.json
│           ├── review-provider-status.json
│           ├── opendesign/
│           ├── patch.diff
│           ├── review.md
│           ├── manual-review-checklist.md
│           └── rollback.md
└── runs/
    └── coding/
        └── <job_id>/
            ├── provider.json
            ├── command.json
            ├── stdout.log
            ├── stderr.log
            ├── exit.json
            └── redacted-env.json
```

---

## Provider Registry

### Provider 类型

Phase 4 首版建议包含：

```text
local_claude_code
- 本地 Claude Code CLI provider
- 用于 coding job
- 未检测到 claude 命令、未登录或不可执行时标记 unavailable

codex_review
- 本地 Codex CLI review provider
- 只用于 review
- 具体 review 命令由本机 Codex CLI 版本和 help 输出探测决定

opendesign
- 设计 artifact provider
- 可选
- 不作为 coding workflow 硬依赖

hapi
- 未来外置 provider
- 通过 HTTP job API 接入
- 当前不阻塞 Phase 4

noop/mock
- 测试 provider
- 用于单元测试和 UI 开发
```

### Provider Availability

不要只返回 `available: true/false`。建议统一为：

```ts
type ProviderAvailability =
  | "available"
  | "not_installed"
  | "not_authenticated"
  | "subscription_required"
  | "unsupported_platform"
  | "misconfigured"
  | "disabled_by_user"
  | "unknown_error"
```

Provider 状态建议：

```ts
type ProviderStatus = {
  id: string
  display_name: string
  role: "coding" | "review" | "design" | "mock"
  availability: ProviderAvailability
  version?: string
  executable_path?: string
  blocking_reason?: string
  install_hint?: string
  auth_hint?: string
  docs_url?: string
  can_install_from_ui?: boolean
  can_open_docs?: boolean
  risk_level: "low" | "medium" | "high"
}
```

### Health Check 分层

Provider health check 至少分四层：

```text
installed：命令是否存在。
runnable：能否执行 --version / --help / doctor。
authenticated：是否已经登录，或是否具备可用凭据。
capability_ready：是否支持当前 job 所需能力。
```

示例：

```text
local_claude_code
- installed: 检测 claude 命令
- runnable: 检测 claude --version 或等价命令
- authenticated: 检测当前用户是否已登录
- capability_ready: 检测是否可用于 headless coding job

codex_review
- installed: 检测 codex 命令
- runnable: 检测 codex --version 或 codex --help
- authenticated: 检测 Codex CLI 是否可用
- capability_ready: 探测是否支持 review uncommitted / base branch / commit review
```

---

## Review Strategy

Review 不应硬依赖 Codex。Codex 是优先 provider，但不是唯一 provider。

推荐 review 策略：

```ts
type ReviewStrategy =
  | "codex_if_available"
  | "same_provider"
  | "any_available_agent"
  | "manual_only"
  | "none"
```

含义：

```text
codex_if_available：优先使用 Codex review。Codex 不可用时进入 blocked 或提示用户选择 fallback。
same_provider：由执行 coding job 的 provider 自评，例如 Claude Code 实装后让 Claude Code 自查。
any_available_agent：从可用 review providers 中选择一个，例如 Codex、Claude Code、Hermes provider、MiMo、opencode。
manual_only：不调用 Agent，只生成 diff、测试结果和 review checklist，让用户自己审查。
none：不进行 review，只展示改动、测试结果和回滚建议。
```

### Review Provider Registry

建议新增：

```text
codex_review
- 优先 review provider
- 仅在 Codex CLI installed + authenticated + review_capable 时可用

same_provider_review
- 使用完成 coding job 的 provider 进行自评

hermes_review
- 使用 Hermes 当前可用模型进行 prompt-based diff review

manual_review
- 不调用 Agent，只生成 checklist 和 diff artifact
- 始终可用

noop_review
- 测试用
```

UI 表达建议：

```text
Codex Review：不可用，原因：未安装 / 未登录 / 需要订阅
可选操作：
- 查看安装说明
- 使用 Claude Code 自评
- 使用 Hermes Review
- 只生成 Manual Checklist
- 跳过 Review
```

没有 Codex 不应显示为任务失败，而应显示为：

```text
Codex Review unavailable, fallback required.
```

---

## Design Mode / OpenDesign Fallback

OpenDesign 也不应是硬依赖。

推荐设计模式：

```ts
type DesignMode =
  | "none"
  | "opendesign_if_available"
  | "opendesign_required"
  | "brief_only"
  | "import_existing_artifact"
```

含义：

```text
none：不需要设计步骤。
opendesign_if_available：有 OpenDesign 就使用或引导导入 artifact；没有则降级为 brief_only。
opendesign_required：必须有 OpenDesign artifact，否则 job 进入 blocked。
brief_only：只生成产品/设计 brief，不使用 OpenDesign。
import_existing_artifact：用户手动导入截图、HTML、Markdown、设计说明等 artifact。
```

---

## Job API

### Public Interfaces

```text
GET  /ui/coding/providers
POST /ui/coding/providers/{provider_id}/health-check

GET  /ui/coding/review-providers

POST /ui/coding/jobs
GET  /ui/coding/jobs/{job_id}
POST /ui/coding/jobs/{job_id}/approve
POST /ui/coding/jobs/{job_id}/cancel
GET  /ui/coding/jobs/{job_id}/artifacts

POST /ui/coding/jobs/{job_id}/select-provider
POST /ui/coding/jobs/{job_id}/select-review-strategy

GET  /ui/coding/install-guides/{provider_id}
```

### Create Job Request

```ts
type CreateCodingJobRequest = {
  user_request: string
  repo_path: string

  task_type:
    | "ui_redesign"
    | "bugfix"
    | "refactor"
    | "docs"
    | "packaging_check"
    | "custom"

  writable_scopes: string[]
  readonly_scopes?: string[]

  design_mode?:
    | "none"
    | "opendesign_if_available"
    | "opendesign_required"
    | "brief_only"
    | "import_existing_artifact"

  preferred_provider?:
    | "local_claude_code"
    | "hapi"
    | "noop"

  review_strategy?:
    | "codex_if_available"
    | "same_provider"
    | "any_available_agent"
    | "manual_only"
    | "none"

  allow_install_suggestions?: boolean

  branch_policy?: {
    create_branch: boolean
    branch_prefix?: string
  }

  test_commands?: string[]
  build_commands?: string[]

  constraints?: string[]
}
```

### Create Job Response

```ts
type CreateCodingJobResponse = {
  job_id: string
  status:
    | "draft"
    | "planning"
    | "blocked"
    | "awaiting_approval"

  plan_summary: string
  risk_level: "low" | "medium" | "high"
  requires_approval: boolean

  selected_provider?: string
  selected_review_provider?: string
  selected_design_mode?: string

  blockers: Array<{
    provider_id?: string
    reason:
      | "not_installed"
      | "not_authenticated"
      | "subscription_required"
      | "unsupported_platform"
      | "misconfigured"
      | "user_action_required"

    message: string

    suggested_actions: Array<{
      type:
        | "open_install_docs"
        | "open_auth_guide"
        | "switch_provider"
        | "skip_review"
        | "manual_review"
        | "import_artifact"
        | "cancel"

      label: string
      payload?: Record<string, unknown>
    }>
  }>

  fallback_options: Array<{
    id: string
    label: string
    consequence: string
  }>
}
```

---

## Safety Policy

### 前端边界

```text
- 前端只能调用 workflow/job API。
- 前端不能提交任意 shell 命令。
- 前端不能绕过审批直接启动写入型 job。
```

### 后端执行边界

```text
- 所有 provider 必须来自后端白名单。
- provider 必须绑定工作目录。
- 默认只允许在 git 仓库内执行。
- 默认在独立分支执行，例如 ai/coding/<job_id>。
- 所有写入型 job 必须先进入 awaiting_approval。
- 执行后必须校验实际变更文件是否全部位于 writable_scopes 内。
- 如果发现越界文件变更，job 标记为 failed，并提示回滚。
```

### 默认禁止动作

```text
- sudo
- dangerous / bypass permission mode
- rm -rf
- chmod -R
- chown
- curl | bash
- git push --force
- 删除分支
- 修改 SSH key / keychain / 系统安全配置
- launchctl
- codesign，除非 packaging workflow 明确审批
```

### 安装建议边界

```text
- Provider 不可用时，Yachiyo 可以展示安装建议和官方文档入口。
- Phase 4 首版不自动执行安装命令。
- 如果未来支持一键安装，必须单独审批。
- 一键安装前必须展示即将执行的命令、来源、风险和回滚方式。
- 安装来源必须是官方文档或项目配置的可信源。
```

---

## Coding Workflow v1

首个垂直闭环：设计到代码。

流程：

```text
1. 用户在 Chat 中描述需求。
2. Hermes / Chat 生成 coding brief。
3. 如果任务涉及 UI：
   - design_mode = opendesign_if_available 时，尝试使用或导入 OpenDesign artifact。
   - OpenDesign 不可用时降级为 brief_only。
   - 如果 design_mode = opendesign_required 且 artifact 缺失，则 job 进入 blocked。
4. Yachiyo 生成执行计划：目标仓库、可写范围、只读范围、provider、review 策略、测试命令、风险说明、预计产物。
5. 用户审批。
6. CodingExecutionService 启动 provider。
7. provider 执行完成后收集 stdout/stderr 摘要、changed files、git diff、test/build 结果、patch artifact。
8. 进入 review：Codex 可用则 Codex review；Codex 不可用则根据策略选择 same_provider_review / hermes_review / manual_review / none。
9. UI 展示时间线、计划、产物、文件变更、测试结果、review 结论和回滚建议。
```

---

## UI 最小页面

Phase 4 MVP 建议先做一个页面：

```text
Coding Jobs
```

页面模块：

```text
Provider Status
- Claude Code
- Codex Review
- OpenDesign
- Hapi
- Mock

Create Job
- repo path
- task type
- user request
- writable scopes
- design mode
- coding provider
- review strategy

Plan & Approval
- plan summary
- risk level
- blockers
- fallback options
- approve / cancel

Job Timeline
- planning
- approval
- running
- reviewing
- completed / failed

Artifacts
- brief.md
- plan.md
- patch.diff
- review.md
- rollback.md
- logs
```

---

## Test Plan

### Unit Tests

```text
Provider health check
- claude 缺失时 local_claude_code = not_installed
- codex 可执行时 codex_review 返回版本信息
- codex 未登录/无订阅时返回 not_authenticated 或 subscription_required
- hapi 未配置时不阻塞 Phase 4
- mock provider 始终可用于测试

Job state machine
- draft -> planning -> awaiting_approval
- planning -> blocked
- awaiting_approval -> running
- running -> reviewing
- reviewing -> completed
- 任意运行中状态可 cancel
- 失败后保留日志和产物

Approval gate
- 未审批 job 不能启动本地 CLI
- 写入型 job 必须等待 approve
- 只读/manual review 可以不要求写入审批

Artifact security
- artifact 路径越界保护
- 日志脱敏
- redacted-env.json 不包含 API key 明文
- patch.diff 可读取但不能越权写入

Writable scope validation
- provider 执行后检查 changed files
- 越界变更导致 job failed
- UI 提示回滚建议

Review fallback
- Codex 可用时优先 Codex review
- Codex 不可用时走 same_provider_review
- 没有 Agent review 时生成 manual checklist
- 用户选择 none 时跳过 review
```

### API Tests

```text
GET /ui/coding/providers 返回 provider 状态和 blocker。
POST /ui/coding/jobs 能创建 job 并返回 plan/blockers/fallback_options。
未审批 job 调用 approve 前不会启动 CLI。
provider 不可用时返回明确 blocker。
review_strategy=codex_if_available 且 Codex 不可用时，返回 fallback options。
opendesign_required 但缺少 artifact 时，job 进入 blocked。
前端无法提交任意 shell 命令。
执行失败后仍能读取计划、日志和产物。
```

### Manual Acceptance

```text
1. 从 Chat 发起一个小 UI 改动。
2. 生成 coding brief。
3. 如果 OpenDesign 可用，生成或导入设计 artifact；否则 brief_only。
4. Yachiyo 展示计划和风险。
5. 用户审批。
6. 本地 coding provider 执行。
7. 收集 diff 和测试结果。
8. Codex 可用则 review，不可用则 fallback。
9. Yachiyo 页面能完整展示计划、执行、产物、review 和下一步。
```

---

## Assumptions

```text
- Phase 4 不要求 Hapi 先完成。
- Hermes 可以作为意图和工具入口，但不直接拥有 coding runtime。
- 用户不一定安装 Claude Code、Codex、OpenDesign。
- 用户不一定有 Codex 订阅。
- Review 是可插拔、可降级、可跳过的阶段。
- OpenDesign 是可选 design artifact provider，不是硬依赖。
- 首版只做用户确认后的半自动编码。
- 首版不做无审批桌面控制。
- 首版不自动外发邮件、push 代码或执行安装命令。
```

---

## Non-goals

Phase 4 首版不做：

```text
- 自动安装 Claude Code / Codex / OpenDesign
- 自动 git push
- 自动发 PR
- 自动外发邮件
- 无审批执行写入型任务
- 远程 coding job 队列
- 多机器分布式执行
- 完整 Hapi 外置化
- 完整办公秘书闭环
```

---

## Recommended MVP Cut

为了避免 Phase 4 过大，MVP 建议只做：

```text
1. Provider Registry
2. Provider health check
3. Coding job 状态机
4. Artifact/runs 目录
5. local_claude_code provider skeleton
6. codex_review provider skeleton
7. manual_review fallback
8. mock provider
9. 最小 Coding Jobs UI
10. 未审批不能执行的安全 gate
```

暂缓：

```text
- Hapi
- 自动安装
- Cron/主动关怀
- 邮件外发
- 多 Agent 自动竞标
- 远程执行
```

---

## Final Decision

Phase 4 最终判断：

```text
Yachiyo 不应该只是 Hermes 的聊天壳。
Yachiyo 应该成为本地个人 Agent 的工作流控制层。

Hermes 负责通用 Agent 能力。
Yachiyo 负责上下文、审批、产物、进度、恢复和用户体验。
CodingExecutionService 负责受控执行 coding jobs。
Claude Code / Codex / OpenDesign 都只是可插拔 provider。
Hapi 是未来外置化选项，不是当前 blocker。
```

一句话版本：

```text
Phase 4 的目标是建立一个受控、可审计、可恢复、可降级的本地 coding workflow runtime。
```
