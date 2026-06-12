# oha-yachiyo Native Runtime Systemic Audit

日期：2026-06-09（更新：2026-06-10）

参考规格：`/Users/cxldefontaine/Desktop/oha-yachiyo_agent_runtime_plan.md`

## 结论

当前工程已经超过 PR-1 的范围：TaskRunner / Task API / AppState / ChatSession 保留，主执行路径已切到 `NativeAgentExecutor` 和 `NativeRunEngine`，并且生产源码中的 Hermes 产品身份和执行入口残留已清零。

按设计书最终目标衡量，当前大致状态：

- 执行内核替换：约 95%。
- v0.5 功能保留合同：约 96%。
- PR-4 Hermes 删除与发布验收：约 95%。
- Harness 风格架构完整度：约 96%。

这里的 Harness 风格指：Run 作为执行事实、事件可回放、工具有 descriptor/policy/approval/budget、Workflow/Agent Studio/Chat 共享同一个 NativeRunEngine。当前行为骨架已经具备，但组件边界和 replay/projection 成熟度还没到最终形态。

## 本轮完成项

### 生产源码 Hermes 残留清零

扫描范围：

```text
apps integrations packages scripts pyproject.toml
排除 apps/frontend/dist、dist-electron、__pycache__、node_modules
```

结果：

```text
0 matches for Hermes/hermes/HERMES
```

已清理的主要类别：

- Electron preload / IPC / route-change 从旧命名迁到 `oha*`。
- Dashboard/settings 状态协议只保留 `native_agent`。
- Tool config 协议只保留 `native_toolsets`。
- ModelProfile 协议只保留 `native_provider` / `can_use_as_native`。
- ChatSession 字段迁移为 `execution_session_id`。
- CSS class、localStorage key、DOM data attribute、临时目录和资源 preset 改为 Oha/Native 命名。
- AstrBot 集成从 `HermesClient/hermes_url` 改为 `OhaClient/oha_url`，状态读取 `native_agent_ready`。
- 旧 `HermesRuntime = AppRuntime` 兼容别名已删除。
- 旧 Native CLI 兼容命令别名已删除；只允许 `native ...` 命令。
- Agent Studio 旧 Hermes source/backend 迁移映射已删除；旧 backend 作为 legacy/unknown 拒绝。

### Release 链路产品身份防回归

本轮修正了 release-facing 链路中仍指向旧产品身份的真实缺口：

- `.github/workflows/release-macos.yml`
  - 构建 metadata 输出从 `hermes-yachiyo-build.json` 改为 `oha-yachiyo-build.json`，与 `apps.core.build_metadata` 的运行时读取路径一致。
  - Release title、DMG、latest JSON、artifact name、自签名证书默认名和权限说明统一为 Oha-Yachiyo。
  - release workflow 增加 `python scripts/verify_release_artifacts.py`，在依赖安装前先验证发布身份。
- `.github/workflows/release-tts-assets.yml`
  - TTS 资源包 asset name 和 release notes 统一为 Oha-Yachiyo。
- `docs/release-packaging.md`
  - 打包说明从旧执行内核依赖改为 Native Agent runtime。
  - 后端产物、`.app` 路径、固定下载链接和权限说明统一为 Oha-Yachiyo / `oha-yachiyo`。
- `scripts/verify_release_artifacts.py`
  - 新增 release-facing verifier，默认扫描 macOS release workflow、TTS asset workflow、release packaging 文档、electron-builder 配置、backend packaging 脚本和 build metadata。
  - 检查旧 build metadata 文件名不得存在，且发布链路文件不得再包含旧产品 token。
  - verifier 源码避免直接写入连续旧 token，避免污染生产源码级 `rg Hermes` 扫描。
- `apps/frontend/electron-builder.yml`
  - 排除 `node_modules/@lobehub/icons/**` 未使用源码包，避免第三方 provider/icon catalog 中的 `HermesAgent` 文案进入 app.asar。
  - Vite bundle 仍保留实际使用的 provider icons；Electron runtime 只需要 `node-pty` 等运行时依赖。

### Release-like 安全护栏固化

本轮补齐了发布渠道命名与源码级 guard 的不一致：

- `apps.core.build_metadata.RELEASE_LIKE_CHANNELS` 现在把 `stable` 与 `release` / `alpha` 一样视为 release-like channel。
- `scripts/verify_release_artifacts.py` 不再只扫描旧产品身份，也会在临时 `release`、`alpha`、`stable` build metadata 下验证：
  - `OHA_YACHIYO_DEV=1` 不能开启 development features。
  - Bridge debug routes 必须关闭。
  - `CredentialStore` 的 development file fallback 必须关闭。
  - `DevFileCredentialStore` 不能被 release-like metadata 实例化。
- macOS release workflow 的 verifier 步骤已改为 `Verify release-facing product identity and security guards`。
- verifier 已按 workflow 同款 `python scripts/verify_release_artifacts.py` 入口复验；脚本会主动把 repo root 加入 `sys.path`，保证依赖安装前也能导入源码 guard。
- 新增/扩展回归测试覆盖 build metadata、Bridge debug route、CredentialStore factory 和 release verifier 自身的 stable-channel 负例。

### Packaged startup 与版本一致性

本轮真实打包 smoke 暴露并修复了两个发布面问题：

- PyInstaller backend 启动时，FastAPI 会把 `Request | None` 注解误判为 response field，导致 packaged backend 在 route 注册阶段崩溃。
  - 已修复 `create_agent_run()`、`create_workflow_run()`、`send_chat_message()` 的 `http_request` 注解。
  - 保留直接调用测试需要的默认 `None`，但避免 `Request | None` union 注解。
  - 新增回归测试锁定这些 endpoint 不再使用 optional union request annotation。
- `/status` 之前没有显式传入应用版本，导致 packaged backend 返回协议 schema 的旧默认值 `0.1.0`。
  - `apps/bridge/routes/status.py` 现在显式返回 `get_app_version()`。
  - `packages/protocol/schemas.py` 默认版本同步到当前产品版本 `0.4.0`。
  - `scripts/app_version.py` 现在同步并检查 protocol schema 默认版本、`main_api.py` 的所有 status/version fallback。
  - 相关 protocol、shell API、AstrBot status 输出测试已更新。

真实 smoke 结果：

- Standalone `dist/backend/oha-yachiyo-backend` 可启动，`/status.version` 返回 `0.4.0`。
- Packaged `dist/electron/mac-arm64/Oha-Yachiyo.app` 可启动，内置 backend 监听 `127.0.0.1:18420`，`/status.version` 返回 `0.4.0`。
- 本地 `.venv` 中旧 editable 包 `hermes-yachiyo==0.1.0` 已移除，避免后续 PyInstaller 日志继续出现旧 package path。

### Frontend feature-preservation guard

本轮新增 `tests/test_frontend_feature_preservation.py`，在现有 pytest 网内锁定设计书明确要求保留的成熟 UI 入口：

- 顶层路由与导航：
  - Chat、Agent Studio、Settings、Model Profiles、Diagnostics、Tool Center、Activity、App Update、Proactive TTS、Bubble、Live2D。
  - Agent Studio 的 `agents / skills / skill-groups / workflows / runs` 深链接。
- Chat UI：
  - ChatSession 消息读取/发送、多会话、图片附件、runnable 选择。
  - 图片粘贴路径、图片尺寸校验、附件 file input、composer 审批卡和批准/拒绝按钮。
  - 群聊创建/编辑、群派活 metadata、委派 Run summary。
  - Run approval approve/reject 与 Run Detail/Workflow Studio 跳转入口。
- Agent Studio：
  - Agent、Skill、Workflow、Run history、Run Detail、Run artifact、rerun/cancel。
  - Approval UI、Workflow child approval bridge、Workflow approval/artifact 节点。
  - `client_run_id` 仍由前端传入，避免重复提交创建重复 Run。
- 桌面存在感功能：
  - Live2D 资源选择/导入、Live2D runtime preload。
  - 本地截图诊断 `/screen/current`。
  - 主动关怀 TTS、手动 TTS 测试、音色包导入、GPT-SoVITS service install/adopt/uninstall。

这个测试不是浏览器 E2E 的替代，但能防止后续删除旧执行内核时误删成熟产品入口。

### Browser UI smoke

本轮新增一次真实浏览器级 smoke 验证：

- 启动 source backend：
  - `python -m apps.desktop_backend.app`
  - Bridge: `http://127.0.0.1:8420`
  - `/status` 返回 `service=oha-yachiyo`、`version=0.4.0+488987a0`、`native_agent_ready=false`
- 启动前端 preview：
  - `npm --prefix apps/frontend run preview -- --host 127.0.0.1 --port 4173 --strictPort`
- 用 in-app Browser 逐页打开并检查 route-specific DOM、关键文本和 console error：
  - `#/` 主控台。
  - `#/chat` Chat UI：会话列表、群组 tab、composer、textarea、发送按钮存在。
  - `#/agents` Agent Studio。
  - `#/agents/workflows` Workflow Studio。
  - `#/agents/runs` Run history / Run Detail shell。
  - `#/diagnostics` Diagnostics。
  - `#/settings` Settings。
  - `#/proactive-tts` Proactive TTS。
  - `#/live2d` Live2D mode。
  - `#/tools` Tool Center。
  - `#/provider` Model Profiles。
  - `#/resources` Resources。
  - `#/workspace` Workspace。
  - `#/activity-all` ActivityStore feed。
  - `#/activity-detail/a10f16dcbbc3` Activity detail。
  - `#/app-update` App update。

结果：

- 所有页面 `#root` 均非空。
- 所有页面的 route-specific DOM 判据通过。
- Chat、Activity All 初次 smoke 的失败是测试判据使用了不可见 aria/placeholder 或错误 selector；用真实 DOM 判据重跑后通过。
- Browser console error 为空。
- Bridge 与 preview 均监听 `127.0.0.1`。

### Isolated button-level UI smoke

本轮追加一次更接近真实操作的浏览器级 smoke，后端使用临时数据目录，避免污染本机正式数据：

```text
HOME=/tmp/oha-yachiyo-smoke.*/home
OHA_YACHIYO_HOME=/tmp/oha-yachiyo-smoke.*/data
OHA_YACHIYO_BRIDGE_URL=http://127.0.0.1:8420
.venv/bin/python -m apps.desktop_backend.app
npm --prefix apps/frontend run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

验证结果：

- Chat：
  - 打开 `#/chat`。
  - 在 `textarea[placeholder="输入消息..."]` 填入测试消息并点击 `发送消息`。
  - 消息进入 Chat UI。
  - 未配置默认模型时显示 native readiness / `model_profile_required` 相关状态。
  - 未出现 Hermes 安装/回退错误。
  - Browser console error 为空。
- Agent Studio：
  - 从侧栏点击 `Agent Studio`。
  - 点击 `Workflow Studio` tab 后进入 `#/agents/workflows`，Workflow Run 控件存在。
  - 点击 `Runs` tab 后进入 `#/agents/runs`，Run Agent / Workflow、Run Detail、approval 文案存在。
  - Browser console error 为空。
- Live2D：
  - 从侧栏点击 `Live2D 模式`。
  - `资源设置` 按钮可点击，并进入 `#/settings/live2d`。
  - 页面无 React crash，Browser console error 为空。
- 主动关怀 / 手动 TTS：
  - 从侧栏点击 `主动关怀`。
  - 主动关怀、TTS Provider、立即测试、保存语音设置等控件存在。
  - 点击 `保存语音设置` 可完成隔离配置写入，无 console error。
  - 保存后回到主控台是 `ProactiveTtsSettingsView.saveSettings()` 中已有的显式行为，本轮未改变成熟业务语义。

### Mature UI flow contract

本轮新增 `tests/test_ui_mature_flow_contract.py`，作为无浏览器 runner 环境下可重复运行的 UI flow contract：

- Chat UI → Bridge：
  - `/ui/chat/messages` 保留文本发送、图片 attachment、runnable 选择和 `client_message_id`。
  - `Idempotency-Key` header 仍映射到 ChatAPI 的 `client_message_id`。
  - `/ui/chat/attachments/{attachment_id}` 保留图片/音频附件 inline 读取入口。
  - `/ui/chat/session/cancel` 保留停止生成语义，返回 `cancelled_tasks`、`processing_count`、`is_processing` 和 messages。
  - `/ui/chat/groups` 和 `/ui/chat/groups/{session_id}` 保留群聊创建/编辑入口、头像 URL/data URL 和 participant ids。
  - `/ui/chat/delegated-run-summary` 保留自动委派 Run 的主模型总结入口。
- Activity UI → Bridge：
  - `/ui/activity` 保留用户可见活动流查询入口和 query/status/tool/phase/session/task/limit 过滤参数。
  - `/ui/activity/{event_id}` 保留活动详情和 trace 读取入口。
  - `DELETE /ui/activity/{event_id}` 和 `DELETE /ui/activity` 保留单条/批量删除入口。
- Run Detail / approval UI → Bridge：
  - `/ui/agent-runs` 与 `/ui/workflow-runs` 保留 Agent/Workflow Run 创建入口，并继续支持 `Idempotency-Key` 到 `client_run_id` 的映射。
  - `/ui/runs`、`/ui/runs/{run_id}`、`/ui/workflow-runs/{run_id}` 和 `/ui/run-groups/{run_group_id}` 保留 Run history、Run Detail 和 Workflow group detail 读取入口。
  - `/ui/runs/{run_id}/artifacts/{artifact_path}` 保留 Run/Workflow artifact 读取入口。
  - `/ui/runs/{run_id}/rerun` 保留 Run Detail rerun 入口。
  - `/ui/runs/{run_id}/approval/approve` 仍调用 runtime approval approve。
  - `/ui/runs/{run_id}/approval/reject` 仍传递用户拒绝原因。
  - `/ui/runs/{run_id}/cancel` 仍调用 runtime cancel。
- 桌面存在感功能 → Bridge：
  - `/screen/current` 保留本地截图入口。
  - `/ui/proactive/screen-permission/check` 保留截图权限检查与打开系统设置语义。
  - `/ui/tts/test`、`/ui/tts/status`、`/ui/tts/voice-resource` 和 `/ui/tts/voice-resource/import` 保留手动 TTS、状态查询和音色包导入入口。
  - `/ui/proactive/test` 保留主动关怀手动触发入口。
  - `/ui/live2d/model-path/prepare` 和 `/ui/live2d/archive/import` 保留 Live2D 资源选择/导入入口。

这不是完整浏览器 E2E 的替代，但把 Chat 多轮入口、图片发送/读取入口、群聊入口、自动委派总结入口、Activity feed/detail/delete、Agent/Workflow Run 创建、Run history/detail、artifact、rerun、取消入口、审批入口、Run cancel、本地截图、主动关怀、手动 TTS、TTS 资源和 Live2D 资源入口的后端合同固定为同步 pytest，可在当前缺少 `pytest_asyncio` 的 shell 中直接运行。

### Browser Chat readiness E2E

本轮新增一次更窄但更真实的 Chat 浏览器级验证，覆盖 source frontend preview 到 source Bridge 的真实 UI 入口：

测试装置：

```text
HOME=/tmp/oha-yachiyo-browser-e2e-notoken.*/home
OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-e2e-notoken.*/data
OHA_YACHIYO_CONFIG_HOME=/tmp/oha-yachiyo-browser-e2e-notoken.*/config
Bridge: http://127.0.0.1:8420
Frontend preview: http://127.0.0.1:4173/?bridge=http%3A%2F%2F127.0.0.1%3A8420#/chat
```

说明：

- in-app Browser 当前不能在页面加载前注入 Electron preload token，因此该 smoke 使用 localhost-only、无 token 的测试 Bridge。
- 产品安全路径不因此放宽：Electron token 注入、前端 mutating request token header、desktop backend 直接启动生成临时 token 的合同已有 pytest 和 backend smoke 覆盖。

验证结果：

- `#/chat` 可在真实浏览器中启动，`#root` 非空。
- 会话列表、Agent/群组 tab、textarea `输入消息...`、`发送消息`、`停止生成`、图片附件入口均存在。
- 未配置默认模型时，UI 显示用户可见 readiness：`请先配置并选择默认对话模型。`
- 图片附件入口与停止生成按钮保持可见但禁用，符合 Native 未就绪状态。
- 页面没有 Hermes 安装、Hermes fallback 或旧执行内核文案。
- Browser console error 为空。
- 直接调用 `POST /ui/chat/messages` 返回结构化 readiness：

```json
{
  "ok": false,
  "code": "native_agent_not_ready",
  "reason": "model_profile_required",
  "error": "请先配置并选择默认对话模型。"
}
```

- `GET /ui/chat/executor` 返回 native 状态：

```json
{
  "executor": "NativeAgentUnavailableExecutor",
  "available": false,
  "image_input": {
    "mode": "native",
    "route": "blocked"
  }
}
```

这一步把“无模型时 Chat UI 不崩溃、入口保留、错误为 native readiness、无 Hermes 回退”的路径提升到了真实浏览器层；仍不是配置真实模型后的多轮/图片/取消/审批完整 E2E。

### Browser Chat fake-model E2E

本轮继续补齐“有可用模型时主聊天真实执行”的浏览器级验证。测试不使用真实外网模型，而是在隔离 backend 进程内启动本地 OpenAI-compatible fake server，并用 `MemoryCredentialStore` 注入默认 Chat ModelProfile，避免触发 macOS Keychain 和真实 API Key。

测试装置：

```text
HOME=/tmp/oha-yachiyo-browser-model-e2e.*/home
OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-model-e2e.*/data
OHA_YACHIYO_CONFIG_HOME=/tmp/oha-yachiyo-browser-model-e2e.*/config
OHA_YACHIYO_MODEL_TIMEOUT_SECONDS=5
Fake model: http://127.0.0.1:18765/v1/chat/completions
Bridge: http://127.0.0.1:8420
Frontend preview: http://127.0.0.1:4173/?bridge=http%3A%2F%2F127.0.0.1%3A8420#/chat
```

Backend readiness：

- Runtime 启动时选择 `NativeAgentExecutor`。
- `/status` 返回 `native_agent_ready=true`。
- `/ui/chat/executor` 返回：

```json
{
  "executor": "NativeAgentExecutor",
  "available": true,
  "image_input": {
    "can_attach_images": true,
    "mode": "native",
    "route": "native_chat",
    "provider": "custom",
    "model": "browser-fake-model"
  }
}
```

浏览器验证结果：

- `#/chat` 真实页面显示 `就绪 · Native Agent`。
- 图片附件入口从 disabled 变为可用。
- 用户在 textarea 输入 `browser ui fake model message 2026-06-10 07:41` 并点击 `发送消息`。
- UI 投影出用户消息和 assistant 回复：

```text
Browser E2E fake model reply: browser ui fake model message 2026-06-10 07:41
```

- Browser console error 为空。
- 页面没有 Hermes 文案、Hermes fallback 文案或 `native_agent_not_ready`。

API / Run 侧证据：

- `/ui/chat/messages` 中该浏览器消息状态为 `completed`，assistant 消息状态为 `completed`。
- `/ui/runs` 中对应 Run 为：

```text
run_id=main_chat_run_95f3fbe93d34
kind=main_chat_run
runnable_id=builtin:yachiyo-main
status=completed
result=Browser E2E fake model reply: browser ui fake model message 2026-06-10 07:41
```

- `/runs/main_chat_run_95f3fbe93d34/events?after_sequence=0&limit=200` 返回 sequence 1-5：

```text
run.started
task.linked
model.request.started
model.output.completed
run.completed
```

- `model.output.completed` 是单条 completed event，没有 token/delta 级事件。
- 隔离 runtime 数据目录通过 `scripts/verify_secret_redaction.py`，fake API key 未进入落盘 DB。

这一步把主聊天从“readiness 浏览器验证”推进到“可用模型下真实 UI → Chat API → TaskRunner → NativeAgentExecutor → NativeRunEngine → ModelProfile → RunEvent → ChatSession 投影”的端到端验证。剩余浏览器级缺口主要是图片附件、取消、审批、群聊/委派和 Workflow/Run Detail 的完整交互流。

### Source Bridge Chat image and approval E2E

本轮继续补齐主聊天图片与审批的 live source Bridge 验证。测试仍使用本地 OpenAI-compatible fake model 和 `MemoryCredentialStore`，但入口改为真实 `/ui/chat/messages`、`/ui/runs/{run_id}/approval/approve`、`/runs/{run_id}/events` 路由，避免只停留在单元/route stub。

测试装置：

```text
Fake model: http://127.0.0.1:18680/v1
Bridge: http://127.0.0.1:18431
Workspace: /private/tmp/oha-yachiyo-browser-e2e2-data/projects
Default Chat ModelProfile: profile_c77a872865f9
Executor: NativeAgentExecutor
```

验证结果：

- 图片附件路径：
  - `POST /ui/chat/messages` 提交 `data:image/png;base64,...` 图片 attachment。
  - ChatSession 用户消息只暴露 `/ui/chat/attachments/{attachment_id}` 公共 URL。
  - TaskRunner 走 `NativeAgentExecutor`，NativeRunEngine 把图片作为 OpenAI-compatible `image_url` content part 传给 fake model。
  - assistant 投影为 `Browser E2E image reply saw image attachment`。
  - `/runs/main_chat_run_f7d672099d46/events?after_sequence=0&limit=200` 返回：

```text
run.started
task.linked
model.request.started
model.output.completed
run.completed
```

- 审批路径：
  - `POST /ui/chat/messages` 提交 `approval-e2e please patch workspace c`。
  - 对应 Run 进入 `approval_required`，`pending_approval.tool=workspace.write_patch`。
  - `POST /ui/runs/main_chat_run_aa423a508b06/approval/approve` 后执行工具并恢复模型。
  - workspace 文件 `browser-e2e-approval.txt` 从 `before\n` 变为 `after-browser-approval\n`。
  - assistant 最终投影为 `Browser E2E approval final after tool result`。
  - RunEvent replay 返回：

```text
run.started
task.linked
model.request.started
agent.tool.call
agent.tool.approval_required
agent.tool.approval_approved
agent.tool.call
model.output.completed
run.completed
```

本轮同时发现 `/ui/runs` 列表没有顶层暴露 `task_id/session_id`，只能从 timeline 的 `task.linked` 反推 Task↔Run。已将 `task_run_links` 投影到 Run API 顶层：`task_id`、`session_id`、`task_run_link_created_at`，并用 `tests/test_agent_runtime.py::test_main_chat_run_links_task_and_records_replayable_events` 锁定 `get_run()` 与 `list_runs()` 都能直接读取映射。后续又按设计书建议扩展 TaskRunLink 投影字段：`run_status`、`last_event_sequence`、`updated_at`，并在 Run 状态更新和 RunEvent append 时同步，避免诊断入口继续从 timeline 或 replay 列表反推最新状态。

### Chat UI interaction guard and Browser blocker

本轮继续尝试把图片/审批从 source Bridge E2E 推进到真实浏览器按钮级 E2E。启动了隔离 fake model、隔离 Bridge 和前端 dev server：

```text
Fake model: http://127.0.0.1:18682/v1
Bridge: http://127.0.0.1:18433
Frontend dev server target: http://127.0.0.1:5176/#/chat
Executor: NativeAgentExecutor
```

结果：

- Bridge 正常启动，`/status.native_agent_ready=true`。
- `/ui/chat/executor` 返回 `NativeAgentExecutor`，图片输入为 `native_chat`。
- in-app Browser 打开 `http://127.0.0.1:5176/#/chat` 与裸 `http://127.0.0.1:5176/` 均被 Browser client 拦截，错误为 `net::ERR_BLOCKED_BY_CLIENT`。
- `agent-browser` CLI 不在当前 PATH，无法作为等价浏览器 runner fallback。

因此本轮没有声称完成浏览器按钮级图片上传/审批卡 E2E。作为临时防回归措施，扩展了 `tests/test_frontend_feature_preservation.py::test_chat_ui_preserves_sessions_groups_attachments_and_approval_paths`，锁定：

- textarea 的 `onPaste` 图片路径仍调用 `clipboardImageFiles(event.clipboardData)` 与 `addImageFiles(files)`。
- 图片读取仍经过 `readPendingAttachment`、`loadImageDimensions(dataUrl)` 和 16x16 最小尺寸校验。
- 图片附件仍通过 `attachments: outgoingAttachments` 进入 `/ui/chat/messages`。
- 附件按钮和隐藏 file input 仍保留 `aria-label="添加附件，当前仅支持图片"`、`type="file"`、`accept="image/*"`。
- composer 审批卡仍保留 `.composer-approval-notice`、`.composer-approval-actions`、`.approve`、`.reject` 和 `onApprove` / `onReject`。

这一步不是完整浏览器 E2E 的替代，但把真实浏览器 runner 恢复前最容易被重构误删的 Chat 图片/审批 UI 交互入口固定到可重复 pytest。

### Browser DOM selector smoke

本轮重新启动前端 dev server 时先发现一次错误启动方式：`npm --prefix apps/frontend exec vite` 会在仓库根目录服务，`curl http://127.0.0.1:5174/` 返回 404；改为在 `apps/frontend` 目录执行 `npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort` 后，首页返回 200 且 in-app Browser 可打开 `http://127.0.0.1:5174/`。

已用 in-app Browser 真实 DOM 检查：

```text
http://127.0.0.1:5174/#/chat
http://127.0.0.1:5174/#/agents/runs
http://127.0.0.1:5174/#/agents/workflows
```

结果：

- Chat 路由真实渲染，`chat-header-image-attach-button`、`chat-composer-image-attach-button`、`chat-image-file-input` 存在；无 Bridge 时图片按钮按预期 disabled，file input 为隐藏 input。
- Runs 路由真实渲染 Agent Studio / Runs 空态；因为本轮没有 source Bridge / Run seed，`agent-run-detail`、`agent-run-detail-execution`、`agent-run-detail-load-more-events` 未挂载，不能把本轮计作 Run Detail 完整 E2E。
- Workflow Studio 路由真实渲染，`workflow-studio`、`workflow-editor`、`workflow-add-agent-node`、`workflow-save-and-run` 存在；无 Bridge / Agent 数据时 `workflow-save-and-run` 按预期 disabled。
- Browser console error 为空。

这一步只补了真实浏览器 DOM 层的入口/选择器复验；Chat 图片上传动作、审批卡 approve/reject、取消、Run Detail 有数据态、Workflow 保存运行和群聊/委派完整交互仍需 source Bridge 或桌面级 runner 继续覆盖。

### Browser Chat image upload selector hardening

本轮再次尝试补 Chat 图片 file upload 的真实 Browser E2E，并先把可验证的 UI 稳定点补齐：

```text
Frontend: http://127.0.0.1:5174/#/chat
Source Bridge: http://127.0.0.1:8420
OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-chat-upload-20260611-01
Fake provider: http://127.0.0.1:18777/v1
Temp image: /tmp/oha-yachiyo-browser-chat-upload.png
Default Chat profile: profile_4839d854f6dd
```

已确认：

- `/ui/chat/executor` 为 `NativeAgentExecutor` / `available=true`。
- `image_input.can_attach_images=true`，route 为 `native_chat`，Chat 图片按钮在 source Browser 中可用。
- in-app Browser DOM 中 `chat-composer-image-attach-button` 为 enabled，`chat-image-file-input` 存在，页面 status 为 `就绪`。
- Chat composer 现在给附件预览和移除按钮暴露稳定选择器：`chat-composer-attachment-preview` / `chat-composer-attachment-remove`，并由 `tests/test_frontend_feature_preservation.py::test_chat_ui_exposes_stable_e2e_selectors_for_image_cancel_approval_flow` 锁定。
- Chat paste path 和 hidden file input `onChange` 现在都会在进入 `addImageFiles()` 前复用同一个 `imageAttachDisabled` 状态，`addImageFiles()` 自身也拒绝发送中或图片能力不可用状态，并由 source guard 锁定，避免未来 Browser file upload runner 直接驱动 hidden input 时绕过 UI 禁用语义。

仍未计作完成的部分：

- in-app Browser Playwright locator 仍没有 `setInputFiles()`，不能直接给 hidden file input 设置文件。
- 点击附件按钮后，Computer Use 只能看到另一个已打开的 packaged `.app` 窗口，不能操作 source Browser 的 file picker。
- `tab.clipboard.write()`、macOS system clipboard + Playwright `Meta+V`、以及 lower-level CUA keypress 都被同一个错误阻断：`Browser Use virtual clipboard is not installed`。
- `agent-browser` CLI 当前不在 PATH，无法作为等价 runner fallback。

因此本轮不声称完成 Chat 图片 file upload 浏览器 E2E；它只把“上传后预览/移除”的稳定 selector 补齐，并记录当前 Browser runner 的真实阻断条件。图片数据进入 NativeRunEngine 的产品链路仍由 live source Bridge E2E、HTTP route roundtrip、TaskRunner image roundtrip 和 RunEvent replay 回归覆盖。

### Browser Run Detail approval E2E

本轮用 in-app Browser + source Vite + source Bridge + 本地 OpenAI-compatible SSE fake provider 补 Run Detail 数据态审批 E2E：

```text
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18766/v1  # profile test returns JSON OK, agent run stream returns SSE tool_call delta
Browser route: http://127.0.0.1:5174/#/agents/agent_run_5107d9e0032f
```

验证内容：

- Chat route 在有 source Bridge 后真实加载，`chat-header-image-attach-button`、`chat-composer-image-attach-button`、`chat-image-file-input` 和 `chat-header-stop-button` 存在；未配置默认 Chat Profile 时图片按钮和停止按钮按预期 disabled，hidden file input 保留。
- 通过 Chat UI textarea 输入并点击发送按钮，按钮层真实调用 `/ui/chat/messages`，页面返回 readiness 文案 `请先配置并选择默认对话模型。`，Browser console error 为空。
- 通过 Bridge 创建可用 ModelProfile、Agent 和 `approval_required` Agent Run；fake provider 使用 streaming `tool_calls` delta 返回 `terminal_run` 请求。
- Browser 打开 Run Detail 数据态后，`agent-run-detail`、`agent-run-detail-approval`、`agent-run-detail-approval-actions`、`agent-run-detail-approval-approve`、`agent-run-detail-approval-reject`、`agent-run-approval-request`、`agent-run-detail-execution`、`agent-run-detail-execution-events` 均存在，RunEvent replay 初始为 3 条。
- Browser 点击 `agent-run-detail-approval-approve` 后，Run Detail 刷新为 completed，approval UI 消失，`agent-run-detail-result` 显示 `Browser Run Detail approval complete`，Execution replay 增至 6 条，Browser console error 为空。
- Bridge API 复核同一 Run：

```text
status: completed
result: Browser Run Detail approval complete
pending_approval: {}
event_types:
  agent.run.started
  agent.tool.call
  agent.tool.approval_required
  agent.tool.approval_approved
  agent.tool.call
  agent.run.completed
```

这一步把 Agent Studio / Run Detail / approval UI 从“source selector guard + HTTP route roundtrip”推进到一次真实浏览器点击批准的 source Bridge E2E。本轮下方已继续补 Chat 取消按钮级 smoke；剩余浏览器级缺口主要是 Chat 图片上传按钮真实 file upload、Workflow Studio 保存运行、Workflow 子审批、群聊/委派/会话总结和桌面 `.app` 内完整跨页面流程。

### Browser Run Detail rerun/delete/artifact E2E

本轮继续用 in-app Browser + source Vite + source Bridge + 本地 OpenAI-compatible SSE fake provider 补 Run Detail 的 artifact preview、rerun 和 Run History delete 跨 UI 验证：

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420
OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-run-detail-rerun-20260611-01
fake provider: http://127.0.0.1:18778/v1
Browser original route: http://127.0.0.1:5174/#/agents/workflow_run_4914d0fa6240
```

验证内容：

- 在隔离 home 中创建默认 Chat ModelProfile `profile_6ed9128fec58`，profile test 成功，`/ui/native-agent/recheck` 后 Bridge 内 executor ready。
- 通过 Bridge API 创建 `Browser Rerun Agent` 与 Workflow `Browser Run Detail Rerun Smoke`，节点为 Start → Agent → Artifact；启动原始 Workflow Run `workflow_run_4914d0fa6240`，Run completed，结果为 `Run Detail browser rerun result 2`，artifact 为 `summary-artifact.md`。
- Browser 打开原始 Run Detail 后真实展示：
  - `agent-run-detail` / `agent-run-detail-rerun`
  - `Run Detail browser rerun result 2`
  - `summary-artifact.md`
  - `agent-run-detail-execution-event` 共 5 条
  - `agent-run-history-manage`
- Browser 点击 `agent-run-detail-artifact` 后，`agent-run-detail-artifact-preview` 展示 `summary-artifact.md` 和原始结果内容，确认 artifact preview 不是只依赖静态 timeline。
- Browser 点击 `agent-run-detail-rerun` 后自动切到新 Run `workflow_run_50c71117679a`；新 Run Detail 显示 `Run Detail browser rerun result 3`、artifact 1 个，并且 Execution replay 显示 `run.rerun.started` / `从原 Run 重跑`。
- 为了把 delete 分支也做成稳定 Browser smoke，本轮给 Run History 管理控件补了稳定 selector：`agent-run-history-manage`、`agent-run-history-bulk-actions`、`agent-run-history-select-all`、`agent-run-history-clear-selection`、`agent-run-history-delete-selected`、`agent-run-history-finish-management`、`agent-run-history-select-run`，并由 `tests/test_frontend_feature_preservation.py::test_agent_studio_exposes_stable_e2e_selectors_for_run_detail_and_approval_flow` 锁定。
- Browser 进入 Run History 管理模式，选择新 Run `workflow_run_50c71117679a`，点击 `agent-run-history-delete-selected`，确认 `删除 1 条记录` 后：
  - URL 回到 `http://127.0.0.1:5174/#/agents/runs`
  - Run Detail 清空为“从左侧选择一个 Run...”
  - run list 不再包含 `workflow_run_50c71117679a`
  - 原始 Run `workflow_run_4914d0fa6240` 仍保留
  - Browser console error 为空

Bridge API 复核：

```text
original:
  GET /ui/workflow-runs/workflow_run_4914d0fa6240 -> 200
  result: Run Detail browser rerun result 2
deleted rerun:
  GET /ui/workflow-runs/workflow_run_50c71117679a -> 404
  GET /runs/workflow_run_50c71117679a/events?after_sequence=0&limit=200 -> 404
remaining /ui/runs:
  workflow_run_4914d0fa6240
provider calls:
  #1 profile test, non-stream
  #2 original Workflow run, stream
  #3 rerun Workflow run, stream
```

这一步把 Run Detail 从“approval 点击 / replay handoff”推进到 artifact preview、rerun route、rerun replay fact、新 Run cache、Run History 管理模式、delete confirmation、detail cache 清空和 backend 404 的真实 Browser 闭环。

### Browser Chat cancel button E2E

本轮用 in-app Browser + source Vite + source Bridge + 慢速本地 OpenAI-compatible fake provider 补 Chat 停止生成按钮到 Native Run 取消的浏览器 smoke：

```text
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18768/v1  # profile test returns JSON OK, chat stream sleeps before SSE output
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 先通过 Bridge 创建并设为默认 Chat ModelProfile，Chat route 真实渲染，`chat-header-stop-button` 和 composer stop button 初始为不可用或未挂载。
- Browser 的 `fill()` / `type()` 在当前环境被虚拟剪贴板缺失阻断，错误为 `Browser Use virtual clipboard is not installed`；因此文本输入改用 DOM/CUA keypress。图片 paste / file upload 同样因虚拟剪贴板缺失与 Codex in-app file picker 无法由 Computer Use 驱动而未计作完成。
- 通过 Chat UI 发送 `Ca` 后，composer stop button 真实出现；等待 Native `main_chat_run` 创建并进入模型请求后点击停止。
- 慢模型返回后，Chat 页面显示用户消息和 assistant `任务已取消`，composer stop button 消失，header stop button 回到 disabled；fake provider 的 late output 字符串 `Browser cancel late output should not appear` 没有进入页面，Browser console error 为空。
- Bridge API 复核同一 Run：

```text
run_id: main_chat_run_0e4d6a868a07
task_id: 12f10c773d40
session_id: 6ea95cca
status: cancelled
result: Run cancelled
task_run_link_run_status: cancelled
task_run_link_last_event_sequence: 4
event_types:
  run.started
  task.linked
  agent.runtime.compiled
  model.request.started
  run.cancelled
```

SQLite `agent-runtime.db` 中 `task_run_links`、`runs` 和 `run_events` 与 `/ui/runs` projection 一致，确认这次不是只取消 ChatSession 投影，而是按钮路径通过 `/ui/chat/session/cancel` 让 Native `main_chat_run` 落到 `cancelled`，且 late model output 没有覆盖终态。

### Browser Chat approval-card E2E

本轮继续用 in-app Browser + source Vite + source Bridge + 本地 OpenAI-compatible SSE fake provider 补 Chat 页面审批卡按钮级 E2E：

```text
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18769/v1  # profile test returns JSON OK, first chat stream requests terminal_run, approval resume returns final content
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 预置默认 Chat ModelProfile 为 available，Chat route 真实渲染 `模型配置 ok` 和可发送状态。
- 当前 Browser 的 Playwright `fill()` / DOM bulk `type()` 仍被虚拟剪贴板缺失阻断，因此继续使用 DOM/CUA keypress 输入 `ApprovalTest`；Browser Playwright subset 也没有暴露 `setInputFiles()`，所以 Chat 图片 file upload 仍未计作完成。
- Browser 点击 Chat 发送按钮后，fake provider streaming 返回 `terminal_run` tool call；Chat 页面真实出现 message approval card 与 composer approval notice，均带 approve/reject action。
- Browser 点击 Chat message approval approve 后，Run 通过 `/ui/runs/{run_id}/approval/approve` 恢复，执行已批准的 `terminal.run`，随后模型返回 `Browser Chat approval card complete`。
- Bridge API 复核同一 Run：

```text
run_id: main_chat_run_93ce2aa51220
task_id: 2b85c22e87c0
session_id: 1e6829bc
status: completed
result: Browser Chat approval card complete
task_run_link_run_status: completed
task_run_link_last_event_sequence: 9
event_types:
  run.started
  task.linked
  model.request.started
  agent.tool.call
  agent.tool.approval_required
  agent.tool.approval_approved
  agent.tool.call
  model.output.completed
  run.completed
```

这次浏览器 smoke 同时暴露一个前端 stale-action bug：Run 和 Chat message 已 completed、`approval_count=0`、message metadata 的 `pending_approval={}`，但历史 `activity_events` 里保留了已完成审批活动，且其旧 metadata 仍含 `run_status=approval_required`，导致 composer approval notice 继续显示 approve/reject。已修复 `hasActionableActivityApproval()`：当 activity event status 为 `completed` / `success` / `failed` / `error` / `cancelled` 时直接视为不可操作，只保留历史活动展示，不再派生待审批操作。修复后重新加载同一 Chat 页面：

```text
messageApprovalCards: 0
messageApprovalActions: 0
composerApprovalNotices: 0
composerApprovalApprove: 0
completedVisible: true
activityStillVisible: true
consoleErrors: []
```

### Browser Chat composer approval reject E2E

本轮在同一类 source Browser 环境继续补 Chat composer approval notice 的 reject 分支：

```text
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18770/v1  # profile test returns JSON OK, first chat stream requests terminal_run
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 预置默认 Chat ModelProfile 为 available，Browser 打开 Chat 后真实显示 `模型配置 ok`。
- 继续用 DOM/CUA keypress 输入 `RejectTest` 并点击 Chat 发送按钮；fake provider streaming 返回 `terminal_run` tool call。
- Chat 页面同时出现 message approval card 与 composer approval notice；本轮明确点击 composer 层 `chat-composer-approval-reject`，而不是 message card 的 reject。
- 点击后 Chat 页面显示 `工具审批已拒绝：Rejected from chat`，message approval card、message approval actions、composer approval notice 和 composer reject button 全部消失，fake provider 的 post-reject completion sentinel `SHOULD NOT COMPLETE AFTER REJECT` 没有出现，Browser console error 为空。
- Bridge API 复核同一 Run：

```text
run_id: main_chat_run_8cb84535cbc8
task_id: 263619661e84
session_id: 51603d6b
status: cancelled
result: 工具审批已拒绝：Rejected from chat
task_run_link_run_status: cancelled
task_run_link_last_event_sequence: 7
event_types:
  run.started
  task.linked
  model.request.started
  agent.tool.call
  agent.tool.approval_required
  agent.tool.approval_rejected
  agent.run.cancelled
```

这一步覆盖了 Chat composer 审批条的拒绝分支：产品级 Chat transcript 以 failed 状态展示用户可见拒绝原因，Native Run / TaskRunLink 以 cancelled 记录执行终态，并保留可回放 `agent.tool.approval_rejected` 与 `agent.run.cancelled` facts。

### Browser Chat message approval reject E2E

本轮补齐 Chat message approval card 自身的 reject 分支，继续使用 source Browser + source Bridge + 本地 fake provider：

```text
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18771/v1  # profile test returns JSON OK, first chat stream requests terminal_run
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 预置默认 Chat ModelProfile 为 available，Browser 打开 Chat 后真实显示 `模型配置 ok`。
- 使用 DOM/CUA keypress 输入 `MsgReject` 并点击 Chat 发送按钮；fake provider streaming 返回 `terminal_run` tool call。
- Chat 页面同时出现 message approval card 与 composer approval notice；本轮明确点击 message card 层 `chat-message-approval-reject`。
- 点击后 Chat 页面显示 `工具审批已拒绝：Rejected from chat`，message approval card、message approval actions、message reject button、composer approval notice 和 composer reject button 全部消失，fake provider 的 post-reject completion sentinel `SHOULD NOT COMPLETE AFTER MESSAGE REJECT` 没有出现，Browser console error 为空。
- Bridge API 复核同一 Run：

```text
run_id: main_chat_run_80c684831be0
task_id: 20beb3a1cede
session_id: cacd8567
status: cancelled
result: 工具审批已拒绝：Rejected from chat
task_run_link_run_status: cancelled
task_run_link_last_event_sequence: 7
event_types:
  run.started
  task.linked
  model.request.started
  agent.tool.call
  agent.tool.approval_required
  agent.tool.approval_rejected
  agent.run.cancelled
```

这一步和上一条 composer reject smoke 合起来覆盖 Chat 两处审批 UI 的拒绝入口：message card 与 composer approval notice 都会调用同一 Run approval reject route，清空 Chat approval UI，并让 Native Run 以 cancelled 终态和 replay facts 收敛。

### Browser Chat approval to Run Detail handoff E2E

本轮继续补 Chat 审批卡跨页面 handoff：从真实 Chat 页面触发 `terminal.run` 审批后，点击 message approval card 的 `运行详情`，确认 Agent Studio Run Detail 打开同一个 Native `main_chat_run` 并展示 RunEvent replay。

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18772/v1  # profile test returns JSON OK, first chat stream requests terminal_run
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 在隔离 `OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-run-detail-20260611043019` 中创建默认 Chat ModelProfile，并通过 `/ui/model-profiles/{profile_id}/test` 与 `/ui/native-agent/recheck` 让 Bridge 进程内 TaskRunner 刷新为 `NativeAgentExecutor`。
- Browser 打开 Chat 后显示 `模型配置 ok`，使用真实键盘输入 `please request terminal approval for run detail browser smoke` 并点击 Chat 发送按钮。
- fake provider streaming 返回 `terminal_run` tool call；Chat 页面出现 message approval card 与 composer approval notice，本轮点击 message card 的 `chat-message-approval-open-run-detail`。
- 页面跳转到 `http://127.0.0.1:5174/#/agents/main_chat_run_300ebe0a11b9`，Agent Studio Run Detail 真实展示同一个 `main_chat_run`、同一个 Task/Session、`Approval Required · terminal.run`、`Task link 等待审批` 和 `Execution · 5` replay facts。
- Browser console error 为空。
- Bridge API 复核同一 Run：

```text
run_id: main_chat_run_300ebe0a11b9
task_id: 8eada114f772
session_id: a913eaf6
status: approval_required
pending_tool: terminal.run
task_run_link_run_status: approval_required
task_run_link_last_event_sequence: 5
chat_approval_count: 1
event_types:
  run.started
  task.linked
  model.request.started
  agent.tool.call
  agent.tool.approval_required
```

这一步把此前同步 UI flow contract 中的“Chat approval card 跳转 Run Detail / replay handoff”推进到真实 Browser 点击验证：Chat message approval card、route navigation、Agent Studio Run selection、Task↔Run metadata 和 `/runs/{run_id}/events` replay API 都指向同一个 Native `main_chat_run`。

### Browser Workflow Studio save-and-run E2E

本轮继续补 Workflow Studio 的 source Browser 跨 UI 运行证据：从真实 Workflow Studio 页面新建最小 Workflow，添加一个 Agent 节点，点击 `保存并运行 Workflow`，确认自动打开同一个 Workflow Run 的 Run Detail，并能看到父 Workflow Run、子 Agent Run、RunGroup 和 RunEvent replay。

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18773/v1  # profile test returns JSON OK, Agent run returns final content
Browser route: http://127.0.0.1:5174/#/agents/workflows
```

验证内容：

- 在隔离 `OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-workflow-run-20260611044343` 中创建并测试默认 Chat ModelProfile，Bridge 启动后 `/ui/chat/executor` 已是 `NativeAgentExecutor` / `available=true`。
- Browser 打开 Workflow Studio 后显示 `模型配置 ok`、8 个可添加 Agent、`workflow-studio` / `workflow-editor` / `workflow-agent-palette` / `workflow-save-and-run`。
- Browser 点击 `workflow-new`，把 workflow 名称改为 `Browser Workflow Studio Smoke`，从 palette 点击 `Coding Agent`，填写运行目标 `Run the Browser Workflow Studio smoke and return a short result.`；UI 显示 1 个可运行 step，`workflow-save-and-run` 从 disabled 变为 enabled。
- Browser 点击 `workflow-save-and-run` 后自动跳转 `http://127.0.0.1:5174/#/agents/workflow_run_b3574776694d`；Run Detail 显示 `Browser Workflow Studio Smoke`、`Workflow Run · 已完成`、最终结果 `Browser Workflow Studio run complete`、`Workflow Steps · 2`、子 Agent `Open Run` 入口和 `Execution · 4` replay facts。
- Browser console error 为空。
- Bridge API 复核：

```text
workflow_run:
  run_id: workflow_run_b3574776694d
  kind: workflow_run
  status: completed
  runnable_name: Browser Workflow Studio Smoke
  result: Browser Workflow Studio run complete
  run_group_id: run_group_03f0b2c08863
  event_types:
    workflow.run.started
    workflow.node.start
    workflow.node.agent
    workflow.run.completed
child_run:
  run_id: agent_run_4fdcea46bee3
  kind: agent_run
  status: completed
  runnable_name: Coding Agent
  result: Browser Workflow Studio run complete
  event_types:
    agent.run.started
    agent.run.completed
run_group:
  run_group_id: run_group_03f0b2c08863
  status: completed
  child_run_ids:
    workflow_run_b3574776694d
    agent_run_4fdcea46bee3
```

这一步把此前“Workflow Studio 编辑/节点配置/保存并运行路径已暴露稳定 selector”和 HTTP route roundtrip 推进到一次真实 Browser UI 操作：Workflow Studio 保存定义、创建 Workflow Run、父子 RunGroup 投影、Run Detail 自动打开、Workflow Steps 与 RunEvent replay 都在同一 source Bridge 环境下闭环。

### Browser Workflow child approval Run Detail E2E

本轮继续用 in-app Browser + source Vite + source Bridge + 本地 OpenAI-compatible SSE fake provider 补 Workflow 子 Agent 审批的 Run Detail 跨 Run 验证：

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18776/v1  # profile test returns OK, first Agent stream requests terminal_run, approval resume returns final content
Browser route: http://127.0.0.1:5174/#/agents/workflow_run_0c852178a12a
```

验证内容：

- 在隔离 `OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-workflow-child-approval-20260611-050603` 中创建并测试默认 Chat ModelProfile；Bridge 启动后 `/ui/chat/executor` 为 `NativeAgentExecutor` / `available=true`。
- 通过 source Bridge API 创建 `Browser Workflow Child Approval Smoke`，节点为 Start → `Coding Agent` → Artifact `summary.md`；启动 `workflow_run_0c852178a12a` 后，父 Workflow 和子 `agent_run_ef2028a3a752` 同时进入 `approval_required`，RunGroup `run_group_162b33403050` source 为 `workflow`。
- Browser 打开父 Workflow Run Detail 后真实展示 `agent-run-detail-workflow-child-approval`：`Workflow 正在等待子 Agent 审批`、子 Run `agent_run_ef2028a3a752`、工具 `terminal.run`、命令 `printf workflow-child-browser-approved`、`批准子 Agent` / `拒绝子 Agent` / `取消子 Run` / `打开子 Run`。
- Browser 点击 `agent-run-detail-workflow-child-approve` 后，子 Run 执行已批准的 `terminal.run`，父 Workflow 自动刷新为 completed；父 Run Detail 展示 `Workflow child browser approval complete`、`Workflow Steps · 3`、`summary.md` artifact、Execution replay 中的 `workflow.run.child_resumed` / `workflow.run.resumed` / `workflow.node.artifact` / `workflow.run.completed`。
- Browser 再点击 Workflow Steps 的 `Open Run` 进入 `http://127.0.0.1:5174/#/agents/agent_run_ef2028a3a752`；子 Run Detail 展示 completed、返回父 Workflow 入口、`agent.tool.approval_required` / `agent.tool.approval_approved` / approved `agent.tool.call` / `agent.run.completed` replay，以及最终结果 `Workflow child browser approval complete`。
- Browser console error 为空。

Bridge API / replay 复核：

```text
workflow_run:
  run_id: workflow_run_0c852178a12a
  status: completed
  result: Workflow child browser approval complete
  artifacts: summary.md
child_run:
  run_id: agent_run_ef2028a3a752
  runnable_id: agent_coding
  status: completed
  result: Workflow child browser approval complete
  approved_tool: terminal.run
  stdout: workflow-child-browser-approved
run_group:
  run_group_id: run_group_162b33403050
  source: workflow
  status: completed
  child_run_ids:
    workflow_run_0c852178a12a
    agent_run_ef2028a3a752
parent_run_events:
  workflow.run.started
  workflow.node.start
  workflow.node.agent            # approval_required
  workflow.run.approval_required
  workflow.node.agent            # running after approve
  workflow.run.child_resumed
  workflow.node.agent            # completed
  workflow.run.resumed
  workflow.node.artifact
  workflow.run.completed
child_run_events:
  agent.run.started
  agent.tool.call                # initial terminal.run request
  agent.tool.approval_required
  agent.tool.approval_approved
  agent.tool.call                # approved terminal.run execution
  agent.run.completed
```

这一步把此前 route-level Workflow child approval 回归推进到真实 Browser Run Detail 操作：父 Workflow Run Detail 的子审批桥接、批准后父/子 Run cache 刷新、RunGroup 完成态、Workflow Steps、父子 RunEvent replay、子 Run Detail 跳转和返回父 Workflow 入口都在同一 source Bridge 环境下闭环。

### Browser group chat dispatch and summary E2E

本轮继续补群聊 / 自动派发 / 会话总结的 source Browser 跨 UI 证据：从真实 Chat 页面创建群组，选择 Coding Agent，向主模型发送群聊派发请求，确认主模型 `oha.group_dispatch`、Coding Agent Run、群组总结 Task 和 Chat transcript 都在同一 Native runtime 下收敛。

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18774/v1  # profile test returns JSON OK, main model dispatches, Coding Agent and summary return final content
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 在隔离 `OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-group-dispatch-20260611044908` 中创建并测试默认 Chat ModelProfile；Bridge 启动后 `/ui/chat/executor` 为 `NativeAgentExecutor` / `available=true`。
- Browser 打开 Chat 后显示 `模型配置 ok`；点击 `群组` tab 和 `创建群组`，在真实群组弹窗中填写 `Browser Group Dispatch Smoke`，选中 `Coding Agent`，点击 `创建`。
- Chat 自动切到新群组，header 显示 `Browser Group Dispatch Smoke`、`群组 · 2 成员`。
- Browser 输入并发送 `@主模型 请安排 Coding 做 Browser Native 群聊派发验证`。
- fake provider 的主模型回复包含 `oha.group_dispatch` JSON，但 Chat transcript 不泄露该 directive；页面展示“我把这个任务派给 Coding Agent 了”。
- Coding Agent 的 Native Agent Run 完成后，页面展示 `Coding browser native dispatch result` 和 `运行详情` 入口；随后主模型群组总结 Task 自动完成，页面展示 `群组总结：Coding 已完成 Browser Native 群聊派发。`。
- Browser console error 为空，页面最终不再 processing。

Bridge API / SQLite 复核：

```text
chat:
  is_processing: false
  approval_count: 0
  parent_status: completed
  group_dispatch_count: 1
  group_agent_summary_status: completed
  group_dispatch_run_group_id: run_group_47d4513c3542
agent_message:
  status: completed
  run_id: agent_run_12bc3d368e65
  run_status: completed
  delegated_goal: 做 Browser Native 群聊派发验证
run_group:
  run_group_id: run_group_47d4513c3542
  status: completed
  child_run_ids:
    agent_run_12bc3d368e65
task_run_links:
  63102dd75b2e -> main_chat_run_9ae531519beb -> completed
  a3efe3823394 -> main_chat_run_2228f82af586 -> completed
run_events:
  main_chat_run_9ae531519beb:
    run.started
    task.linked
    model.request.started
    model.output.completed
    run.completed
  agent_run_12bc3d368e65:
    agent.run.started
    agent.run.completed
  main_chat_run_2228f82af586:
    run.started
    task.linked
    model.request.started
    model.output.completed
    run.completed
```

这一步把此前 ChatAPI / TaskRunner / Bridge route 级群聊派发回归推进到真实 Browser UI：群组创建、成员选择、群聊发送、主模型派发、Agent Run、RunGroup、群组总结 Task、Task↔Run link 和 Chat transcript 都在 source Bridge 环境下闭环，并继续证明内部 `oha.group_dispatch` directive 只作为执行合同，不暴露给用户 transcript。

### Browser main chat auto delegation and delegated summary smoke

本轮继续用 in-app Browser + source Vite + source Bridge + 本地 OpenAI-compatible fake provider 补主聊天自动委派浏览器 smoke：

```text
./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort  # cwd=apps/frontend
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
fake provider: http://127.0.0.1:18775/v1  # profile test returns OK, main model emits run_oha_agent, Coding Agent and summary return final content
Browser route: http://127.0.0.1:5174/#/chat
```

验证内容：

- 在隔离 `OHA_YACHIYO_HOME=/tmp/oha-yachiyo-browser-auto-delegation-20260611-045752` 中创建并测试默认 Chat ModelProfile；Bridge 启动后 `/ui/chat/executor` 为 `NativeAgentExecutor` / `available=true`。
- Browser 打开 Chat 后显示 `模型配置 ok`；真实输入并发送 `请自动委派 Coding Agent 做 Browser Native 自动委派验证`。
- fake provider 的主模型第一轮回复包含内部 `<oha_delegation>{"action":"run_oha_agent","agent":"Coding Agent","goal":"做 Browser Native 自动委派验证"}</oha_delegation>`；TaskRunner / NativeAgentExecutor / NativeRunEngine 创建 `agent_run_85291ca52873`，RunGroup source 为 `delegation`。
- `Coding Agent` 的 delegated Agent Run 走同一 NativeRunEngine，完成结果为 `Coding browser auto delegation result`；主模型第二轮收到 `[OHA 委派结果]` 后完成最终 Chat transcript：`最终结论：Browser Native 自动委派链路已闭环。`
- Chat transcript 不泄露 `run_oha_agent` 或 `oha_delegation`，页面最终不再 processing，Browser console error 为空。
- 通过 `/ui/chat/delegated-run-summary` 显式为 `agent_run_85291ca52873` 创建主模型整理 Task；TaskRunner 完成新的 `main_chat_run_8a1563648b60` 后刷新 Browser，同一 Chat transcript 显示 `自动委派总结：Coding 已完成 Browser Native 自动委派。` 和 `运行详情` 入口，且仍不泄露内部 directive。

Bridge API / replay 复核：

```text
chat:
  is_processing: false
  approval_count: 0
  original_task: 5f9995390906 -> main_chat_run_c7a74d910f80 -> completed
  summary_task: 6a09f71726bd -> main_chat_run_8a1563648b60 -> completed
delegation:
  run_group_id: run_group_11c9b3b710fe
  source: delegation
  agent_run: agent_run_85291ca52873
  runnable_id: agent_coding
  run_status: completed
  result: Coding browser auto delegation result
run_events:
  main_chat_run_c7a74d910f80:
    run.started
    task.linked
    model.request.started
    model.output.completed   # internal delegation directive, stored as RunEvent only
    model.request.started
    model.output.completed   # final user-visible reply
    run.completed
  agent_run_85291ca52873:
    agent.run.started
    agent.run.completed
  main_chat_run_8a1563648b60:
    run.started
    task.linked
    model.request.started
    model.output.completed
    run.completed
```

这一步把此前 TaskRunner / ChatAPI / Bridge route 级自动委派和 delegated summary 回归推进到真实 Browser UI 入口：主聊天发送、内部 `run_oha_agent` directive 解析、delegated Agent Run、RunGroup source、Task↔Run link、RunEvent replay、ChatSession 最终投影和 delegated summary 的 Chat UI 投影都在同一 source Bridge 环境下闭环。summary 创建本轮使用 `/ui/chat/delegated-run-summary` route 显式触发，不把它记作主聊天自动委派 UI 的按钮级交互。

### Browser launcher session summary E2E

本轮继续补会话总结在 Bubble / Live2D launcher 壳里的真实浏览器证据，并先给前端补稳定 DOM selector：

- `LauncherPayload.chat` 类型显式承接 `recent_sessions`。
- Bubble desktop surface 暴露 `bubble-launcher-shell`、`bubble-launcher-summary`、`bubble-launcher-latest-reply` 和 `bubble-launcher-recent-session`。
- Live2D desktop surface 暴露 `live2d-launcher-shell`、`live2d-launcher-reply`、`live2d-launcher-reply-text`、`live2d-launcher-latest-reply`、`live2d-launcher-recent-session` 和 quick input selectors。
- `tests/test_frontend_feature_preservation.py::test_launcher_views_expose_session_summary_e2e_selectors` 锁定这些 selector，避免后续 Browser smoke 失去稳定断言点。

source 环境：

```text
source Bridge: http://127.0.0.1:8420  # isolated OHA_YACHIYO_HOME, no session token for source Browser
source Vite:   http://127.0.0.1:5174
fake provider: http://127.0.0.1:18779/v1  # profile test returns OK, chat stream returns launcher summary sentinel
Browser routes:
  http://127.0.0.1:5174/#/bubble?surface=desktop
  http://127.0.0.1:5174/#/live2d?surface=desktop
```

验证路径：

- 通过 Bridge 创建并测试默认 Chat ModelProfile，随后 `/ui/chat/messages` 发送 `Please create launcher session summary browser smoke evidence.`。
- TaskRunner 走 `NativeAgentExecutor` / `NativeRunEngine` / streaming fake provider 完成 `main_chat_run`，ChatSession assistant 投影为 `Browser launcher session summary complete`。
- `/ui/launcher?mode=bubble` 返回 `launcher.latest_reply=Browser launcher session summary complete`，`chat.recent_sessions[0].summary` 包含同一 assistant 回复。
- in-app Browser 打开 Bubble desktop surface 后，`bubble-launcher-summary`、`bubble-launcher-latest-reply` 和 `bubble-launcher-recent-session` 均包含 `Browser launcher session summary complete`。
- in-app Browser 打开 Live2D desktop surface 后，`live2d-launcher-reply-text`、`live2d-launcher-latest-reply` 和 `live2d-launcher-recent-session` 均包含 `Browser launcher session summary complete`。
- Browser console error 为空。

这一步把此前 ChatBridge / launcher route 级会话总结合同推进到真实 Browser DOM：主聊天、NativeRunEngine、ChatSession summary、Bubble desktop surface 和 Live2D desktop surface 使用同一个 source Bridge 数据源闭环。

### Chat cancel late-output hardening

本轮继续推进主聊天取消路径，先用慢速 OpenAI-compatible fake model 做真实 UI 取消 smoke，发现一个真实生命周期 bug：

- 用户在 Chat UI 点击 `停止当前任务` 后，ChatSession 消息已正确变成 `任务已取消`。
- AppState Task 已变成 `cancelled`。
- 但对应 `main_chat_run` 仍保持 `running`。
- 8 秒后慢模型返回，late model output 被写进 Run result / timeline，Run 仍未进入终态。

根因：

- `NativeAgentExecutor` 在 `asyncio.CancelledError` cleanup 中继续 `await asyncio.to_thread(service.cancel_run, run_id)`。
- 当前 coroutine 已处于 cancellation 状态，cleanup await 本身可能被取消，导致 `cancel_run()` 没有可靠执行。
- `NativeRunEngine.execute_main_chat_model_loop()` 在模型返回后无条件写入 `model.output.ready` / `model.output.completed` 并 `_update_run(status="running")`，没有检查 Run 是否已被其他线程取消。

已修复：

- `NativeAgentExecutor` 的 cancellation cleanup 改为同步调用 `service.cancel_run(run_id)`，保证已创建的 Native Run 立即进入 `cancelled`。
- `NativeRunEngine` 新增 `_terminal_run_or_none()`。
- `call_main_chat_model()` / `execute_main_chat_model_loop()` 在模型异常和模型返回后检查终态；若 Run 已是 `completed` / `failed` / `cancelled`，不再写 late output、failure 或 completed event。
- `complete_main_chat_run()` / `fail_main_chat_run()` 遇到既有终态直接返回，不再覆盖 cancelled Run。

新增回归：

- `tests/test_agent_runtime.py::test_main_chat_cancelled_run_ignores_late_model_output`
  - 模拟模型调用期间 `cancel_run()` 已执行。
  - late model output 返回后，Run 仍为 `cancelled`。
  - 不写入 `model.output.completed`、`run.completed` 或 `run.failed`。

Post-fix 验证：

- 由于 in-app Browser native pipe 在复验时断开，post-fix 复验使用同一 source Bridge 路由完成：
  - `POST /ui/chat/messages`
  - `POST /ui/chat/session/cancel`
  - 等慢模型 8 秒返回后读取 `/ui/runs` 与 `/runs/{run_id}/events`
- 结果：

```text
Run status: cancelled
Run result: ""
RunEvent sequence:
1 run.started
2 task.linked
3 model.request.started
4 run.cancelled
```

- `model.output.completed` 不再出现，late fake model response 没有覆盖 cancelled Run。

### Main chat approval projection

本轮继续补齐 PR-2 的主聊天审批等待投影：`NativeAgentExecutor` 已经会在执行协程中把审批文案写入 processing assistant message，但 Chat API 的状态同步缺少兜底。若 UI 轮询、进程重载或同步路径先发生，RUNNING Task 只能看到普通 processing 状态，无法稳定显示待审批工具。

已修复：

- `ChatAPI._sync_task_status_to_messages()` 在 Task 仍为 `RUNNING` 时，会通过 `task_run_links` 查找对应 `main_chat_run`。
- 当 linked Run 为 `approval_required` 且有 `pending_approval.tool`：
  - ChatSession assistant processing message 写入审批文案。
  - metadata 写入 `run_status=approval_required`、`run_id`、`run_group_id`、`pending_approval`、`run_progress_title/detail`。
  - ActivityStore 写入幂等事件 `{task_id}-main-chat-approval-required`，`phase=tool_start`，`status=approval_required`，`tool_name` 为实际工具。
- 当 linked Run 从 `approval_required` 回到 running/processing/pending：
  - ChatSession 清空 `pending_approval`。
  - metadata 写入 `run_status=processing` 和“审批已通过，正在继续执行”的 progress 文案。

新增回归：

- `tests/test_chat_api.py::test_running_main_chat_task_projects_native_tool_approval`
  - 构造 RUNNING Task、user message、Task↔Run link 和 `approval_required` main_chat_run。
  - `api.get_messages()` 后，ChatSession assistant message 显示工具审批内容，metadata 可驱动 Chat UI approval card。
  - ActivityStore 中出现同一 task 的 `approval_required` 可见活动事件。
- `tests/test_chat_api.py::test_running_main_chat_task_clears_approval_projection_after_resume`
  - 审批通过后 linked Run 回到 running，ChatSession 清空 `pending_approval`，避免 UI 继续显示旧审批卡片。

### Main chat approval roundtrip

本轮继续把主聊天工具审批从“投影合同”推进到真实执行往返：

- `NativeAgentExecutor` 新增可选 `tool_policy_getter` / `workspace_policy_getter`，允许主聊天在受控入口下把工具策略和 workspace 策略传给唯一的 `NativeRunEngine.execute_main_chat_model_loop()`。
- `AppRuntime.main_chat_tool_policy()` / `main_chat_workspace_policy()` 已接入 `select_executor(runtime)`，真实产品路径会把主聊天工具与 workspace policy 传入 `NativeAgentExecutor`。
- 主聊天默认允许 `workspace.list`、`workspace.read`、`workspace.write_patch`、`terminal.run`、`artifact.write`；其中 `workspace.write_patch` 和 `terminal.run` 强制走 approval。
- workspace policy 默认使用已初始化 workspace 的 `projects` 目录；未初始化时由 `NativeRunEngine` 兜底到内置 main-chat workdir，读写 scope 都限制在 `.`。
- 该接入点用于后续 UI/设置侧把用户选择的 trusted workspace 继续收敛到 Runtime 方法，而不是为主聊天创建第二套 agent runtime。
- `NativeRunEngine.approve_run_approval()` 新增 per-run approval resume guard，并在 `run_approvals` 上使用 SQLite `BEGIN IMMEDIATE` + pending→approved 条件更新作为持久化 claim：同一个 Run 正在恢复执行时，重复 approval 会返回当前 Run 状态，不会再次执行已批准工具；顺序重复 approval 继续由 Run status / approval claim 检查保持幂等。

新增回归：

- `tests/test_task_runner.py::test_task_runner_main_chat_native_tool_approval_roundtrip`
  - 使用真实 `TaskRunner._execute_with_state()`、真实 `NativeAgentExecutor`、真实 `AgentRuntimeService / NativeRunEngine`。
  - fake model 第一次返回 `workspace_write_patch` tool call。
  - Run 进入 `approval_required`，Task 保持 `RUNNING`。
  - `ChatAPI.get_messages()` 投影 ChatSession approval metadata，并写 ActivityStore 待审批事件。
  - 调用 `approve_run_approval()` 后工具执行，workspace 文件被修改。
  - fake model 第二次返回最终文本，Task 完成，ChatSession assistant message 最终为 completed。
  - RunEvent 包含 `agent.tool.approval_required`、`agent.tool.approval_approved`、`model.output.completed`、`run.completed`。
- `tests/test_runtime.py::test_main_chat_runtime_policies_enable_native_tools_with_approval`
  - 锁定 AppRuntime 默认 main-chat tool/workspace policy。
- `tests/test_executor.py::TestNativeAgentExecutor::test_select_executor_uses_native_when_ready`
  - 锁定 `select_executor(runtime)` 会把 AppRuntime policy getters 接到 `NativeAgentExecutor`。
- `tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice`
  - 模拟主聊天模型返回 `workspace.write_patch` 后进入 `approval_required`。
  - 第一次 approval 恢复模型时并发提交第二次 approval。
  - 验证 workspace 文件只被修改一次，模型调用数保持 initial + one resume，RunEvent 只出现一条 `agent.tool.approval_approved` 和一条 approved `agent.tool.call`。
- `tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution`
  - 使用两个 `AgentRuntimeService / NativeRunEngine` 实例共享同一 SQLite runtime DB。
  - 第一个实例保持 Run 处于 `approval_required`，第二个实例先 claim 同一 approval 行。
  - 验证后续 approval 请求不会追加 `agent.tool.approval_approved`、不会执行 `workspace.write_patch`、不会恢复模型调用。

### Main chat image attachment roundtrip

本轮补齐主聊天图片附件在真实产品执行层的闭环验证。之前已有两段分散覆盖：

- `ChatAPI.send_message()` 能把 pasted image data URL 保存为 attachment 文件，并把公开 URL 投影给 Chat UI。
- `NativeAgentExecutor` 能把 Task attachment 文件转换成 OpenAI-compatible `image_url` data URL。

新增回归把这两段接成一条路径：

- `tests/test_task_runner.py::test_task_runner_main_chat_image_attachment_reaches_native_model`
  - 通过真实 `ChatAPI.send_message()` 提交 `data:image/png;base64,...` 图片附件。
  - 真实 `TaskRunner._execute_with_state()` 执行该 Task。
  - 真实 `NativeAgentExecutor` 从 Task attachment 读取文件并传给 `NativeRunEngine.execute_main_chat_model_loop()`。
  - fake model 直接断言收到的最后一条 user message 是 OpenAI-compatible content parts：`text` + `image_url`，且 `image_url.url` 与原始 data URL 内容一致。
  - 验证 ChatSession 中用户消息只暴露 `/ui/chat/attachments/{id}` 公共 URL、不泄漏本地 path。
  - 验证 Run 完成，并包含 `task.linked`、`model.output.completed`、`run.completed` 可回放事实。
  - 通过 `apps.bridge.routes.agents.get_any_run()` / `list_runs()` 验证 Agent Studio Run Detail 依赖的 `/ui/runs` projection 可读取同一 `main_chat_run`。
  - 通过 `apps.bridge.routes.runs.list_run_events()` 验证 `/runs/{run_id}/events?after_sequence=0&limit=200` 可回放同一 Run 的 user-visible facts，并验证 `after_sequence` / `limit` 分页行为。

### Workflow approval replay facts

本轮补齐 Workflow 审批等待的 replayable fact 缺口。此前 Workflow Run 的 `timeline_json` 已能驱动 Agent Studio / Run Detail 显示审批等待，但部分等待事实没有进入 `run_events`，导致 `/runs/{run_id}/events` 无法完整回放 Workflow 审批状态。

已修复：

- Workflow start / agent / artifact 节点实际执行时写入 `workflow.node.start` / `workflow.node.agent` / `workflow.node.artifact` RunEvent。
- Workflow 自身 approval node 暂停时写入 `workflow.node.approval_required` RunEvent。
- Workflow 等待子 Agent 工具审批时写入 `workflow.run.approval_required` RunEvent。
- 子 Agent 工具审批恢复后，父 Workflow 继续追加同一 `workflow.node.agent` 的状态转移 RunEvent：`approval_required → running → completed`。
- 子 Agent 工具审批拒绝后，父 Workflow 追加 `workflow.node.agent(cancelled)` 和 `workflow.run.cancelled` RunEvent。
- Workflow 子 Agent 审批批准后，父 Workflow 写入 `workflow.run.child_resumed` 和 `workflow.run.resumed` RunEvent。
- `WorkflowParentResumeCoordinator` 通过显式 `append_run_event` 回调写事实日志，不再依赖隐式 engine 全局。

新增/扩展回归：

- `tests/test_agent_runtime.py::test_workflow_approval_node_pauses_and_resumes`
  - 断言 approval node 暂停时 `/runs/{run_id}/events` 含 `workflow.node.approval_required`，payload 包含节点 id、label、criteria 和公开 pending approval。
  - 断言审批恢复后 replay 继续包含 `workflow.node.approval_approved` 和 `workflow.run.completed`。
- `tests/test_agent_runtime.py::test_workflow_child_approval_route_approve_resumes_parent_workflow`
  - 通过 route 级 `/ui/runs/{run_id}` projection 验证父 Workflow Run Detail 能看到 `workflow.run.approval_required` 和 child run id。
  - 通过 route 级 `/runs/{run_id}/events` 验证父 Workflow replay 含 `workflow.run.approval_required`，子 Agent replay 含 `agent.tool.approval_required`。
  - 验证子 Agent 审批通过后，父 Workflow replay 含且只含一条 `workflow.run.child_resumed`、一条 `workflow.run.resumed`，最终含 `workflow.run.completed`。
  - 验证同一 child run 的 `workflow.node.agent` replay 状态链为 `approval_required → running → completed`。
  - 验证 `/ui/runs` 列表隐藏 workflow child agent run，但 `get_any_run(child_run_id)` 仍可供 Run Detail bridge 拉取子 Run。
- `tests/test_agent_runtime.py::test_workflow_child_approval_route_reject_cancels_parent_workflow`
  - 通过 route 级 `/runs/{run_id}/events` 验证子 Agent 工具审批拒绝后，父 Workflow replay 含 `workflow.node.agent(cancelled)` 和 `workflow.run.cancelled`。
- `tests/test_agent_runtime.py::test_workflow_artifact_review_route_exposes_outputs_and_reruns`
  - 通过 route 级 `/runs/{run_id}/events` 验证无审批 Workflow 的 replay 节点序列与 timeline 一致：start → agent → agent → artifact。
  - 验证 `workflow.node.agent` RunEvent payload 包含 child run id、节点 id、状态和 artifact count。
  - 验证 `workflow.node.artifact` RunEvent payload 包含最终 artifact path。

### Secret 持久化清洗

本轮补齐了 P0 安全护栏中的一个真实缺口：ChatSession / ChatStore 之前会把用户消息正文、错误、附件 JSON 和 metadata JSON 直接写入 `chat.db`。如果用户在聊天里贴出 API Key、token 或 password，这些内容会进入用户可见 transcript 存储。

已完成：

- 新增 `packages.security` 共享 redactor：
  - 统一识别 `api_key`、`token`、`password`、`secret`、`authorization`、`bearer`、`sk-*`、GitHub token、Slack token 等常见 secret 形态。
  - 支持 JSON-like payload 按 key 清洗，例如 `{ "token": "..." }` 即使 value 不是 `sk-*` 形态也会被替换。
  - 支持隐藏原始 `<tool_call>...</tool_call>` 草稿，避免 tool 参数直接进入用户可见日志。
- `ActivityStore` 改为使用共享 redactor，保留原有压缩空白和长度限制行为。
- `RunEventRepository.append()` 对 durable RunEvent payload 使用 key-based sanitizer；内部 Workflow/Agent 恢复快照继续使用原字符串 redaction，避免清洗 `model_config.api_key` 后破坏运行中 approval resume。
- `ChatSession` 标准 API 在进入内存前清洗 user / assistant / system 消息正文、错误、附件和 metadata。
- `ChatStore` 作为最后入库边界再次清洗 `save_message()`、`update_message_status()`、session title、execution session id 和 session context JSON。
- `ChatStore` 初始化时会清洗旧 `chat.db` 已存在的明显 secret，再执行 checkpoint / `VACUUM`，并启用 `PRAGMA secure_delete=ON`，避免历史 transcript 明显 secret 继续留在当前 SQLite 文件和 WAL 中。
- `packages.security` 新增 process-wide logging redaction：
  - 标准库 logging record 会在格式化后清洗 secret，并清洗 `exc_info` / `exc_text` / `stack_info`。
  - 桌面后端 `_setup_logging()` 会安装 logging redaction 和 redacted `sys.excepthook`，未捕获异常 traceback 不直接输出明显 secret。
- `packages.security` 新增 HTTP/API 错误边界 helper：
  - `redact_api_error_text()` 用于 UI JSON 中的 `error` / `message` 字段。
  - `redact_api_error_detail()` 用于 FastAPI `HTTPException.detail`，支持嵌套 dict/list payload。
  - Bridge app 在真实 FastAPI runtime 下注册 redacting HTTPException handler；测试 mock 不具备 handler registry 时跳过注册，保持 backend import smoke。
  - Agent Studio route、Model Profile route、Task API cancel error、剪贴板 route、ChatAPI、ChatBridge、MainWindowAPI、TTS/GPT-SoVITS/Live2D resource import、provider catalog cache、terminal helper、ModelProfile 连接测试、NativeRunEngine failure projection 等 UI/API 可见错误路径已接入清洗。
- 新增 `scripts/verify_secret_redaction.py`：
  - 默认扫描 `OHA_YACHIYO_HOME`、`.oha-yachiyo-config` 和 macOS app log 候选目录。
  - 支持显式扫描 runtime/log/cache/artifact 目录，覆盖 `.log`、`.json`、`.db`、`.sqlite`、`.wal`、`.crash` 等常见落盘文件。
  - finding 只输出路径与行号，不回显命中的 secret 原文。
  - 当前默认运行时目录扫描结果为 `secret redaction verification passed`。
- `artifact.write` 文件内容已通过回归锁定：写入前清洗明显 secret，写入后 artifact 目录可通过 `verify_secret_redaction()`。
- 主聊天 provider exception 与 tool exception 端到端路径已补回归：异常文本会进入 Run projection / RunEvent / tool-result message 前清洗，并对对应 SQLite / artifact 落盘目录执行 `verify_secret_redaction()`。
- `contains_sensitive_text()` 修复了 SQLite 字节解码时相邻字段拼接造成的 `[redacted]` 误报，例如 `token=[redacted]provider...` 不再被误判为泄漏；真实未清洗 secret 仍会被 scanner 命中。
- 未捕获异常 crash 文件落盘已补回归：redacted `sys.excepthook` 写出的 `.crash` 文件不包含 raw secret，并可通过 `verify_secret_redaction()`。
- Chat transcript 清洗模式不折叠空白、不截断正文，尽量保留用户可见对话语义；Activity/RunEvent 仍按各自边界执行压缩或限制。
- ModelProfile / Agent Studio 旧明文 API Key 迁移现在会在成功搬迁到 CredentialStore 后执行 SQLite checkpoint / `VACUUM` / checkpoint；legacy `model_sources.api_key`、`model_profiles.api_key` 和 `agents.model_api_key` 均已有 raw SQLite / WAL 目录级 `verify_secret_redaction()` 回归，证明旧 secret 不继续残留在当前 DB 文件中。

### Harness 边界收敛

本轮新增或显式化的内部边界：

- `RunRepository`
  - 负责 runs 表 get / list / insert / update / delete rows / idempotency lookup / private pending approval payload read。
  - 保留 `NativeRunEngine` 公开方法作为薄委托，路由和业务调用不变。
  - update 继续统一处理 secret redaction、Run row/timeline 落库，并通过 `RunProjectionCoordinator` 同步 artifact / pending approval / TaskRunLink status 投影。
  - delete rows 通过显式 artifact cleanup 回调删除对应 artifact 文件后再删除 runs 表记录，`NativeRunEngine.delete_run()` 保留 active-run 检查、Workflow group 删除策略和返回结构。

- `RunEventRepository`
  - 负责 RunEvent durable append / replay list。
  - sequence 分配在 `BEGIN IMMEDIATE` 事务内完成。
  - append 成功后通过注入的 projection callback 同步 replay cursor，避免 `NativeRunEngine.append_run_event()` 直接维护 TaskRunLink 投影字段。
  - 默认 list 只返回 user-visible 且非 secret events。
  - limit clamp 保持默认 200、最大 1000。

- `TaskRunLinkRepository`
  - 负责 `task_run_links` 的 Task↔Run 映射、按 Run 读取、Run status projection 和 replay `last_event_sequence` projection。
  - 保留 `NativeRunEngine.link_task_run()` / `get_task_run_link()` 作为 TaskRunner、ChatAPI 和路由兼容入口。

- `RunProjectionCoordinator`
  - 负责 Run update 后同步 `run_artifacts`、`run_approvals` 和 `task_run_links` status projection。
  - 负责 RunEvent append 后同步 `task_run_links.last_event_sequence` replay cursor projection。
  - `RunRepository.update()` 和 `RunEventRepository.append()` 直接调用该边界，`NativeRunEngine` 不再保留单独的 Run projection / TaskRunLink projection 同步 helper。

- `ApprovalRepository`
  - 负责 `run_approvals` pending / resolved 投影同步。
  - 保留 approve / reject 现有幂等业务语义。

- `ApprovalCoordinator`
  - 负责 approval approve / reject / timeout 的通用 lifecycle transition。
  - 统一写入 approval timeline、RunEvent 和 pending approval 清理。

- `ApprovalResumeCoordinator` / `ToolApprovalResumeContext`
  - 负责批准后 pending approval 持久化 claim 和 running projection，重复 approval claim 直接返回当前 Run，不重复执行工具。
  - 负责批准后恢复时的已批准工具调用执行。
  - `ToolApprovalResumeContext.from_run()` 统一解析 pending approval 中的 messages、tool request、remaining requests、next iteration、timeline 和 artifacts，并用同一份 timeline 构造 resume budget。
  - `ToolApprovalClaimProjection` 负责批准 claim 成功后的 running Run 投影 payload，避免 claim 分支继续直接拼 timeline、artifact、tool name 和 input preview 参数。
  - `ToolApprovalExecutionRequest` 负责 approved-tool 调用参数交接，固定 `approved=True`、run id、budget、timeline 和 artifact 传递。
  - `ToolApprovalContinuationHandoff` 负责批准工具执行后的 custom API continuation 参数交接，避免 coordinator 内继续散落 broker、timeline、artifacts、messages、iteration、run id 和 budget 参数拼装。
  - `ToolApprovalCustomApiContinuationRequest` 负责 approved-tool 后 custom API 模型续跑回调参数交接。
  - `ToolApprovalExecutionFollowup` 负责批准工具成功后的 tool-result message 追加和 remaining tool requests 续跑参数交接。
  - `ToolApprovalContinuationOutcome` 负责批准工具执行后的 completed / approval_required / failed continuation outcome 投影分派；`continue_and_project_after_approved_tool()` 保留模型继续执行与 outcome 构造，`resume_approved_tool_run()` 保留 claim、running projection 和最终 result projection 编排。
  - `ToolApprovalExecutionFailureProjection` 负责 approved-tool fatal failure timeline event 和错误详情，避免 `execute_approved_tool()` 直接拼失败 replay payload。
  - 主聊天和 Agent Run 的工具审批恢复共用同一个 resume context 和 coordinator。
  - 保留 `NativeRunEngine` 对最终模型继续执行和 Run 状态落库的编排职责。

- `ApprovalResumeProjectionCoordinator`
  - 负责 approved-tool resume 后的 running / completed / approval_required / failed Run 投影。
  - 负责 Agent approved-tool resume running 时的 RunGroup 投影和父 Workflow child-running 通知。
  - 负责 Agent completed、主聊天 model output completed、二次 tool approval required 和 failed replay facts。
  - `NativeRunEngine._project_agent_approval_resume_running()`、`_project_agent_approval_resume_completed()`、`_project_main_chat_approval_resume_completed()`、`_project_approval_resume_required()`、`_project_approval_resume_failed()` 保留为薄 wrapper，成熟测试 spy 点不变。

- `ToolApprovalTransitionContext`
  - 统一解析 tool approval pending payload 中的 tool name 和 input preview。
  - 普通 Agent / 主聊天 tool approval reject / timeout 共享该结构，避免两个分支各自解析 pending tool request。

- `RunTransitionProjectionCoordinator`
  - 负责非 Workflow-root child Run 状态变化后的 Agent RunGroup 投影和父 Workflow 恢复通知。
  - 负责 standalone/root Agent Run 创建完成后的 RunGroup status/summary 投影。
  - 普通 Run cancel、Agent approved-tool resume 结束、普通 Agent / 主聊天 tool approval reject / timeout 共享该边界，避免各分支各自维护相同结束投影。
  - 负责 Workflow approval reject / timeout 和 `cancel_run()` root Workflow 取消后的 root RunGroup cancelled 状态和 summary 投影。
  - `NativeRunEngine._project_child_run_transition()`、`_project_agent_run_group_if_root()` 和 `_project_cancelled_workflow_group_if_root()` 保留为薄 wrapper，成熟测试 spy 点不变。

- `WorkflowApprovalTransitionContext`
  - 统一解析 Workflow approval pending payload 中的 node id、label、criteria 和 input preview。
  - Workflow approval approve / reject / timeout 共享该结构，避免三个分支各自解析 pending approval 字段。

- `WorkflowApprovalResumeContext`
  - 统一解析 Workflow approval approve 恢复所需的 workflow context、next index、timeline、artifacts 和 root group 标记。
  - 避免 `NativeRunEngine._approve_workflow_run_approval()` 继续直接拼装 pending payload、恢复位置和 Workflow continuation 参数。

- `WorkflowParentResumeCoordinator`
  - 负责子 Agent Run 状态变化后标记父 Workflow running / approval_required / failed / cancelled / resumed。
  - `WorkflowChildRunProjection` 负责父 Workflow replay 中的 child run 状态、result preview、artifact count 和 node metadata payload。
  - `WorkflowChildStatusProjection` 负责父 Workflow child transition 的 projected / fallback status payload 和 result payload，避免 approval / terminal / resumed 分支重复拼字典。
  - `WorkflowParentResumeFailureProjection` 负责 child completed 后继续父 Workflow 失败时的错误清洗、failed timeline payload 和 Run update 字段。
  - 负责合并子 Run 结果、子 artifact references、父 Workflow timeline 和 RunGroup 状态更新。

- `WorkflowContinuationCoordinator`
  - 负责 Workflow start / agent / approval / artifact 节点执行。
  - 负责 Workflow 节点 timeline、child Agent Run 创建、approval pause、artifact write、completed/failed 状态落库。
  - `WorkflowStartNodeProjection` 负责 Workflow start node 的 timeline event 和 RunEvent replay payload。
  - `WorkflowAgentNodeHandoff` 负责从 Workflow agent node 解析 child Agent、child goal、upstream context、node metadata 和 replay payload，避免 child-run 参数继续散落在执行循环内。
  - `WorkflowAgentNodeExecution` 负责从 handoff 创建并执行 child Agent Run，集中维护 next context、artifact count、agent replay payload 和 status replay payload。
  - `WorkflowApprovalPauseProjection` 负责 Workflow approval node 暂停时的 private pending approval、public replay payload、timeline event 和 Run update 字段。
  - `WorkflowArtifactNodeWrite` 负责 Workflow artifact node 的 artifact path 解析、文件写入、artifact record 和 replay payload。
  - `WorkflowRunCompletionProjection` 负责 Workflow completed timeline、RunEvent payload 和 Run update 字段。
  - `WorkflowContinuationFailureProjection` 负责 Workflow continuation 节点执行异常时的错误清洗、failed timeline、RunEvent payload 和 Run update 字段。
  - 负责异步 Workflow 后台线程异常时的 failed Run、RunEvent 和 root RunGroup 投影。
  - `NativeRunEngine._continue_workflow_run()` 保留为薄 wrapper，成熟调用点不变。

- `WorkflowCancellationProjectionCoordinator`
  - 负责 Workflow Run 取消时的 pending approval / child approval / child outcome 合并与 Workflow timeline 投影。
  - `WorkflowCancellationTarget` 负责 pending approval / waiting child 两类取消目标的 label、node metadata、child run id、timeline payload 和 result 文本。
  - `RunCancellationProjection` 负责普通 Run / Workflow Run 取消后的统一 `_update_run()` 字段，避免 cancel 分派继续直接拼状态、result、timeline、artifacts 和 pending approval 清理字段。
  - 负责父 Workflow 取消时取消等待中的子 Agent Run，并合并子 Run 结果、artifact references 和 workflow node 元数据。
  - `NativeRunEngine._cancel_workflow_run_projection()` 保留为薄 wrapper；`_cancel_run_once()` 保留普通 Run 与 Workflow Run 的取消分派、最终落库、RunGroup 更新和父 Workflow 恢复通知。

- `_coalesce_model_message()`
  - 普通 provider 返回 dict 时行为保持不变。
  - provider 返回 stream iterable 时先在内存中合并 delta 内容，再交给现有 completed-event 持久化路径。
  - streaming chunk 兼容 dict-style `choices[].delta.content`、OpenAI SDK object-style `chunk.choices[0].delta.content`，以及 OpenAI-style `choices[].delta.tool_calls[]` 分片。
  - 当前覆盖主聊天模型 loop；避免未来接入 streaming provider 后退化成 token/delta 级 RunEvent 写入。

- `RunArtifactRepository`
  - 负责 `run_artifacts` 投影同步。
  - 负责按 Run kind 读取和删除 agent / workflow artifact 文件。
  - `NativeRunEngine` 保留原公开方法作为薄委托。

- `RunGroupRepository`
  - 负责 `run_groups` list / get / source / insert / append / update / delete。
  - 负责 child run membership 更新和空 group 清理。
  - 负责 title/source/workspace_dir insert 投影、summary update 投影和旧库 run_groups 投影迁移的 secret redaction。
  - 保留原 Run group 路由和 Workflow/Agent Studio 行为不变。

- `ToolDescriptor` / `ToolDescriptorRegistry`
  - 工具 schema 生成和 payload validation 共用同一份 descriptor。
  - `workspace.write_patch` schema 已补齐 `patch`、`expected_sha256`、`base_sha256` 字段，避免 schema 与 validator 不一致。
  - `workspace.write_patch` 已收敛为 patch-only：tool schema 不再暴露 `content`，payload validator 拒绝未声明 `content` 字段，direct ToolBroker 入口也拒绝 content 全量写入。
  - `workspace.write_patch` patch 模式已限制为单文件 UTF-8 unified diff，拒绝多文件、二进制、删除、新建和重命名 patch。

- `PolicyGate`
  - 工具 allow-list 判断从 `_call_agent_tool` 内部逻辑中抽出为显式边界。

- `DelegationDirective`
  - 主聊天自动委派内部已从原始 JSON dict 收敛为结构化 directive。
  - 自动委派 parser / runner / ActivityStore tool name 已收敛为 OHA 命名：`run_oha_agent` / `run_oha_workflow`、`_parse_oha_delegation_*`、`_run_oha_delegation()` 和 `oha.delegation`。
  - 旧 `run_yachiyo_*` action 和 `<yachiyo_delegation>` tag 已移除为有效入口；旧 dict 输出仍作为内部适配器保留。
  - 底层仍通过 `NativeRunEngine.delegate_runnable()` 执行 Agent/Workflow。
  - `NativeAgentExecutor` 的自动委派现在把当前注入的 `NativeRunEngine` 传给 `_run_oha_delegation()`，不再在 TaskRunner 产品路径中回退到全局 runtime 实例，保证 Task↔Run 映射、测试注入和同一 runtime 数据库边界一致。

- `GroupDispatchDirective`
  - 群聊派活内部已从原始 JSON dict 收敛为结构化 directive。
  - 主模型群组提示已从旧 `<yachiyo_group_dispatch>` 文本块切到 native JSON envelope：`{"tool":"oha.group_dispatch","input":...}`。
  - parser 接受 `oha.group_dispatch` / `native.group_dispatch` / `<oha_group_dispatch>` 等中性命名；旧 `<yachiyo_group_dispatch>` 文本块已移除为有效入口，即使旧 tag 内包着合法 OHA JSON 也不会触发派发，旧 `_parse_group_dispatch_requests()` dict 输出仍作为内部适配器保留。
  - Chat UI 可见内容清理会移除旧紧凑/未闭合 group dispatch tag 与 payload，避免 streaming 期间暴露内部协议片段；该路径只做显示清理，不把旧 Hermes/Yachiyo 协议重新作为有效执行入口。
  - 群聊、手动 Agent、群总结和审批显示已有 Chat API 回归覆盖；本轮重新跑了 group_dispatch focused 回归。
  - `ChatAPI` 新增 `_agent_runtime_service()` accessor，优先使用 runtime 注入的 `agent_runtime_service` / `get_agent_runtime_service()`，回退到现有全局 getter；群聊派活、Agent/Workflow mention、Run 状态同步、自动委派 summary 均通过该边界取同一个 NativeRunEngine。

- Skill library source model
  - Agent Studio / Agent Runtime 的 Skill 来源展示从 `Yachiyo Skill Library` / `yachiyo_count` / `source_scope=yachiyo` 收敛为 `Installed Skill Library` / `installed_count` / `source_scope=installed`。
  - `sync_yachiyo_installed_skills()`、`_repair_yachiyo_installed_skill_provenance()`、`_yachiyo_skill_root_specs()` 等内部函数已改为 installed 命名。
  - 旧本地 DB 中 `source_scope='yachiyo'` 和 `studio_deletions.item_key='yachiyo:...'` 会在 runtime 初始化时迁移到 installed 命名；新 API 输入不再接受 `yachiyo` 作为合法 source scope。

新增测试覆盖：

- Runtime SQLite 初始化直接覆盖 `runtime_schema_metadata.schema_version=1`、`PRAGMA foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout=5000`，并验证删除 Run 会通过 FK cascade 清理 `TaskRunLink`。
- NativeRunEngine shutdown 直接覆盖终止 terminal process groups、取消非终态 Run、写入 `run.cancelled` fact、拒绝新 Run，以及 `close_db=True` 关闭 runtime DB 连接。
- AppRuntime shutdown 直接覆盖 runtime 注入的 NativeRunEngine service 会被关闭，同时仍调用全局兼容 service shutdown；AppRuntime 也显式暴露并关闭进程 ActivityStore，避免桌面/测试注入路径漏过执行内核和活动投影生命周期收口。
- 并发 RunEvent 写入 sequence 连续唯一。
- `GET /runs/{run_id}/events` 的 `after_sequence` 归一化、limit 最大 1000、默认隐藏 internal events。
- `GET /runs/{run_id}/events` 路由层覆盖默认隐藏 internal / secret events、limit clamp、after_sequence 分页和 missing run 404。
- `GET /runs/{run_id}/events` 真实 FastAPI/TestClient HTTP 层覆盖 query string 解析、分页、limit clamp、默认隐藏 internal/secret events 和 secret redaction。
- Bridge security middleware 真实 FastAPI/TestClient HTTP 层覆盖可信 Origin CORS header、非 loopback Host 拒绝、非可信 Origin 拒绝，以及 mutating request 必须携带桌面本地 session token。
- 已注册 Bridge mutating routes 枚举回归覆盖当前所有 `POST` / `PUT` / `PATCH` / `DELETE` 路由缺 token 时均由 middleware 返回 `invalid_bridge_token`，防止新增 route 绕过 P0 护栏。
- Bridge 启动/重启 host guard 覆盖 `0.0.0.0` / LAN host 拒绝；`restart_bridge()` 已将 host/port 校验前置，非法重启请求不会停止当前运行中的 Bridge，也不会启动后台线程。
- `POST /runs`、`POST /ui/chat/messages`、`POST /ui/agent-runs` 和 `POST /ui/workflow-runs` 真实 FastAPI/TestClient HTTP 层覆盖 `Idempotency-Key` header 到 `client_message_id` / `client_run_id` 的映射；`NativeRunEngine.create_run_for_runnable()` 会继续把 `client_run_id` 传入底层 Agent/Workflow Run 创建路径。
- `RunRepository` 直接覆盖 secret redaction、pending approval projection 和 client_request_id idempotency lookup。
- `RunArtifactRepository` 直接覆盖 artifact projection secret redaction 和 artifact 文件读取 redaction。
- `RunGroupRepository` 直接覆盖 child membership、list/get、insert title/source/workspace_dir redaction、status/summary update redaction、旧库 run_groups secret scrub + vacuum 和空 group 清理。
- 主聊天模型长输出回归锁定为单条 `model.output.completed` durable event，不写 token/delta 级 RunEvent。
- 主聊天模型 loop 的 stream iterator 压力回归锁定为先合并 300 个 delta chunk，再只写一条 `model.output.completed` durable event。
- 主聊天模型 loop 新增 OpenAI SDK object-style stream chunk 回归：先合并 180 个 `chunk.choices[0].delta.content` 对象 chunk，再只写一条 `model.output.completed` durable event，避免真实 SDK chunk 形态被忽略或退化成逐 token RunEvent。
- 主聊天模型 loop 新增 OpenAI-style streaming tool_call delta 回归：分片合并 `workspace_read` tool call name 与 JSON arguments，执行 `workspace.read` 后恢复模型，并确认 replay 仍只写完成态事件、不写 token/delta 级 RunEvent。
- ToolDescriptor schema 与 payload validation 对 `workspace.write_patch.patch`、content 禁用和 hash precondition 保持一致。
- `workspace.write_patch` 直接覆盖 expected SHA-256、hunk context 校验、单文件 unified diff 应用、多文件/二进制 patch 拒绝和原子写入结果字段。
- `workspace.write_patch` 现在会在进入 approval 前先做 workspace boundary validation；越界写请求不会生成待审批项，会作为受控工具错误回传给模型继续处理，并保持外部文件不变。
- release-like build metadata 直接覆盖 debug routes 禁用、development features 禁用，以及 credential store factory 不选择 dev file fallback。
- `DelegationDirective` 直接覆盖解析、旧 dict 兼容、结构化 directive 执行入口、旧 `run_yachiyo_*` / `<yachiyo_delegation>` 拒绝，以及 executor/chat 自动委派回归。
- 主聊天自动委派新增 TaskRunner 级闭环回归：真实 `TaskRunner._execute_with_state()`、`NativeAgentExecutor`、`AgentRuntimeService / NativeRunEngine` 能处理主模型输出的 `run_oha_agent` JSON，创建 delegation Agent Run，写入 ActivityStore，再把委派结果回填给主模型生成最终 ChatSession 回复；该回归同时锁定自动委派使用当前注入的 runtime service，而不是隐式全局 runtime。
- `GroupDispatchDirective` 直接覆盖解析、旧 dict wrapper 兼容、`oha.group_dispatch` native envelope、`<oha_group_dispatch>` tag、旧 `<yachiyo_group_dispatch>` tag 拒绝、旧 tag 内 OHA JSON 不执行，以及群聊派发执行入口；group_dispatch focused Chat API 回归已重新通过。
- 群聊派活新增真实 `AgentRuntimeService / NativeRunEngine` 闭环回归：runtime stub 注入 service 后，ChatAPI 创建群组、解析主模型 `oha.group_dispatch`、创建真实 Agent Run、把群组 upstream 注入 Agent context、回写 ChatSession、创建主模型群总结 Task，全程不 monkeypatch ChatAPI 全局 runtime getter。
- 群聊 streaming 显示回归覆盖旧紧凑 `<yachiyogroupdispatch>` 未闭合 tag 与 smart quotes payload：Chat UI content / metadata 不暴露 tag 或 payload，同时旧协议仍不触发派发。
- `builtin:yachiyo-main` 新增 Runtime/Agent Studio 合同回归：作为 system/virtual/deletable=false/editable=false 的系统 Agent 出现在 `list_agents` / `get_agent` / `resolve_runnable` / `list_runnables`，不写入普通 `agents` 表，不能 create/update/delete 覆盖，且不会进入自动委派目标。
- Agent Studio source-level guard 锁定系统 Agent 只读 UI：删除、批量删除、保存、测试模型、Quick Run 和 Skill 挂载路径均受 `selectedAgentReadOnly` / `selectedAgentDeletable` 保护。
- Skill library focused 回归覆盖 Native skill sync、installed skill reinstall restore、folder count `installed_count`、install command validation 和 Skill route sync。
- FastAPI packaged route 注册回归锁定 `Request` 参数不再使用 optional union 注解。
- `/status` route 回归锁定版本来自 `get_app_version()`，不是 protocol 默认值。
- `app_version.py check` 现在覆盖 protocol schema 和 `main_api.py` fallback 版本同步。
- `Frontend feature-preservation smoke` 锁定 Chat、群聊、Agent Studio、Workflow、Run Detail、approval UI、Activity、Proactive TTS、local screenshot、manual TTS、Live2D 顶层入口不被误删。
- `/screen/current` 在 macOS 屏幕录制权限不足时返回 403 结构化 `screen_capture_permission_denied`，提示系统设置授权；route function 和真实 FastAPI/TestClient HTTP 层均已覆盖，不再把权限不足折叠成普通 adapter error。
- ChatAPI 用户明确要求查看桌面但截图权限不足时，仍保留发送消息和创建 Task 的业务语义，同时在 response、用户消息 metadata 和 ActivityStore 用户可见 feed 写入结构化 `desktop_snapshot_error`；该错误会清洗 secret，幂等重放不丢失该错误，并已对本次 ChatStore / ActivityStore SQLite 落盘目录执行 `verify_secret_redaction()`。
- approval projection 和 approved-tool resume 抽出后，批准、拒绝、重复审批、Workflow approval focused tests 仍通过。
- Run approval route handler 级回归覆盖 approve/reject 幂等：终态重复 approve 不触发新执行；重复 reject 不追加第二条 `agent.tool.approval_rejected` fact，也不会执行待审批工具。
- 主聊天与 Agent Run 的工具审批恢复测试直接 spy `ApprovalResumeCoordinator.execute_approved_tool()`，确认批准后工具执行走统一边界。
- Workflow child approval resume 测试直接 spy `WorkflowParentResumeCoordinator.mark_child_running()` / `resume_after_child_update()`，确认父子 Run 联动走统一边界。
- 基础线性 Workflow 测试直接 spy `WorkflowContinuationCoordinator.continue_run()`，确认 Workflow 节点执行走统一边界。
- release artifact verifier 覆盖当前 release-facing 文件通过、旧产品 token 报错、旧 build metadata 文件名报错。
- 主聊天工具审批等待超时现在通过 `NativeRunEngine.timeout_run_approval()` 写入 `approval.timeout` RunEvent，清理 pending approval projection，并保持重复 timeout 无副作用。
- `NativeAgentExecutor` 审批等待超时优先调用运行时 timeout 边界，不再把已 timeout/cancelled 的 Run 覆盖成普通 `run.failed`。
- `NativeAgentExecutor` 审批等待超时现在保留 runtime 返回的 `工具审批已超时：approval_wait_timeout` 作为用户可见失败文案；TaskRunner 产品路径回归覆盖 Task 进入 failed、ChatSession assistant 失败态清理 `pending_approval`、`approval_count` 回到 0、ActivityStore 写入 failed 里程碑、RunEvent 只保留一条 `approval.timeout` 且目标 workspace 文件未被修改。
- ChatAPI 主聊天审批投影修复 `_linked_main_chat_run_for_task()` 错误 staticmethod，确保 RUNNING Task 可通过当前 runtime service 的 Task↔Run link 读取 main_chat_run，并把 `approval_required` 稳定投影到 ChatSession metadata、ActivityStore 和 `approval_count`。
- NativeRunEngine 可见输出提取现在不再把非流式 provider dict/object message 的 `reasoning_content` 当作用户可见正文；`call_main_chat_model()` 和主聊天 `execute_main_chat_model_loop()` 对 reasoning-only 响应返回空回复错误，只写 `model.request.failed`，不会写 `model.output.completed` 或把私有 reasoning 落入 RunEvent。
- NativeRunEngine 执行预算新增直接回归：`max_run_duration_seconds` 过期后会在执行工具前中断 Run，返回结构化失败并避免继续消费工具调用；`budget` focused suite 同时覆盖模型/工具/terminal/output/context 预算。
- `terminal.run` ToolBroker 边界新增直接回归：
  - 未审批调用仍只返回 approval_required，不执行命令。
  - 审批后默认使用 argv 执行，`shell=False`，`cwd` 固定为配置 workspace。
  - 显式 shell 模式未审批时不会执行，会在 approval preview 中展示完整命令和 `shell=True`。
  - 敏感环境变量不会继承到子进程，包括 `SSH_AUTH_SOCK`、`GITHUB_TOKEN`、`AWS_*`、`GOOGLE_*`、`AZURE_*`、`*_API_KEY`、`*_PASSWORD`。
  - 子进程启动失败会返回结构化 `ok=false` terminal result，stderr 经过 redaction，不会把工具启动异常冒泡成 Runtime/Chat 崩溃。
  - timeout 会调用 process-group kill，并返回 `timed_out=True`。
  - stdout/stderr 中的 secret 会被 redaction 后再返回，且返回内容限制在 8000 字符以内。
- ToolBroker workspace boundary 新增 symlink 越界回归：
  - `workspace.read` 会拒绝指向 workspace 外文件的 symlink。
  - `workspace.list` 会拒绝指向 workspace 外目录的 symlink。
  - `workspace.write_patch` 即使审批通过，也会拒绝通过 symlink 写出 workspace，并保持外部文件内容不变。
- 主聊天上下文合同已显式化为常量并覆盖回归：
  - 最近历史消息上限 20 条。
  - 历史上下文字符上限 32,000。
  - 图片附件最多传递 4 张。
  - 当前 task 关联的 user/assistant 消息不会回灌进本轮模型上下文。
  - 图片附件以 `data:<mime>;base64,...` 形式传给 Native model message content。
- Bridge mutating endpoint token 合同新增覆盖：
  - Electron 生成 `bridgeSessionToken`，传入 backend 环境变量，并通过 preload 暴露给前端。
  - 前端 `apiPost` / `apiPatch` / `apiDelete` 自动携带 `X-Oha-Yachiyo-Bridge-Token`。
  - Python desktop backend 直接启动时，如果 token 未注入，会生成临时本地 token，使 mutating endpoint 仍进入 token 校验状态。
  - 当前已注册的所有 Bridge mutating routes 缺 token 时均会在 middleware 层返回 `invalid_bridge_token`。
  - `start_bridge()` / `restart_bridge()` 均拒绝非回环 host，且非法 restart 不会先停止现有 Bridge。
  - `POST /runs` 保持 `client_run_id` / `client_request_id` / `Idempotency-Key` 映射，并复用 NativeRunEngine runnable Run 创建路径。
  - `POST /ui/chat/messages` 保持 `client_message_id` / `Idempotency-Key` 映射。
  - `POST /ui/agent-runs` / `POST /ui/workflow-runs` 保持 `client_run_id` / `Idempotency-Key` 映射。
- Secret 持久化清洗新增覆盖：
  - `ChatStore.save_message()` 直接写入路径会清洗 content、error、attachments_json、metadata_json，并保留 transcript 换行。
  - `ChatStore.update_message_status()` 会清洗失败原因。
  - `ChatStore` 初始化会迁移清洗旧 `chat.db` 中的 message/session 敏感字段，并验证 SQLite 文件中不再包含测试 secret token。
  - `ChatSession.add_user_message()` / `upsert_assistant_message()` 在内存快照和持久化两侧都不保留明显 secret。
  - `RunEventRepository.append()` 对 payload key 为 `token` 但 value 不是 `sk-*` 形态的事件仍会按 key 清洗。
  - `ActivityStore` 共享 redactor 后，原 detail / metadata / tool_call 草稿清洗回归仍通过。
  - logging record factory 会清洗格式化后的日志消息和 exception traceback。
  - redacted `sys.excepthook` 会清洗未捕获异常输出。
  - `apps.desktop_backend.app._setup_logging()` 会安装 logging 与 excepthook 两条清洗防线。
  - API 错误 helper 会清洗字符串错误和嵌套 `HTTPException.detail`。
  - Bridge route `_bad_request()` helper、剪贴板错误 JSON、provider catalog 失败缓存均已有 secret redaction 回归。
  - `verify_secret_redaction()` 会扫描 runtime/log/cache/artifact 落盘文件，且不会把命中的 secret 原文打印到输出。
  - `ToolBroker.artifact_write()` 写出的 artifact 文件会先清洗明显 secret，并通过落盘扫描器回归。
  - 主聊天 provider exception 会以 redacted failure 写入 Run / RunEvent，落盘 DB 扫描不包含 raw secret。
  - 主聊天 tool exception 会以 redacted tool-result message 继续模型循环，Run / RunEvent / DB 扫描不包含 raw secret。
  - runtime scanner 对 SQLite 中相邻 redacted 字段的误报已补回归，同时保留真实 secret 命中。
  - redacted `sys.excepthook` 写出的 `.crash` 文件会通过 runtime scanner，不回写 raw exception secret。

### 功能保留状态

仍保留并通过测试覆盖的成熟功能入口：

- AppState、TaskRunner、Task API。
- ChatSession、Chat UI、多会话、任务消息投影。
- Agent Studio、Workflow、Run 记录、审批相关路径。
- ActivityStore。
- 主动关怀、本地截图、手动 TTS、GPT-SoVITS 服务管理、Live2D 资源导入。
- AstrBot 外部命令入口。

本轮没有删除成熟业务模块；改动集中在执行内核命名、协议字段和兼容入口清理。

### Workspace / Installer OHA identity 收敛

本轮继续清理安装、备份、卸载链路里的旧工作空间兼容入口：

- Workspace 初始化入口从 `YachiyoWorkspaceInitializer` / `initialize_yachiyo_workspace()` 收敛为 `OhaWorkspaceInitializer` / `initialize_oha_workspace()`。
- 初始化标记只写入并识别 `.oha_yachiyo_init`，配置标记只识别 `configs/oha-yachiyo.json`；不再把 `.yachiyo_init` 或 `configs/yachiyo.json` 当作有效 workspace 标记。
- 备份与恢复归档项从 `yachiyo_workspace` / `yachiyo-workspace` 收敛为 `oha_workspace` / `oha-workspace`。
- 卸载 scope 从 `yachiyo_only` 收敛为 `oha_only`，前端系统设置页也只提交 `oha_only`。
- workspace 安全删除判断只接受当前用户目录下的 `.oha-yachiyo`，并要求 OHA 初始化标记；不再把旧 `yachiyo` 目录视为有效 runtime workspace。
- Dashboard 读取 ActivityStore 失败时降级为空活动流，避免 activity SQLite 临时不可用导致整个主控台 payload 退化为错误响应。
- Bridge UI route 与 MainWindowAPI 的卸载默认 scope 均已改为 `oha_only`，避免未显式传参时重新提交旧 scope。
- Live2D runtime dependency cache 使用 `get_oha_workspace_dir()`，不再通过旧 workspace helper 命名进入 `.oha-yachiyo`。
- `.github` Copilot / prompt / instruction 文件已更新为 Oha-Yachiyo 与 Native Agent Runtime 语言，避免后续自动化代理继续按旧执行内核目标生成代码。

## 验证结果

已运行：

```text
.venv/bin/python -m pytest -q
```

结果：

```text
755 passed, 1 warning
```

已运行：

```text
.venv/bin/python scripts/app_version.py check
.venv/bin/python -m pytest -q tests/test_frontend_feature_preservation.py
.venv/bin/python -m pytest -q tests/test_frontend_feature_preservation.py tests/test_ui_bridge_routes.py tests/test_chat_api.py tests/test_agent_runtime.py -k "frontend_feature_preservation or native_agent_not_ready or model_profile_required or task_run_link or group_dispatch or group_main_model_dispatch or approval or workflow_resumes_after_child_agent_approval or linear_workflow_executes_agent_nodes_in_order"
.venv/bin/python -m pytest tests/test_screenshot.py tests/test_bridge_server.py::test_screen_current_http_route_returns_structured_permission_error tests/test_ui_bridge_routes.py::test_proactive_screen_permission_route_checks_real_capture tests/test_protocol.py::TestEnums::test_error_code_includes_key_codes -q
.venv/bin/python -m pytest -q tests/test_agent_runtime.py -k "approval_timeout or main_chat_model_loop_pauses_and_resumes_approved_tool"
.venv/bin/python -m pytest -q tests/test_executor.py -k "approval_resolution or approval_through_runtime_boundary"
.venv/bin/python -m pytest -q tests/test_agent_runtime.py -k "approval or cancel_workflow_waiting_for_child_approval or cancel_run"
.venv/bin/python -m pytest -q tests/test_chat_api.py -k "approval or cancel_current_tasks or cancelled_task"
.venv/bin/python -m pytest -q tests/test_executor.py -k "recent_chat_history or context_chars or image_attachments"
.venv/bin/python -m pytest tests/test_chat_api.py -k "desktop_snapshot or retry_failed_message_reuses_saved_image_attachments" -q
.venv/bin/python -m pytest -q tests/test_agent_runtime.py -k "budget"
.venv/bin/python -m pytest -q tests/test_desktop_backend_app.py
.venv/bin/python -m pytest -q tests/test_bridge_server.py
.venv/bin/python -m pytest -q tests/test_frontend_feature_preservation.py
.venv/bin/python -m pytest -q tests/test_agent_runtime.py -k "idempotency_key or client_run_id_is_idempotent"
.venv/bin/python -m pytest -q tests/test_ui_bridge_routes.py::test_chat_routes_use_shared_chat_api
python -m pytest tests/test_activity_store.py tests/test_chat_store.py tests/test_chat_session.py -q
python -m pytest tests/test_chat_store.py::TestChatStore::test_init_redacts_sensitive_legacy_rows_before_load -q
python -m pytest tests/test_security_logging.py -q
python -m pytest tests/test_secret_redaction_verifier.py tests/test_security_logging.py -q
python -m pytest tests/test_security_logging.py tests/test_secret_redaction_verifier.py -q
python -m pytest tests/test_provider_catalog_sync.py -q
python -m pytest tests/test_desktop_backend_app.py -q
python -m pytest tests/test_bridge_server.py -m "not asyncio" -q
python -m pytest tests/test_ui_bridge_routes.py::test_clipboard_route_redacts_secret_failure -q
python -m pytest tests/test_agent_runtime.py::test_artifact_write_redacts_file_content_and_passes_secret_scan -q
python -m pytest tests/test_secret_redaction_verifier.py tests/test_agent_runtime.py::test_main_chat_provider_exception_is_redacted_from_run_events_and_storage tests/test_agent_runtime.py::test_main_chat_tool_exception_is_redacted_from_tool_messages_events_and_storage -q
python -m pytest tests/test_secret_redaction_verifier.py tests/test_security_logging.py tests/test_agent_runtime.py::test_main_chat_provider_exception_is_redacted_from_run_events_and_storage tests/test_agent_runtime.py::test_main_chat_tool_exception_is_redacted_from_tool_messages_events_and_storage tests/test_agent_runtime.py::test_artifact_write_redacts_file_content_and_passes_secret_scan tests/test_agent_runtime.py::test_main_chat_model_loop_executes_native_tool_call tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_stream_chunks_before_persisting -q
python -m pytest tests/test_agent_runtime.py -k "redacts or redacted or secret or hide_internal" -q
python -m pytest tests/test_activity_store.py tests/test_chat_store.py tests/test_chat_session.py tests/test_agent_runtime.py -k "redacts or redacted or secret or hide_internal" -q
python -m pytest tests/test_bridge_server.py tests/test_desktop_backend_app.py tests/test_security_logging.py -m "not asyncio" -q
python -m pytest tests/test_bridge_server.py tests/test_desktop_backend_app.py tests/test_security_logging.py tests/test_provider_catalog_sync.py -m "not asyncio" -q
python -m pytest tests/test_desktop_backend_app.py tests/test_bridge_server.py tests/test_secret_redaction_verifier.py -m "not asyncio" -q
python -m pytest tests/test_ui_mature_flow_contract.py tests/test_frontend_feature_preservation.py tests/test_ui_bridge_routes.py::test_clipboard_route_redacts_secret_failure -q
Browser Chat readiness E2E via in-app Browser against source frontend preview and localhost-only source Bridge
Browser Chat fake-model E2E via in-app Browser against source frontend preview, localhost-only source Bridge, and local OpenAI-compatible fake model
Source Bridge Chat image E2E via /ui/chat/messages + local OpenAI-compatible fake model + /runs/{run_id}/events
Source Bridge Chat approval E2E via /ui/chat/messages + /ui/runs/{run_id}/approval/approve + workspace.write_patch + /runs/{run_id}/events
Browser Chat image/approval button-level E2E attempted against isolated fake model + Bridge + Vite dev server; blocked by in-app Browser net::ERR_BLOCKED_BY_CLIENT and missing agent-browser CLI
.venv/bin/python -m pytest tests/test_frontend_feature_preservation.py -q
python scripts/verify_secret_redaction.py /tmp/oha-yachiyo-browser-model-e2e.*/data
python -m pytest tests/test_agent_runtime.py::test_main_chat_cancelled_run_ignores_late_model_output tests/test_agent_runtime.py::test_main_chat_run_links_task_and_records_replayable_events -q
python -m pytest tests/test_chat_api.py::test_running_main_chat_task_projects_native_tool_approval tests/test_chat_api.py::test_running_main_chat_task_clears_approval_projection_after_resume -q
.venv/bin/python -m pytest tests/test_task_runner.py::test_task_runner_main_chat_native_tool_approval_roundtrip tests/test_chat_api.py::test_running_main_chat_task_projects_native_tool_approval tests/test_chat_api.py::test_running_main_chat_task_clears_approval_projection_after_resume -q
python -m pytest tests/test_chat_api.py -k "approval or cancel_current_tasks or cancelled_task" -q
python -m pytest tests/test_ui_mature_flow_contract.py tests/test_frontend_feature_preservation.py -q
.venv/bin/python -m pytest tests/test_task_runner.py::test_task_runner_main_chat_native_tool_approval_roundtrip -q
.venv/bin/python -m pytest tests/test_task_runner.py -q
.venv/bin/python -m pytest tests/test_executor.py -k "approval_resolution or approval_through_runtime_boundary or recent_chat_history or context_chars or image_attachments" -q
python -m pytest tests/test_runtime.py::test_main_chat_runtime_policies_enable_native_tools_with_approval tests/test_runtime.py::test_switch_session_syncs_executor_via_public_method -q
.venv/bin/python -m pytest tests/test_executor.py::TestNativeAgentExecutor::test_select_executor_uses_native_when_ready tests/test_executor.py -k "approval_resolution or approval_through_runtime_boundary" -q
python -m pytest tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice -q
python -m pytest tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution -q
python -m pytest tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution -q
python -m pytest tests/test_agent_runtime.py -k "main_chat_repeated_approval or durable_approval_claim or approval_timeout or main_chat_model_loop_pauses_and_resumes_approved_tool or pauses_for_terminal_approval_and_resumes" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_runtime_migrates_legacy_runs_before_index_creation tests/test_agent_runtime.py::test_runtime_sqlite_enables_required_database_guards tests/test_agent_runtime.py::test_main_chat_run_links_task_and_records_replayable_events tests/test_agent_runtime.py::test_run_events_route_paginates_user_visible_events tests/test_agent_runtime.py::test_run_events_route_returns_404_for_missing_run -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_runtime_shutdown_cancels_active_runs_rejects_new_runs_and_records_fact tests/test_agent_runtime.py::test_runtime_shutdown_close_db_closes_runtime_resources -q
.venv/bin/python -m pytest tests/test_bridge_server.py::test_run_events_http_route_paginates_and_hides_non_user_events tests/test_bridge_server.py::test_bridge_http_middleware_enforces_host_origin_and_session_token tests/test_bridge_server.py::test_chat_message_http_route_maps_idempotency_key_header tests/test_bridge_server.py::test_agent_and_workflow_run_http_routes_map_idempotency_key_header -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_tool_broker_blocks_out_of_scope_and_unapproved_terminal tests/test_agent_runtime.py::test_terminal_run_defaults_to_argv_and_requires_explicit_shell tests/test_agent_runtime.py::test_terminal_run_shell_mode_requires_approval_and_shows_full_command tests/test_agent_runtime.py::test_terminal_run_uses_workspace_argv_and_scrubbed_environment tests/test_agent_runtime.py::test_terminal_run_startup_failure_returns_structured_sanitized_error tests/test_agent_runtime.py::test_terminal_run_truncates_and_sanitizes_outputs tests/test_agent_runtime.py::test_terminal_run_timeout_kills_process_group -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_tool_broker_rejects_symlink_workspace_escape tests/test_agent_runtime.py::test_tool_broker_blocks_out_of_scope_and_unapproved_terminal -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "terminal_run or tool_broker or workspace_write_patch" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_agent_run_validates_write_patch_workspace_boundary_before_approval tests/test_agent_runtime.py::test_main_chat_model_loop_pauses_and_resumes_approved_tool tests/test_agent_runtime.py::test_agent_run_pauses_for_terminal_approval_and_resumes tests/test_agent_runtime.py::test_tool_broker_blocks_out_of_scope_and_unapproved_terminal -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_tool_descriptor_schema_and_validation_share_patch_contract tests/test_agent_runtime.py::test_main_chat_model_loop_pauses_and_resumes_approved_tool tests/test_agent_runtime.py::test_main_chat_approval_timeout_records_replayable_fact_and_is_idempotent tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution tests/test_agent_runtime.py::test_agent_run_skips_write_tool_when_user_goal_forbids_file_changes tests/test_agent_runtime.py::test_model_payload_approved_flag_is_rejected_by_tool_schema tests/test_agent_runtime.py::test_tool_broker_blocks_out_of_scope_and_unapproved_terminal tests/test_agent_runtime.py::test_tool_broker_rejects_symlink_workspace_escape tests/test_agent_runtime.py::test_workspace_write_patch_applies_single_file_unified_diff_with_hash tests/test_agent_runtime.py::test_workspace_write_patch_rejects_hash_or_context_mismatch_without_writing tests/test_agent_runtime.py::test_workspace_write_patch_rejects_multifile_or_binary_patch tests/test_task_runner.py::test_task_runner_main_chat_native_tool_approval_roundtrip -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "run_approval_routes_return_404_and_are_idempotent or workflow_resumes_after_child_agent_approval" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_run_approval_routes_return_404_and_are_idempotent tests/test_agent_runtime.py::test_run_approval_reject_route_is_idempotent -q
.venv/bin/python -m pytest tests/test_task_runner.py::test_task_runner_main_chat_image_attachment_reaches_native_model -q
.venv/bin/python -m pytest tests/test_task_runner.py -q
.venv/bin/python -m pytest tests/test_task_runner.py::test_task_runner_main_chat_auto_delegation_uses_native_runtime -q
.venv/bin/python -m pytest tests/test_executor.py::TestNativeAgentExecutor::test_run_delegates_oha_agent_before_final_reply tests/test_executor.py::TestNativeAgentExecutor::test_group_mode_returns_dispatch_for_chat_layer tests/test_executor.py::TestExecutorHelpers::test_run_oha_delegation_accepts_structured_directive tests/test_agent_runtime.py::test_delegation_targets_and_delegate_run -q
.venv/bin/python -m pytest tests/test_executor.py -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "run_events_route_paginates_user_visible_events or run_events_route_returns_404_for_missing_run" -q
.venv/bin/python -m pytest tests/test_executor.py -k "image_attachments or context_chars" -q
.venv/bin/python -m pytest tests/test_chat_api.py -k "desktop_snapshot or retry_failed_message_reuses_saved_image_attachments" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_workflow_approval_node_pauses_and_resumes tests/test_agent_runtime.py::test_workflow_child_approval_route_approve_resumes_parent_workflow -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "workflow_approval_node_pauses_and_resumes or workflow_child_approval_route_approve_resumes_parent_workflow or workflow_resumes_after_child_agent_approval or workflow_child_consecutive_approvals_keep_parent_waiting or workflow_child_approval_route_reject_cancels_parent_workflow" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_workflow_artifact_review_route_exposes_outputs_and_reruns -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "workflow_artifact_review_route_exposes_outputs_and_reruns or workflow_approval_node_pauses_and_resumes or workflow_child_approval_route_approve_resumes_parent_workflow or workflow_resumes_after_child_agent_approval or workflow_child_consecutive_approvals_keep_parent_waiting or workflow_child_approval_route_reject_cancels_parent_workflow or run_events_route_paginates_user_visible_events or run_events_route_returns_404_for_missing_run" -q
.venv/bin/python -m pytest tests/test_chat_api.py -k "group_dispatch" -q
.venv/bin/python -m pytest tests/test_executor.py -k "delegation or group_dispatch" -q
.venv/bin/python -m pytest tests/test_chat_api.py::test_summarize_delegated_run_creates_main_followup_task tests/test_chat_api.py::test_group_main_model_dispatch_accepts_model_field_variants -q
.venv/bin/python -m pytest tests/test_executor.py tests/test_chat_api.py -k "delegation or group_dispatch or summarize_delegated_run_creates_main_followup_task or group_main_model_dispatch_accepts_model_field_variants" -q
.venv/bin/python -m pytest tests/test_chat_api.py::test_group_dispatch_parser_exposes_structured_directives_and_legacy_requests -q
.venv/bin/python -m pytest tests/test_chat_api.py::test_group_dispatch_uses_runtime_native_service_end_to_end -q
.venv/bin/python -m pytest tests/test_chat_api.py::test_agent_mention_creates_agent_run_without_general_task tests/test_chat_api.py::test_agent_scoped_session_continues_without_new_mention tests/test_chat_api.py::test_workflow_mention_creates_workflow_run_from_chat tests/test_chat_api.py::test_plain_group_goal_approval_flow_continues_to_main_summary tests/test_chat_api.py::test_group_dispatch_uses_runtime_native_service_end_to_end tests/test_chat_api.py::test_group_agent_approval_completion_creates_main_summary tests/test_chat_api.py::test_summarize_delegated_run_creates_main_followup_task -q
.venv/bin/python -m pytest tests/test_chat_api.py -k "group_dispatch or group_agent or group_main_model_dispatch or summarize_delegated_run" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "skill and not workflow" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_skill_install_command_runs_whitelisted_npx_and_syncs tests/test_agent_runtime.py::test_terminal_run_uses_workspace_argv_and_scrubbed_environment tests/test_agent_runtime.py::test_runtime_shutdown_cancels_active_runs_rejects_new_runs_and_records_fact -q
.venv/bin/python -m pytest tests/test_runtime.py::test_stop_closes_injected_native_runtime_service tests/test_runtime.py::test_start_does_not_require_native_agent_readiness -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_builtin_yachiyo_main_is_virtual_system_agent_not_delegation_target tests/test_agent_runtime.py -k "listing_agents or listing_runnables or agent_studio_reads or seed_templates or deleted_seed_templates or create_agent_rejects_legacy_backend or resolve_runnable or delegation_targets or builtin_yachiyo" tests/test_frontend_feature_preservation.py::test_agent_studio_preserves_workflow_run_detail_and_approval_paths -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_create_run_for_runnable_propagates_client_run_id tests/test_agent_runtime.py::test_post_runs_route_maps_idempotency_key_to_runnable_run tests/test_bridge_server.py::test_post_runs_http_route_maps_idempotency_key tests/test_bridge_server.py::test_all_registered_mutating_routes_require_bridge_token -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_concurrent_cancel_run_is_idempotent tests/test_agent_runtime.py::test_runtime_shutdown_cancels_active_runs_rejects_new_runs_and_records_fact tests/test_agent_runtime.py::test_workflow_cancel_route_cancels_child_agent_approval tests/test_bridge_server.py::test_run_cancel_route_handler_is_idempotent -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "cancel_run or cancelled_run_ignores_late_model_output or approval_timeout or workflow_cancel_route_cancels_child_agent_approval or cancel_workflow_waiting_for_child_approval" -q
./apps/frontend/node_modules/.bin/tsc -b apps/frontend/tsconfig.json --pretty false
rg -n 'yachiyo_group_dispatch|<yachiyo_group_dispatch|yachiyo\.group_dispatch|_yachiyo_group_dispatch_context' apps integrations packages scripts pyproject.toml --glob '!apps/frontend/dist/**' --glob '!apps/frontend/dist-electron/**' --glob '!**/__pycache__/**' --glob '!node_modules/**'  # expected no matches
rg -n 'yachiyo_delegation|run_yachiyo|runyachiyo|_yachiyo_delegation|yachiyo\.delegation|_append_yachiyo_delegation|_parse_yachiyo_delegation|_run_yachiyo_delegation|_format_yachiyo_delegation' apps integrations packages scripts pyproject.toml --glob '!apps/frontend/dist/**' --glob '!apps/frontend/dist-electron/**' --glob '!**/__pycache__/**' --glob '!node_modules/**'  # expected no matches
Bridge cancel late-output smoke with slow fake model:
  POST /ui/chat/messages
  POST /ui/chat/session/cancel
  GET /ui/runs
  GET /runs/{run_id}/events?after_sequence=0&limit=200
python -m pytest tests/test_chat_api.py tests/test_main_api_modes.py -q
python -m pytest tests/test_agent_runtime.py -k "not route and not workflow and not skill" -q
python -m pytest tests/test_executor.py -m "not asyncio" -q
python -m compileall packages/security apps/desktop_backend/app.py
python -m compileall packages/security scripts/verify_secret_redaction.py tests/test_agent_runtime.py tests/test_secret_redaction_verifier.py
python -m compileall packages/security apps/bridge/server.py apps/bridge/routes/agents.py apps/bridge/routes/model_profiles.py apps/bridge/routes/ui.py apps/bridge/routes/tasks.py apps/shell/provider_catalog_sync.py apps/shell/chat_api.py apps/shell/chat_bridge.py apps/shell/main_api.py apps/shell/tts.py apps/shell/gpt_sovits_service.py apps/shell/tts_resources.py apps/shell/live2d_resources.py apps/shell/mode_settings.py apps/shell/terminal.py apps/shell/model_profiles.py apps/shell/agent_runtime.py apps/core/executor.py
python -m compileall tests/test_ui_mature_flow_contract.py apps/bridge/routes/ui.py apps/bridge/routes/agents.py
.venv/bin/python -m compileall apps/shell/agent_runtime.py tests/test_agent_runtime.py tests/test_task_runner.py
.venv/bin/python -m compileall apps/shell/chat_api.py apps/core/executor.py tests/test_chat_api.py tests/test_executor.py
.venv/bin/python -m compileall apps/shell/agent_runtime.py apps/shell/chat_api.py apps/core/executor.py tests/test_agent_runtime.py tests/test_chat_api.py tests/test_executor.py
.venv/bin/python -c "import apps.desktop_backend.app, apps.bridge.server, apps.shell.agent_runtime; print('backend imports ok')"
.venv/bin/python -c "import apps.core.executor, apps.shell.chat_api; print('chat dispatch imports ok')"
.venv/bin/python -c "import apps.shell.agent_runtime, apps.shell.chat_api, apps.core.executor; print('runtime imports ok')"
npm --prefix apps/frontend run build
git diff --check
.venv/bin/python -m pytest tests/test_uninstall.py tests/test_main_api_modes.py -q
.venv/bin/python -m compileall apps/shell/main_api.py apps/installer/workspace_init.py apps/installer/backup.py apps/installer/uninstall.py tests/test_uninstall.py tests/test_main_api_modes.py
.venv/bin/python -c "import apps.desktop_backend.app; import apps.shell.main_api; import apps.installer.workspace_init; import apps.installer.backup; import apps.installer.uninstall; print('backend imports ok')"
npm --prefix apps/frontend run build
git diff --check
.venv/bin/python -m compileall apps/bridge/routes/ui.py apps/shell/main_api.py apps/shell/assets.py apps/shell/live2d_runtime.py tests/test_ui_bridge_routes.py
.venv/bin/python -m pytest tests/test_ui_bridge_routes.py tests/test_main_api_modes.py tests/test_uninstall.py -q
.venv/bin/python -m pytest tests/test_ui_bridge_routes.py tests/test_ui_mature_flow_contract.py -q
.venv/bin/python -m pytest tests/test_ui_bridge_routes.py::test_chat_routes_use_shared_chat_api tests/test_ui_mature_flow_contract.py -q
.venv/bin/python -m pytest tests/test_ui_mature_flow_contract.py tests/test_bridge_server.py::test_agent_and_workflow_run_http_routes_map_idempotency_key_header -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "workflow_artifact_review_route_exposes_outputs_and_reruns or workflow_child_artifact_route_reads_source_run_artifact or run_approval_routes_return_404_and_are_idempotent" -q
.venv/bin/python -m pytest tests/test_ui_mature_flow_contract.py tests/test_ui_bridge_routes.py::test_proactive_screen_permission_route_checks_real_capture tests/test_ui_bridge_routes.py::test_proactive_tts_test_route_invokes_sync_service tests/test_ui_bridge_routes.py::test_proactive_tts_status_route_returns_last_launcher_status tests/test_ui_bridge_routes.py::test_launcher_live2d_payload_includes_preview_and_renderer tests/test_ui_bridge_routes.py::test_live2d_prepare_model_path_route_returns_draft tests/test_ui_bridge_routes.py::test_live2d_import_archive_route_returns_draft -q
.venv/bin/python -m pytest tests/test_screenshot.py tests/test_tts.py -q
.venv/bin/python -m compileall tests/test_ui_mature_flow_contract.py apps/bridge/routes/ui.py apps/bridge/routes/screen.py
.venv/bin/python -m pytest tests/test_activity_store.py tests/test_ui_bridge_routes.py::test_activity_route_forwards_filters -q
.venv/bin/python -m compileall tests/test_ui_mature_flow_contract.py apps/bridge/routes/ui.py apps/shell/activity_api.py apps/core/activity_store.py
.venv/bin/python -m compileall tests/conftest.py tests/test_ui_mature_flow_contract.py apps/bridge/routes/ui.py
.venv/bin/python -m pytest tests/test_chat_api.py -k "retry_failed_message_reuses_saved_image_attachments or desktop_snapshot" -q
.venv/bin/python -m pytest tests/test_task_runner.py::test_task_runner_main_chat_image_attachment_reaches_native_model -q
.venv/bin/python -c "from apps.shell.assets import get_oha_workspace_dir, get_user_live2d_assets_dir; import apps.shell.live2d_runtime; import apps.bridge.routes.ui; print('oha assets imports ok', get_oha_workspace_dir().name, bool(get_user_live2d_assets_dir()))"
rg -n 'Hermes|hermes|HERMES' apps integrations packages scripts pyproject.toml .github --glob '!apps/frontend/dist/**' --glob '!apps/frontend/dist-electron/**' --glob '!**/__pycache__/**' --glob '!node_modules/**' --glob '!docs/**' --glob '!apps/shell/assets/live2d/**'  # expected no matches
rg -n 'yachiyo_only|YACHIYO_ONLY|include_hermes|INCLUDE_HERMES|hermes_home|Hermes Home|Hermes Agent|Hermes-Yachiyo|hermes-yachiyo|HERMES_YACHIYO|/ui/hermes|hermes/install|hermes/status|hermes/config|get_yachiyo_workspace_dir|yachiyo_workspace|yachiyo-workspace|\.yachiyo_init|configs/yachiyo\.json|run_yachiyo|yachiyo_delegation|yachiyo_group_dispatch|can_use_as_hermes|hermes_provider|syncHermes' apps integrations packages scripts pyproject.toml .github --glob '!apps/frontend/dist/**' --glob '!apps/frontend/dist-electron/**' --glob '!**/__pycache__/**' --glob '!node_modules/**' --glob '!docs/**' --glob '!apps/shell/assets/live2d/**'  # expected no matches
python scripts/verify_secret_redaction.py
python scripts/verify_secret_redaction.py <clean-temp-runtime-dir>
python scripts/verify_secret_redaction.py <leaky-temp-runtime-dir>  # expected exit 1; output verified not to contain raw secret
python - <<'PY'
import packages.security
import apps.desktop_backend.app
print('security logging import ok')
PY
python - <<'PY'
from apps.bridge.server import _register_routes, app
_register_routes()
print('routes registered', len(getattr(app, 'routes', [])))
PY
python - <<'PY'
from apps.desktop_backend import app as desktop_app
from apps.bridge import server
from apps.bridge.routes import agents, model_profiles, ui, tasks
from packages.security import redact_api_error_text
print('desktop/bridge import ok', bool(desktop_app), bool(server.app), redact_api_error_text('token=import-secret-123456'))
PY
python -m compileall apps/core/chat_store.py
python - <<'PY'
from apps.core.chat_store import ChatStore
print('chat_store import ok')
PY
python -m compileall packages/security apps/core/activity_store.py apps/core/chat_store.py apps/core/chat_session.py apps/shell/agent_runtime.py
python - <<'PY'
import apps.core.chat_session
import apps.core.chat_store
import apps.core.activity_store
import apps.shell.agent_runtime
print('import ok')
PY
.venv/bin/python -m pytest -q tests/test_ui_bridge_routes.py tests/test_chat_api.py tests/test_agent_runtime.py -k "group_dispatch or group_main_model_dispatch or group_agent or approval or workflow_resumes_after_child_agent_approval or linear_workflow_executes_agent_nodes_in_order"
.venv/bin/python -m pytest -q tests/test_protocol.py tests/test_bridge_server.py tests/test_main_api_modes.py tests/test_astrbot_handlers.py
.venv/bin/python - <<'PY'
from apps.bridge.server import _register_routes, app
_register_routes()
print('routes registered', len(app.routes))
PY
.venv/bin/python scripts/verify_release_artifacts.py
.venv/bin/python -m pytest tests/test_release_artifact_verifier.py tests/test_build_backend.py tests/test_build_metadata.py tests/test_credential_store.py tests/test_bridge_server.py tests/test_agent_runtime.py
.venv/bin/python -m pytest tests/test_model_profiles.py tests/test_credential_store.py -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "api_key_redaction or legacy_agent_model_api_key_migration or budget" -q
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "main_chat_model_persists_batched_output_event_not_token_deltas or main_chat_model_loop_coalesces_stream_chunks_before_persisting or main_chat_model_loop_coalesces_openai_sdk_object_stream_before_persisting or main_chat_model_loop_coalesces_streaming_tool_call_deltas or main_chat_model_loop_executes_native_tool_call or main_chat_run_links_task_and_records_replayable_events"
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "run_events"
.venv/bin/python -m pytest tests/test_chat_api.py -k "group_dispatch or group_main_model_dispatch or group_agent"
.venv/bin/python -m pytest tests/test_chat_api.py
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "main_chat_model_loop_pauses_and_resumes_approved_tool or pauses_for_terminal_approval_and_resumes or consecutive_terminal_approvals or approved_terminal_returns_nonzero or workflow_resumes_after_child_agent_approval"
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "workflow_resumes_after_child_agent_approval or workflow_fails_when_child_terminal_returns_nonzero_after_approval or workflow_resume_failure_keeps_child_node_context or workflow_approval_node_pauses_and_resumes"
.venv/bin/python -m pytest tests/test_agent_runtime.py -k "linear_workflow_executes_agent_nodes_in_order or workflow_approval_node_pauses_and_resumes or workflow_resumes_after_child_agent_approval or workflow_fails_when_child_terminal_returns_nonzero_after_approval or workflow_resume_failure_keeps_child_node_context"
.venv/bin/python -m pytest tests/test_agent_runtime.py
.venv/bin/python -m pytest -q tests/test_executor.py
```

结果：

```text
0.4.0
4 passed
66 passed, 231 deselected
3 passed, 27 deselected
2 passed, 126 deselected
2 passed, 32 deselected
21 passed, 107 deselected
21 passed, 122 deselected
3 passed, 34 deselected
9 passed, 134 deselected
4 passed, 124 deselected
6 passed
19 passed
5 passed
2 passed, 126 deselected
1 passed
64 passed
1 passed
6 passed
11 passed
12 passed
5 passed
6 passed
18 passed, 1 skipped, 2 deselected, 2 warnings
1 passed, 20 warnings
1 passed, 17 warnings
7 passed, 17 warnings
16 passed, 17 warnings
3 passed, 125 deselected, 17 warnings
9 passed, 184 deselected, 17 warnings
27 passed, 2 deselected, 2 warnings
35 passed, 1 skipped, 2 deselected, 2 warnings
29 passed, 1 skipped, 2 deselected, 2 warnings
8 passed, 20 warnings
Chat route loaded in Browser; no console errors; missing-model UI readiness shown; direct POST returned native_agent_not_ready/model_profile_required
Chat route loaded in Browser with NativeAgentExecutor; user message submitted; fake model reply projected; Run completed; RunEvent replay returned run.started/task.linked/model.request.started/model.output.completed/run.completed
secret redaction verification passed
2 passed, 17 warnings
2 passed
23 passed, 122 deselected
7 passed
1 passed
3 passed
5 passed, 32 deselected
2 passed
2 passed, 35 deselected
1 passed, 17 warnings
1 passed, 17 warnings
2 passed, 17 warnings
5 passed, 129 deselected, 17 warnings
2 passed, 132 deselected
1 passed
4 passed
2 passed, 132 deselected
2 passed, 35 deselected
9 passed, 136 deselected
2 passed
5 passed, 129 deselected
Chat cancel returned cancelled_tasks=1; after slow model returned Run stayed cancelled; RunEvent replay ended at run.cancelled and did not contain model.output.completed
169 passed
59 passed, 69 deselected, 17 warnings
25 passed, 12 deselected, 12 warnings
compileall security logging passed
compileall secret redaction verifier and focused tests passed
secret redaction verification passed
clean temp runtime scan passed
leaky temp runtime scan failed as expected without printing raw secret
compileall API error redaction boundary passed
compileall UI mature flow contract passed
security logging import ok
routes registered 144
desktop/bridge import ok True True token=[redacted]
compileall chat_store passed
chat_store import ok
compileall passed
import ok
74 passed, 219 deselected
98 passed
routes registered 144
release artifact verification passed
154 passed
4 passed, 122 deselected
3 passed, 124 deselected
45 passed, 98 deselected
143 passed
5 passed, 120 deselected
4 passed, 121 deselected
5 passed, 120 deselected
128 passed
34 passed
```

验证环境注意：`tests/test_executor.py` 中的 NativeAgentExecutor 回归是 async pytest，用项目 `.venv/bin/python` 跑可正常加载 `pytest_asyncio`。系统 `python` 未安装该插件时会把这些用例报告为 “async def functions are not natively supported”，这不是业务回归。

已运行：

```text
cd apps/frontend && npm run build
npm --prefix apps/frontend run build
.venv/bin/python -m pip install -e ".[packaging]"
.venv/bin/python scripts/build_backend.py --clean
CSC_IDENTITY_AUTO_DISCOVERY=false npm --prefix apps/frontend run dist:mac
```

结果：

```text
tsc -b && vite build && tsc -p tsconfig.electron.json passed
frontend build passed
dist/backend/oha-yachiyo-backend built
dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg built
```

已运行：

```text
Standalone packaged backend smoke:
OHA_YACHIYO_BRIDGE_URL=http://127.0.0.1:18420
OHA_YACHIYO_BRIDGE_TOKEN=backend-smoke-token
dist/backend/oha-yachiyo-backend

Packaged desktop smoke:
OHA_YACHIYO_BRIDGE_URL=http://127.0.0.1:18420
OHA_YACHIYO_BRIDGE_TOKEN=packaged-smoke-token
dist/electron/mac-arm64/Oha-Yachiyo.app/Contents/MacOS/Oha-Yachiyo
```

结果：

```text
standalone backend: /status service=oha-yachiyo, version=0.4.0, listener=127.0.0.1:18420
packaged desktop: /status service=oha-yachiyo, version=0.4.0, listener=127.0.0.1:18420
```

已运行：

```text
git diff --check
```

结果：

```text
passed
```

当前 shell Python 缺少 `pytest_asyncio`：

```text
pytest_asyncio unavailable: ModuleNotFoundError: No module named 'pytest_asyncio'
```

因此本轮直接运行 `python -m pytest tests/test_agent_runtime.py -q` 和 `python -m pytest tests/test_executor.py -q` 时，失败集中在 `@pytest.mark.asyncio` 用例，错误为 `async def functions are not natively supported`。同步路径、focused redaction、Chat API、Main API 和 Store 回归均已通过；报告中较早的 `.venv/bin/python -m pytest` 全量结果保留为当时环境的历史验证记录。

已运行：

```text
backend import smoke
```

结果：

```text
backend import smoke ok
```

已运行：

```text
rg -n "Hermes-Yachiyo|Hermes|hermes-yachiyo|hermes|HERMES" apps integrations packages scripts pyproject.toml --glob '!apps/frontend/dist/**' --glob '!apps/frontend/dist-electron/**' --glob '!**/__pycache__/**' --glob '!node_modules/**'
rg -n "Hermes-Yachiyo|Hermes|hermes-yachiyo|hermes|HERMES" .github/workflows/release-macos.yml .github/workflows/release-tts-assets.yml docs/release-packaging.md apps/frontend/electron-builder.yml scripts/build_backend.py apps/frontend/public/oha-yachiyo-build.json
rg -n "Hermes-Yachiyo|Hermes|hermes-yachiyo|hermes|HERMES" /tmp/oha-yachiyo-app-asar-scan --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/.vite/**'
rg -a -o "Hermes-Yachiyo|hermes-yachiyo|HERMES_YACHIYO|hermes_yachiyo" dist/backend/oha-yachiyo-backend dist/electron/mac-arm64/Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg.blockmap
plutil -p dist/electron/mac-arm64/Oha-Yachiyo.app/Contents/Info.plist
```

结果：

```text
0 matches
0 matches
0 matches in extracted app.asar
0 matches for legacy product identity tokens in backend binary, packaged backend, DMG, and blockmap
Info.plist uses Oha-Yachiyo identifiers and permission strings
```

### OpenAI-compatible SSE content-part replay

本轮补一条更接近真实 provider 差异的 NativeRunEngine 回归：fake HTTP provider 的 SSE stream 可以在 `choices[].delta.content` / `choices[].message.content` 中返回 OpenAI-compatible content-part 数组，Runtime 仍会合并为单条可见 `model.output.completed` RunEvent，不写 token/delta 级事实；后续又加固了 content-part `text.value` 对象形态，避免真实网关把文本包成对象时被字符串化为 dict。

随后检查真实 provider smoke 环境变量，`OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL`、`OHA_YACHIYO_SMOKE_API_KEY` 均未设置，因此本轮未进行外部 provider 调用。作为可重复替代，补充 smoke helper contract：`scripts/smoke_openai_compatible_stream.py` 能接受同样的 content-part array stream，并在 `--require-content` / `--expect-finish-reason` 下正确统计内容长度而不打印原文；后续也已覆盖 content-part 数组中的 `reasoning` / `thinking` 私有片段只计入 reasoning 长度、不进入可见 content、`text.value` 对象形态，以及 message-level streaming tool call 的 object arguments 形态。

已运行：

```text
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_main_chat_model_consumes_openai_compatible_sse_content_parts -q
.venv/bin/python -m pytest tests/test_streaming_provider_smoke.py::test_stream_smoke_accepts_content_part_arrays -q
```

结果：

```text
1 passed
1 passed
```

### OpenAI-compatible SSE provider error event frames

本轮继续补更接近真实 provider / 网关差异的 streaming 错误帧合同：

- `_openai_compatible_sse_event_payload()` 现在会保留 SSE `event:` 字段。
- `event: error` + `data: {"message": "...", "code": "..."}` 会进入同一 `ModelProfileError` 路径。
- 顶层 `data: {"type": "error", "message": "...", "code": "..."}` 也会被识别为 provider stream error。
- 错误详情继续通过 `redact_api_error_text()` 清洗，测试确认 `sk-...` API key 不会进入异常文本。
- 既有 `data: {"error": {...}}`、multiline data、split UTF-8 和 smoke helper 汇总测试仍通过。

已运行：

```text
pytest tests/test_model_profiles.py::test_openai_compatible_chat_message_stream_raises_provider_error tests/test_model_profiles.py::test_openai_compatible_chat_message_stream_raises_provider_error_event tests/test_model_profiles.py::test_openai_compatible_chat_message_streams_multiline_sse_data_event tests/test_model_profiles.py::test_openai_compatible_chat_message_streams_split_utf8_sse_frame_chunks
pytest tests/test_streaming_provider_smoke.py
python -m compileall apps/shell/model_profiles.py scripts/smoke_openai_compatible_stream.py
```

结果：

```text
5 passed
18 passed
compileall passed
```

### Approval secret payload guards

本轮补审批 UI 前置清洗回归：主聊天模型请求 `terminal.run`，且命令参数里包含 API key / token 形态的敏感值时，NativeRunEngine 会在生成 `pending_approval` 之前拒绝该工具请求；同样，主聊天模型请求 `workspace.write_patch` 且 patch diff 会写入 API key / token 形态敏感值时，也会在生成审批卡之前拒绝。Run 进入 failed，`run_approvals` 不创建记录，`agent.tool.approval_required` 不写入 replay，Run projection / RunEvent / SQLite 扫描都不能看到原始 secret 或原始 `OPENAI_API_KEY` 命令/patch 片段，目标工作区文件不会被修改。

同类 artifact 写入路径也补了主聊天工具循环回归：模型请求 `artifact.write` 且 content 含 API key / token 形态敏感值时，Runtime 在 ToolDescriptor validation 阶段拒绝，不创建 artifact 文件、不追加 `agent.tool.call` fact，Run / RunEvent / SQLite 扫描不含原始 secret 或 `api_key=` 片段。

已运行：

```text
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_main_chat_terminal_secret_payload_is_rejected_before_approval -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_main_chat_workspace_patch_secret_payload_is_rejected_before_approval -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_main_chat_artifact_secret_payload_is_rejected_before_write -q
```

结果：

```text
1 passed
1 passed
1 passed
```

### Approved terminal failure output redaction

本轮补 NativeRunEngine 审批恢复后的 terminal 失败清洗回归：custom_api Agent 请求 `terminal.run`，用户批准后命令以非零退出，并在 stdout / stderr 真实打印 API key / Authorization bearer 形态敏感值。Runtime 会将 Run 标记为 failed，但 Run projection、`agent.tool.call` RunEvent、`agent.tool.failed` timeline 和 raw SQLite 扫描都只能看到 redacted 输出，不保留原始 stdout / stderr secret。

这条覆盖的是 ToolBroker 低层 stdout/stderr 清洗与 ApprovalResumeCoordinator fatal tool failure 路径的组合，防止“工具返回值已清洗，但失败摘要或 replay 重新落下原文”的回归。

已运行：

```text
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_agent_run_redacts_approved_terminal_failure_output_from_projection_and_storage -q
.venv/bin/python -m pytest tests/test_agent_runtime.py::test_agent_run_fails_when_approved_terminal_returns_nonzero tests/test_agent_runtime.py::test_agent_run_redacts_approved_terminal_failure_output_from_projection_and_storage tests/test_agent_runtime.py::test_workflow_fails_when_child_terminal_returns_nonzero_after_approval tests/test_agent_runtime.py::test_terminal_run_truncates_and_sanitizes_outputs -q
```

结果：

```text
1 passed
4 passed
```

## 设计书差距

### 已基本满足

- 不再把 Hermes 作为默认或回退执行路径。
- 成熟业务层没有被删除或 Run-only 重写。
- `NativeAgentExecutor` 维护 Task 到 Run 的映射。
- `NativeRunEngine` 承载模型、RunEvent、工具、审批、取消和预算。
- Hermes 执行内核入口已有源码级 guard：`apps` / `integrations` / `packages` / `scripts` / `pyproject.toml` 不得重新出现 `HermesExecutor`、Hermes CLI/stream/installer/readiness、`hermes_profile`、旧 `run_yachiyo*` / `yachiyo_delegation` / `yachiyo_group_dispatch` 和旧 workspace/product token。
- `builtin:yachiyo-main` 已作为系统虚拟 Agent 暴露给 Runtime / Agent Studio 读取面，使用默认 Chat ModelProfile，不落普通 agents 表，不可作为普通 Agent 创建、修改或删除，并被排除出自动委派目标。
- RunRepository、RunGroupRepository、RunEvent、approval projection、ApprovalCoordinator、ApprovalResumeCoordinator、ApprovalResumeProjectionCoordinator、RunTransitionProjectionCoordinator、WorkflowApprovalResumeContext、WorkflowParentResumeCoordinator、WorkflowCancellationProjectionCoordinator、WorkflowContinuationCoordinator、RunArtifactRepository、tool descriptor 和 policy gate 已开始从 `NativeRunEngine` 中显式拆边界。
- Agent runtime SQLite 已有 runs、run_events、run_approvals、run_artifacts、agents、workflows、model_profiles 等核心表；初始化启用 schema metadata、foreign keys、WAL 和 busy timeout，并已有 FK cascade 回归覆盖 TaskRunLink；TaskRunLink 也已扩展 `run_status`、`last_event_sequence`、`updated_at` 投影并带旧库迁移回填。
- `GET /runs/{run_id}/events` 已具备 service、route function 和真实 FastAPI/TestClient HTTP 层回归，覆盖 `after_sequence`、limit clamp、默认 user-visible 过滤和 secret redaction。
- Bridge localhost、token、CORS/Host 约束已实现，并已有真实 FastAPI/TestClient middleware 回归覆盖可信 Origin CORS、非 loopback Host 阻断、非可信 Origin 阻断、GET 放行、POST 缺 token 阻断和 POST 带 token 放行；当前已注册的全部 mutating routes 也已枚举验证缺 token 时统一返回 `invalid_bridge_token`；`start_bridge()` / `restart_bridge()` 拒绝非回环 host，非法 restart 不会先停止当前 Bridge。
- Desktop backend 直接启动时会生成临时 Bridge session token；Electron 正常启动会注入 session token，前端 mutating requests 会自动携带 token header；`apps.desktop_backend.app.main()` 已有无 Hermes 环境的 focused smoke，覆盖安装 TLS env、加载 AppRuntime、注入 runtime、启动 loopback Bridge 和退出清理。
- `POST /runs` 支持 `client_run_id` / `client_request_id` / `Idempotency-Key`，并复用 `create_run_for_runnable()` 到 Agent/Workflow Run 的幂等链路；`POST /ui/chat/messages` 支持 `client_message_id` / `Idempotency-Key`，`POST /ui/agent-runs` 和 `POST /ui/workflow-runs` 支持 `client_run_id` / `Idempotency-Key`，上述入口均已有真实 FastAPI/TestClient HTTP 层映射回归。
- `terminal.run` 已具备审批、workspace 边界、scrubbed env、timeout、进程组取消和输出截断/清洗。
- NativeRunEngine 执行预算已覆盖 `max_model_calls`、`max_tool_calls`、`max_terminal_calls`、`max_run_duration_seconds`、`max_model_output_chars`、`max_tool_output_chars` 和 `max_context_chars`；duration budget 过期时会在继续执行工具前失败。
- NativeRunEngine shutdown 已具备停止接收新 Run、取消运行中 Run、终止 terminal 进程组、写入取消 RunEvent fact 和关闭 runtime DB 连接的回归覆盖；AppRuntime stop 也已覆盖关闭 runtime 注入的 NativeRunEngine service、进程 ActivityStore，并保留全局兼容 service shutdown；AppRuntime 启动 TaskRunner 时会传入同一个 ActivityStore，TaskRunner 任务里程碑和 NativeAgentExecutor 自动委派 activity 都优先使用 runtime 注入边界。
- `workspace.write_patch` 已具备 workspace 边界、审批、hash precondition、hunk context 校验、单文件 unified diff 限制和原子写入；workspace boundary validation 已前置到 approval 前，避免用户审批越界写请求。
- `approval_wait_timeout` 已具备可回放事实日志：RunEngine 超时时写入 `approval.timeout` RunEvent、清理 pending approval，并保持重复 timeout 幂等。
- Approval approve/reject/timeout 端点已具备 focused 幂等回归；route handler 级 approve/reject 重试不会重复执行工具或追加重复 rejection fact；主聊天重复 approval 通过内存 guard 与 SQLite pending→approved 持久化 claim 防止重复执行已批准工具，双 `NativeRunEngine` 实例共享同一 DB 的回归已覆盖该窗口；`cancel_run()` 新增 per-run cancel lock，focused 并发回归确认同一 Run 并发取消只写一条 `run.cancelled` fact 和一条 timeline cancel；`/ui/runs/{run_id}/cancel` 新增 route handler 级重复请求回归，确认 endpoint handler 重试不会追加第二条取消事实。Task cancel 仍保持 v0.5 既有 Task API 语义：已终态任务返回 409，不在本轮改成 Native Run 风格的 200 幂等响应。
- Secret 持久化前清洗已覆盖 ChatSession、ChatStore、旧 chat.db 迁移、ActivityStore、RunEvent payload、Run projection、Run artifact projection、RunGroup projection/旧库迁移、terminal/tool 输出、terminal 子进程 env 继承边界、provider/tool exception projection、自动委派 summary runtime error projection、标准 logging 输出、桌面后端未捕获异常输出、Bridge HTTPException detail、UI JSON error/message、provider catalog 失败缓存、ModelProfile/NativeRunEngine failure projection，以及 ModelProfile / Agent Studio 旧明文 API Key 迁移后的 raw SQLite 清理；ChatAPI / NativeRunEngine / RunRepository 也会拒绝明显 secret 形态的 `client_message_id` / `client_run_id` / `client_request_id` / `Idempotency-Key`，避免幂等键作为原文进入 chat metadata 或 runs 表；Chat transcript 清洗不折叠空白、不截断正文。
- 主聊天 PR-1 上下文合同已有 executor 级回归：多轮上下文、当前 task 排除、32k 字符限制、图片附件 data URL、最多 4 张图片。
- 主聊天自动委派和群聊派活均已具备内部结构化 directive；自动委派提示和 parser 已收敛到 `run_oha_agent` / `run_oha_workflow`，旧 `run_yachiyo_*` / `<yachiyo_delegation>` 不再是有效入口；群聊派活提示已切到 `oha.group_dispatch` native envelope，旧 `<yachiyo_group_dispatch>` 文本协议已移除为有效入口且不会通过内嵌 OHA JSON 绕过。
- Skill library source API / UI 已从 `Yachiyo` 来源命名收敛为 `Installed`，仅保留角色/产品人格层面的 Yachiyo 命名。
- Workspace 初始化、备份、恢复和卸载协议已收敛到 OHA 命名：`.oha_yachiyo_init`、`configs/oha-yachiyo.json`、`oha_workspace`、`oha-workspace`、`oha_only`；旧 workspace 标记和旧卸载 scope 不再是有效入口。
- release-like source guard 已验证：release/alpha/stable metadata 下 debug routes 关闭，development credential fallback 不会被 factory 选中，macOS release-like factory 会选择 Keychain；release verifier 会阻断 stable 渠道误放行开发能力，也有负向回归确认 debug route modules、`debug_routes_enabled()` 和 `DevFileCredentialStore` fallback 被错误放开时会报错。
- release-facing artifact guard 已接入 macOS release workflow，构建 metadata 文件名、release 文档、workflow 和实际本地 `.app` / DMG 产物旧产品身份已有检查；workflow 现在会先用 binary-safe verifier 扫描 `dist/backend` 与 unpacked `.app/Contents/Resources`，再在生成 release DMG/JSON 后扫描 `release/` 目录；release verifier 自身也会阻断 workflow 丢失依赖安装前 security guard、签名导入/签名构建路径、签名脚本 runtime options / entitlements / verify 步骤、Gatekeeper 首启提示、当前未使用 Apple Developer ID / notarization 状态提示、屏幕录制权限提示、packaged resources scan、release 目录 binary scan、release metadata 生成后置扫描顺序、上传 JSON metadata 或 latest channel JSON metadata；release verifier 也会阻断重新打包本地 `node-pty/build` native artifact，避免旧 workspace 路径进入 `.app`，并锁定 hardened runtime、entitlements 与 macOS 权限说明文案。
- 三语 README、用户手册、knowledge base、memory architecture、release packaging、Live2D/TTS 资源说明和桌面前端架构等活跃用户/开发入口文档已收敛到 Oha-Yachiyo / Native Agent / AppRuntime / NativeRunEngine 命名，并新增 source-level guard 防止这些入口重新出现旧 `Hermes` 产品身份、旧 CLI/env 前缀、旧用户目录、旧仓库 URL 或旧外部执行内核安装语义；历史 5 月首用报告和截图索引仍作为迁移前材料保留，不纳入当前入口 guard。
- Tool Center 的旧外部 updater 文案已收敛：页面不再写“不会启动/运行 Native Runtime”这类会误伤内置 NativeRunEngine 语义的提示，改为明确“外部执行内核 updater 已移除，内置 Native Runtime 继续执行任务”；source guard 也禁止误导短语回归。
- Backend import、route registration、standalone packaged backend startup、packaged desktop startup 均已验证；release smoke 现在也覆盖 desktop launcher 启动准备、shell app entrypoint 到 Electron launcher 的路由，以及桌面 MainWindow API modes。
- `/status` 发布版本与产品版本已同步，版本同步脚本也覆盖该路径。
- 成熟 UI 入口已有 pytest 级 feature-preservation guard，覆盖 Chat、群聊、Agent Studio、Workflow、Run Detail、approval、Activity、Proactive TTS、local screenshot、manual TTS、Live2D。
- 手动 TTS 音色包导入已拥有独立桌面 picker：Electron main/preload 暴露 `oha:chooseTtsVoiceArchive` / `chooseTtsVoiceArchive()`，Proactive TTS 页面优先使用该入口，旧 preload 仅有 `chooseLive2DArchive()` 时保留兼容 fallback；source guard 锁定该链路，避免手动 TTS 继续耦合 Live2D 资源导入 API。
- 本地截图权限不足时 `/screen/current` 返回结构化 `screen_capture_permission_denied` 并提示系统设置授权，且已有真实 FastAPI/TestClient HTTP 层回归；ChatAPI 用户请求桌面截图失败时返回/记录结构化且已清洗 secret 的 `desktop_snapshot_error`，同步 ActivityStore 用户可见失败事件，并通过 `verify_secret_redaction()` 扫描本次 ChatStore / ActivityStore SQLite 落盘目录；主动关怀屏幕权限检查继续返回 `permission_denied` / `settings_opened` 结构化结果。
- 主动关怀桌面观察已有 TaskRunner 级集成回归：`ProactiveDesktopService` 创建低风险 Screenshot Task、写入专用主动关怀会话、复用图片附件链路传递 `image_url` data URL，并由 `NativeAgentExecutor` / `NativeRunEngine` 完成 main_chat_run、RunEvent replay 和 ChatSession 投影，不会污染当前可见聊天会话。
- 成熟 UI 入口已有浏览器级 route smoke，覆盖主控台、Chat、Agent Studio、Workflow、Run history、Diagnostics、Settings、Proactive TTS、Live2D、Tool Center、Model Profiles、Resources、Workspace、Activity feed/detail、App Update。
- 成熟 UI 入口已有浏览器级按钮 smoke，覆盖 Chat 提交 readiness、Agent Studio tab 切换、Workflow/Run Detail shell、Live2D 资源设置、主动关怀语音保存。
- 成熟 UI flow contract 已有同步 pytest 覆盖，锁定 Chat 文本/图片发送、idempotency、停止生成、会话列表/搜索/加载/清空/丢弃空会话/删除、ChatBridge 会话摘要 / conversation overview、群聊 create/update、自动委派 summary task、Bubble / Live2D launcher 最近会话摘要、Chat 审批卡跳转 Run Detail 后读取同一 main_chat_run detail / RunEvent replay、Agent Studio 定义 list/create/update/delete、Skill Library 本体 list/import/source/sync/install/get/update/delete、Skill 文件夹 list/create/update/delete 与 Agent Skill attach/detach、Workflow Studio 定义 list/create/update/delete、Model Profiles 本体 list/create/get/update/defaults/test/delete、Model Sources list/create/get/update/test/fetch-models/delete、Run / RunGroup 列表与详情、Run artifact、rerun、delete、approval approve/reject 和 Run cancel 的 Bridge 合同。
- Chat 群聊 UI 已补稳定 `data-testid` 入口，覆盖 Agent/群组 tab、创建群组按钮、群组设置、群组 dialog、头像选择/清除、群名输入、成员列表、Agent 成员 checkbox 和提交/取消按钮，后续 Browser E2E 可以直接驱动群聊创建/编辑路径。
- Chat message summary/followup 状态已补稳定 `data-testid` 和 summary tone 属性，后续 Browser E2E 可以直接断言群聊总结、直接 Agent follow-up 和自动委派整理任务的 processing/completed/failed UI 状态。
- Chat message summary/followup 状态 DOM 现在还暴露 summary task/status、RunGroup 和 follow-up task / Agent message ids，后续 Browser/Desktop E2E 可以直接断言群聊总结任务与用户补充消息指向同一条 Native 执行链。
- Chat message activity list 已补稳定 `data-testid`、activity status/tool 数据属性和 Run Detail / Activity detail / expand 操作 selector，后续 Browser E2E 可以直接断言自动委派 activity、ActivityStore detail 跳转和 Run Detail handoff。
- Chat Agent run progress card 已补稳定 `data-testid`、Run/RunGroup/runnable 数据属性和 Run Detail 操作 selector，后续 Browser E2E 可以直接断言群聊/自动委派执行中 UI 与同一 Native Run Detail handoff。
- 自动委派 delegated-run summary Bridge response 现在回传 `run_group_id`、`run_status` 和 `source_task_id`，重复创建请求也回传同一 summary message/task 元数据；后续 Browser/Desktop E2E 可以直接断言 summary task、源 delegated Native Run、RunGroup 和 Run Detail replay 指向同一条执行链。
- Chat readiness 已有真实浏览器级 E2E：source preview 打到 localhost-only source Bridge，未配置模型时 UI 入口保留、显示 native readiness、console error 为空，直接 POST 返回 `native_agent_not_ready / model_profile_required`。
- Chat 可用模型路径已有真实浏览器级 E2E：source preview 打到 localhost-only source Bridge 和本地 OpenAI-compatible fake model，真实提交用户消息，TaskRunner 走 `NativeAgentExecutor`，Run 完成并回放 `model.output.completed`，ChatSession 投影 assistant 回复。
- Chat 取消 late-output 已加固，并已补可重复 pytest 级 Bridge route 回归与 in-app Browser 按钮级 source Bridge smoke：慢模型返回前通过 `/ui/chat/session/cancel` 取消任务后，Run 可靠进入 `cancelled`，late model response 不再写 `model.output.completed` 或把 Run 覆盖回 running/completed，且 `/ui/runs` list/detail projection 可读取同一 cancelled Native main_chat_run 的 Task↔Run 映射、`task_run_link_run_status`、`task_run_link_last_event_sequence` 与 `run.cancelled` fact。
- Chat 图片附件已有 live source Bridge E2E，并已补可重复 pytest 级 Bridge route 回归：`/ui/chat/messages` 提交 image data URL attachment，ChatSession 只暴露公共 attachment URL，TaskRunner / NativeAgentExecutor 将图片传给 NativeRunEngine fake model，并可通过 `/runs/{run_id}/events` 读取 `model.output.completed` / `run.completed` replay。
- Chat 审批已有 live source Bridge E2E、in-app Browser Chat approval-card approve smoke、in-app Browser Chat composer approval reject smoke、in-app Browser Chat message approval reject smoke，并已补可重复 pytest 级 Bridge route 回归：真实 `/ui/chat/messages` 触发工具 approval，Chat 页面 approval card 点击批准后可通过 `/ui/runs/{run_id}/approval/approve` 恢复模型并完成 `agent.tool.approval_required` / `agent.tool.approval_approved` / approved `agent.tool.call` / `model.output.completed` / `run.completed` replay；批准后 `terminal.run` 非零退出的 HTTP route roundtrip 也已覆盖 Chat failed 投影、Task failed、Run Detail failed、approved failed tool call 和 `agent.run.failed` replay；Chat composer approval notice 和 message approval card 点击拒绝后都会清空 approval UI，Chat transcript 以 failed 展示拒绝原因，Native Run / TaskRunLink 进入 cancelled 并保留 `agent.tool.approval_rejected` / `agent.run.cancelled` replay；Chat message approval card / actions 与 composer approval notice 现在暴露 `data-run-id`、approval id/source/tool/requester/kind/signature/item id 等稳定 selector，后续 Browser/Desktop E2E 可以直接断言 Chat 审批 UI 与 Run Detail 指向同一个 Native approval；前端也已加 guard，避免 completed activity metadata 继续派生可操作审批卡。
- Chat 审批到 Run Detail 的同步 UI flow contract 已扩展到批准后刷新：Chat approval card / composer approval 调用同一 `/ui/runs/{run_id}/approval/approve` route 后，Chat messages 投影会清空 `pending_approval` 并进入 completed，Agent Studio Run Detail 读取同一 main_chat_run 也会显示 completed，`/runs/{run_id}/events?after_sequence=12` 可继续读取 `agent.tool.approval_approved` / `agent.tool.call` / `model.output.completed` / `run.completed` replay；批准后工具失败分支也已有同步合同，锁定 Chat failed 投影、Run Detail failed 状态和 `agent.tool.approval_approved` / failed `agent.tool.call` / `agent.run.failed` replay。
- Run API 现在直接投影 `task_id`、`session_id`、`task_run_link_created_at`、`task_run_link_updated_at`、`task_run_link_run_status` 和 `task_run_link_last_event_sequence`，让 Task↔Run 映射、当前状态和 replay 游标不必从 timeline 反推；Agent Studio Run Detail 的 `RunSpec` 与元数据行也已显式承接并展示这些字段，source-level guard 与同步 UI flow contract 会阻断前端回退成只看裸 Run timeline。
- Chat 图片附件产品路径已有 TaskRunner/route 级集成回归：真实 ChatAPI 保存 pasted image、TaskRunner 执行、NativeAgentExecutor 传递 OpenAI-compatible `image_url` data URL、NativeRunEngine 完成 RunEvent 和 ChatSession 投影，并且 `/ui/runs` Run Detail projection 与 `/runs/{run_id}/events` replay API 均可读取同一 Native main_chat_run。
- 主聊天工具审批等待已有 Chat API 级投影兜底：RUNNING Task 可通过当前 runtime service 的 Task↔Run link 投影 `approval_required` 到 ChatSession metadata、ActivityStore 和 `approval_count`，审批恢复后会清空旧 `pending_approval`；TaskRunner 和 ChatAPI 的终态投影均会移除过期审批进度，避免 completed assistant message 继续显示旧审批卡。
- 主聊天工具审批往返已有 TaskRunner 级集成回归：真实 TaskRunner / NativeAgentExecutor / NativeRunEngine 可让 main_chat_run 暂停审批、批准后执行 `workspace.write_patch`、恢复模型、完成 Task 与 ChatSession；并发重复 approval 和跨 NativeRunEngine 实例的重复 claim 不会重复执行工具；批准后 `terminal.run` 非零退出会让 main_chat_run 进入 failed，并持久化可回放的 `agent.run.failed` RunEvent。
- 主聊天自动委派已有 TaskRunner 级集成回归：真实 TaskRunner / NativeAgentExecutor / NativeRunEngine 可解析 `run_oha_agent` directive、创建 delegation Agent Run、记录 ActivityStore 委派活动、把 delegated result 回填给主模型并完成最终 ChatSession 回复；delegated Run 结束后创建主模型 follow-up summary Task 已有真实 NativeRunEngine Run projection 回归，并已补 `/ui/chat/delegated-run-summary` Bridge route 闭环，覆盖 route 创建 summary Task、NativeAgentExecutor 完成新的 main_chat_run、TaskRunLink status / replay cursor、RunEvent replay、Run Detail projection 与 Chat metadata 指向同一源 delegated Run / RunGroup；自动委派 summary 路径已修正为同时使用当前注入 runtime service 与 runtime activity store，不再隐式打开全局 NativeRunEngine / ActivityStore。
- 会话总结已有 ChatBridge 行为回归，覆盖真实 ChatSession / ChatStore 中当前会话的 `get_recent_sessions()` 摘要、最近 Task handoff 元数据 `latest_task_id`、`get_conversation_overview()` 给模式壳暴露的 `recent_sessions` / `latest_reply`，以及 processing / failed 状态摘要文案；现有 launcher route 回归也锁定 Bubble / Live2D 入口复用该 conversation overview。
- 群聊派活已有 ChatAPI + 真实 NativeRunEngine 级集成回归，并已补 Bridge route 级闭环：`/ui/chat/groups` 创建群聊后通过 `/ui/chat/messages` 触发主模型 `oha.group_dispatch`，创建真实 Agent Run，群组 upstream 进入 Agent context，Agent 完成后回写群聊消息并创建主模型群总结 Task，随后通过 `NativeAgentExecutor` 生成新的 main_chat_run / TaskRunLink status / replay cursor / RunEvent replay / Run Detail projection / ChatSession 投影；群聊直接点名 Agent 的路径也已有 TaskRunner + 真实 NativeRunEngine 回归，覆盖 direct Agent Run 完成后创建主模型整理 Task，以及工具审批拒绝/取消后继续创建主模型整理 Task，并继续通过 `NativeAgentExecutor` 生成 main_chat_run / RunEvent replay / ChatSession 投影；群聊主模型整理 task 标签已收敛到 Oha-Yachiyo 命名，后台 TaskRunner 终态投影也会保留 summary metadata 以清理父消息 pending 状态；ChatAPI 的 Agent/Workflow/Run 状态读取入口现在统一经 `_agent_runtime_service()`，避免成熟业务路径直接绕过 runtime 注入边界。
- Workflow start / agent / artifact 节点执行、Workflow approval node、Workflow 等待子 Agent 审批、子 Agent 审批恢复/拒绝现在都有 replayable RunEvent：`workflow.node.start` / `workflow.node.agent` / `workflow.node.artifact` / `workflow.node.approval_required` / `workflow.run.approval_required` / `workflow.run.child_resumed` / `workflow.run.resumed` / `workflow.run.cancelled` 已接入 `/runs/{run_id}/events`，并有 route 级 Run Detail projection 回归；Workflow 子 Agent 审批 approve route 也已覆盖子 Run 自身 approve 后的 Run Detail 刷新，以及 `/runs/{child_run_id}/events` 中的 `agent.tool.approval_approved` / `agent.tool.call` / `agent.run.completed` replay；Workflow 子 Agent 审批 reject route 也已覆盖子 Run 自身 cancelled Run Detail 与 `agent.tool.approval_rejected` / `agent.run.cancelled` replay；Workflow rerun route 现在也会持久化 `run.rerun.started` RunEvent，route 回归覆盖 rerun 后 Run Detail、artifact 和 replay API；真实 FastAPI/TestClient HTTP roundtrip 已覆盖 `/ui/workflows` 创建 Workflow、`/ui/workflow-runs` 进入 Workflow approval node 审批和子 Agent 审批、`/ui/runs/{run_id}/approval/approve` 恢复 Workflow approval node、`/ui/runs/{run_id}/approval/reject` 取消 Workflow approval node、`/ui/runs/{run_id}/cancel` 取消 Workflow approval node、`/ui/runs/{run_id}/rerun` 重跑 Workflow 并读取新 Run Detail / artifact / replay、`DELETE /ui/runs/{run_id}` 删除 completed Workflow 及子 Run / RunGroup / artifact / replay、`/ui/runs/{child_run_id}/approval/approve` 恢复父 Workflow、`/ui/runs/{child_run_id}/approval/reject` 取消父 Workflow、`/ui/runs/{child_run_id}/cancel` 取消子 Agent 并投影父 Workflow、父/子 Run Detail、父/子 RunEvent replay 与 artifact 读取。
- Agent Studio Run Detail 已接入 `/runs/{run_id}/events` replay API，Execution 区优先展示 replayable RunEvent facts，选中 Run 的状态/更新时间/timeline 变化时会刷新 replay，支持按 `after_sequence` 继续加载更多 replay facts，常见 RunEvent facts 已映射为可读标题/语气，保留旧 timeline 回退；Run Detail replay 标题映射、分页加载、sequence 去重合并、loading/error 状态的 source guard 已覆盖；Run Detail 的 Workflow 子 Agent 审批桥接已补 source-level guard，锁定父 Workflow 选中态、子 Run approve/reject/cancel、子 Run 打开、approval 后 child/parent Run cache、RunGroup 刷新和审批后父 Run 刷新链路，并有 route contract 覆盖批准/拒绝/取消后子 Run、父 Workflow Run 和 RunEvent replay 刷新；Run rerun 后前端会立即缓存新 Run Detail 并刷新 RunGroup，Run 删除后前端会同步清理 Run list / Run Detail cache / RunEvent replay cache / 已空 RunGroup cache，并有 source-level guard；真实 FastAPI/TestClient HTTP roundtrip 也已覆盖 Agent Run 进入 `approval_required`、Run Detail 读取、approval approve 恢复、approval reject 取消、Run cancel 取消待审批 Run、Agent rerun 新 Run Detail / replay、Agent delete 清理 Run / RunGroup / replay、RunEvent replay 中的审批/工具/完成或取消 facts。
- Run Detail 的 RunEvent replay 标题展示已补 Workflow node label fallback：`workflow.node.agent` / `workflow.node.artifact` 等 replay payload 带 `workflow_node_label` 但没有 tool/model/result/error detail 时，Execution 区仍会显示具体节点名；source guard 也锁定 approval approved/rejected/resumed replay 标题映射，避免审批恢复事实退回原始 event 名。
- Run Detail Execution replay 行已补稳定 `data-run-event`、`data-run-event-id/run-id/sequence/schema-version/actor/visibility/sensitivity/status/tone` 和 `data-child-run-id` 属性，后续 Browser/Desktop E2E 可以不用文本匹配就断言 RunEvent replay 身份、顺序、user-visible 非 secret 边界、状态、审批/工具/模型语气和子 Run handoff；Agent Run Detail Electron smoke 现在也断言 replay payload 字段真实渲染到 Execution 内容中，例如 `agent.tool.call` 的 `path=README.md`、分页内 `model.output.completed` 内容和加载更多后的 completed result，避免只验证事件类型而漏掉 payload 展示。
- Run Detail Workflow step 行现在暴露 `data-workflow-step-key/kind/node-id/status` 与 `data-child-run-id`，artifact item 也暴露 `data-artifact-path/kind/source-run-id/source-label`，后续 Browser/Desktop E2E 可以稳定断言 Workflow step 状态和 artifact preview handoff。
- Run History row / open-run button 与 Run Detail article 已补稳定 `data-testid` 和 Run metadata 属性，覆盖 `run_id`、Run kind/status、RunGroup、Task 与 session id，后续 Browser/Desktop E2E 可以直接定位同一个 Task↔Run 记录并验证 Run Detail handoff。
- AppRuntime 已提供主聊天默认 tool/workspace policy 并接入 `select_executor()`；主聊天产品路径默认进入同一套 ToolDescriptor / PolicyGate / approval / workspace boundary 体系，ToolBroker 已有 realpath/symlink 越界回归。
- 未配置模型时返回结构化 native readiness 错误，不再引导安装旧执行内核。

### 仍未完全达成

- 模型输出 durable persistence 已有 batched completed-event 回归、dict-style stream iterator delta 合并压力测试、OpenAI SDK object-style content chunk 合并回归、OpenAI-style streaming tool_call delta 合并回归、OpenAI-compatible SSE stream parser / NativeRunEngine `stream=True` contract 回归、OpenAI-compatible SSE parser split UTF-8 chunk 回归、fake HTTP provider SSE 闭环回归、fake HTTP provider split UTF-8 SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider message-level content / reasoning SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider content-part array SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、content-part array `text.value` 对象形态回归、content-part array 中 `reasoning` / `thinking` 私有片段不作为可见 output 落盘回归、streaming reasoning-only delta 不作为可见 output 落盘回归、non-stream dict/object reasoning-only message 不作为可见 output 落盘回归、fake HTTP provider coalesced/split/multiline `data:` SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider SSE tool-call、message-level SSE tool-call、message-level streaming tool call object arguments、non-stream dict / OpenAI SDK object message tool-call object arguments 归一化为 JSON 字符串后再进入 provider history、split-frame SSE tool-call、indexless SSE tool-call delta、缺 `index` 但带稳定 tool-call `id` 的 interleaved delta、multiline `data:` SSE tool-call 闭环回归、fake HTTP provider legacy `delta.function_call` 帧透传回归，以及 fake HTTP provider SSE / multiline `data:` / `event: error` / 顶层 `type:error` SSE error frame 失败/清洗闭环回归；现在也有 opt-in `scripts/smoke_openai_compatible_stream.py` 可用真实 provider 做 streaming / tool-call smoke，release workflow 已接入有凭据才运行的真实 provider 文本流和 `workspace_read` tool-call smoke，支持要求流式文本内容、content-part array、message-level content / reasoning frame、reasoning delta、content-part array 中 reasoning/thinking 私有片段、content-part array `text.value` 对象形态、message-level tool call object arguments、指定工具名、tool-call arguments substring、release 中 `workspace_read` 参数必须包含 `README.md` 且 JSON 参数 `path` 字段必须等于 `README.md`，并支持 `finish_reason` 断言，脚本自身已有 fake transport、role-only 首包、usage-only 尾包、多 choice 同 index tool-call delta、indexless tool-call delta、缺 `index` 但带稳定 tool-call `id` 的 interleaved delta、OpenAI SDK object-style tool_call / reasoning delta、multiline `data:` SSE tool_call、legacy streamed `function_call` delta、message-level content / reasoning frame、content-part array frame、reasoning 只统计长度不打印原文、finish_reason 断言和错误 secret 清洗回归，且默认摘要不打印 raw tool arguments；实际凭据环境下的真实外部 provider 联调仍需做。
- opt-in streaming smoke helper 现在还支持 `--require-tool-result-content` 与 `--expect-tool-result-finish-reason`：真实 provider 第一轮必须流式发出 `workspace_read`，脚本用 synthetic tool result 进行第二轮 streaming follow-up，assistant tool-call history 使用 OpenAI-compatible `content: null` 形态，要求输出内容并可断言 follow-up `finish_reason`；该路径不会上传本地 README 内容，摘要仍不打印 raw tool arguments。
- opt-in streaming smoke helper 现在还覆盖 SSE delta tool-call 中 `function.arguments` 为 JSON object 的 provider 形态：`README.md` substring / `path=README.md` JSON 字段断言可以通过，但摘要仍不打印 raw arguments。
- opt-in streaming smoke helper 现在也能汇总顶层 `delta.tool_calls` / `message.tool_calls` 与顶层 `finish_reason` / `stop_reason`，覆盖部分 OpenAI-compatible gateway 预处理后不再包在 `choices[]` 内的 chunk 形态，默认摘要继续不打印 raw tool arguments。
- NativeRunEngine 主聊天模型循环也补了 SSE delta tool-call object arguments 的闭环回归：object arguments 会归一化为 JSON 字符串进入 provider history，并实际执行 `workspace.read` / 写入 `agent.tool.call` replay。
- Responses-style streaming chunk 也已进入同一类回归：NativeRunEngine 和 opt-in smoke helper 都能识别顶层 `response.output_text.delta`、`response.output_text.done` 文本快照、`response.refusal.delta/done` 可见拒答、`response.content_part.added/done` 文本 part 快照、`response.output_item.added/done` message / function-call item、`response.function_call_arguments.delta/done` 参数帧和 `response.completed` 完成帧；参数 delta 不再被误算作可见正文，同一段 `output_text.done` / `refusal.done` / content part 快照会替换而不是重复拼接文本 delta，`output_item.done` 完整快照也会替换而不是重复拼接 arguments，main chat 与 Agent Run 中只有 `call_id` 没有 `id` 的 Responses function call 会用 `content: null` assistant tool-call history 与同一 `tool_call_id` 继续执行 tool result follow-up，默认 smoke 摘要仍不打印 raw tool arguments。
- NativeRunEngine 主聊天与 Agent Run 的 Responses-style tool-call stream 现在会保留 `output_index=0` 这类合法零值索引，不再被 fallback `item.index` 覆盖后把第 0 路工具调用和第 1 路调用合并到同一 slot；对应 provider contract 已接入 release workflow，release verifier 会动态阻断漏跑。
- opt-in streaming smoke helper 现在会保留 Responses-style `output_index=0` / `summary_index=0` 等合法零值索引，不再用 fallback `item.index` / `content_index` 覆盖；多 tool-call 与 reasoning summary key 的零索引回归已补，release verifier 会阻断该合同丢失。
- opt-in streaming smoke helper 现在还覆盖 Responses-style reasoning 快照：`response.reasoning_summary_part.added/done` 和 `response.output_item.added/done` 中的 reasoning item / summary part 只计入 reasoning 长度，不进入可见 content，也不会把 reasoning 原文打印到公开 smoke summary；release verifier 会阻断 helper 或测试丢失该合同。
- opt-in streaming smoke helper 现在还覆盖 Responses-style SSE transport 闭环：mock provider 通过 `event: response.*` + `data: {"type":"response.*"}` 帧进入 `urlopen` / OpenAI-compatible SSE parser / `run_stream_smoke()` 完整路径，验证文本、`workspace_read` tool-call、`README.md` 参数、`path=README.md` JSON 字段、`response.completed` 完成帧，以及只有 `call_id` 的 Responses function call 也能进入 synthetic tool-result follow-up history，同时默认摘要不泄漏 API key 或 raw arguments。
- opt-in streaming smoke helper 现在会优先读取 Responses-style `response.completed` payload 内的 nested `finish_reason` / `stop_reason`，没有标准终止原因时才回退到 `completed`，避免 Responses-like gateway 明明以 `stop` 完成却被 release smoke 误判。
- dict-style streaming 输出与 OpenAI SDK object-style streaming 输出的 completed-event persistence 回归已纳入 macOS release workflow smoke，release verifier 会阻断 workflow 丢失这些测试，确保主聊天长 streaming 输出继续只落单条 `model.output.completed`，不回退为 token/delta 级 RunEvent 持久化。
- canonical SSE content stream、coalesced frame、split frame、split UTF-8 frame 和 multiline `data:` content stream 回归已纳入 macOS release workflow smoke，release verifier 会阻断 workflow 丢失这些测试，确保发布门禁不只覆盖 tool-call stream，也覆盖真实 provider 文本流 transport 边界。
- non-stream provider message `tool_calls` 与 OpenAI SDK object-style message `tool_calls` 回归已纳入 macOS release workflow smoke，release verifier 会阻断 workflow 丢失这些测试，确保 object arguments 继续归一化为 JSON 字符串进入 provider history，并实际执行 Native `workspace.read` / 写入 `agent.tool.call` replay。
- canonical SSE `tool_calls[]`、message-level SSE tool-call、multiline `data:` SSE tool-call、split-frame SSE tool-call、interleaved / multi-choice / indexless / stable-id 归并 SSE tool-call、legacy `delta.function_call`、Responses-style NativeRunEngine 主循环以及 Responses `call_id` main chat / Agent Run history 回归已纳入 macOS release workflow smoke，release verifier 会阻断 workflow 丢失这些测试，避免发布门禁漏掉基础 Chat Completions SSE、message-level、多行/分片 transport、多工具交错、多 choice 同 index、缺 `index` 的 gateway 形态、旧式 `function_call`、Responses 风格 tool-call stream 或只有 `call_id` 的 Responses provider history 形态。
- OpenAI-compatible SSE parser 现在会跳过 provider `ping` / `heartbeat` / `keepalive` 控制帧，避免真实 provider 心跳污染 streaming smoke 摘要；带 `choices` 的有效 payload 即使带控制事件名也会保留，错误事件仍优先抛出并清洗。
- ApprovalCoordinator 已承接 approve/reject/timeout 的通用状态转换；主聊天工具审批、standalone Agent 工具审批和 Workflow approval node 的 reject / timeout 现在都有边界 spy 回归，确认 `NativeRunEngine.reject_run_approval()` / `timeout_run_approval()` 继续委托 ApprovalCoordinator 完成状态转换与 replay fact 写入；approved-tool 恢复的 pending approval 持久化 claim 和 approved/running 投影已收敛到 `ApprovalResumeCoordinator.claim_and_project_approved_tool()`，避免主聊天与 standalone Agent 分支重复实现；ApprovalResumeCoordinator 已承接批准后的工具执行、custom-api 模型循环恢复入口，以及 completed / 二次 approval_required / failed 恢复状态编排，并已有 coordinator 级成功续跑 / fatal tool failure 阻断 / 工具后继续模型顺序 / 恢复状态编排回归；ApprovalResumeProjectionCoordinator 已承接 approved-tool resume 后的 running / completed / approval_required / failed Run 投影，并已有 coordinator 级 replay fact / Run update / RunGroup / parent Workflow child-running 回归；RunTransitionProjectionCoordinator 已承接 child Run 状态变化和 root Workflow cancelled RunGroup 投影，并已有 coordinator 级 child transition / workflow group projection 回归；WorkflowApprovalTransitionContext / WorkflowApprovalResumeContext 已承接 Workflow approval pending payload 与 approve 恢复上下文解析，WorkflowApprovalResumeCoordinator 已承接 Workflow approval approve 后的 pending claim 与 continuation handoff，并已有 context 级 payload/start-index/timeline/artifact 和 coordinator 级 claim/handoff 回归；WorkflowChildOutcomeCoordinator 已承接 child Agent Run 结果合并、artifact reference 去重和 workflow node context 投影；WorkflowParentRunLocator 已承接父 Workflow 等待子 Run 查找和 root RunGroup 判定；WorkflowResumePlanner 已承接 Workflow snapshot 恢复与 child Agent ordinal 到 continuation start-index 的映射；WorkflowPathPlanner 已承接 Workflow path、node task/criteria、child goal、artifact path 和 runtime/path snapshot 规划；WorkflowRunStartProjector 已承接 Workflow run started timeline 与 RunEvent replay payload 投影；WorkflowParentResumeCoordinator 已承接父子 Run 联动，并已有 completed child replay / continuation handoff 的 coordinator 级回归，且重复 child approval_required / cancelled / failed update 不会重复投影父 Workflow replay fact 或重复更新父 Run；WorkflowCancellationProjectionCoordinator 已承接父 Workflow 取消时的 pending approval / child approval / child outcome 投影，并已有 coordinator 级 child cancellation / replay fact / workflow node metadata 回归；WorkflowContinuationCoordinator 已承接具体 Workflow step continuation 和异步后台失败投影，并已有 approval node pause / approved continuation handoff / public pending projection / RunGroup handoff、artifact node write / completion handoff、background failure projection、failure replay payload secret 清洗的 coordinator 级回归。
- 主聊天自动委派和群聊派活都已引入内部结构化 directive；自动委派已收敛到 `run_oha_agent` / `run_oha_workflow`，并已有 TaskRunner 级 NativeRunEngine 闭环回归，群聊主提示与 parser 已收敛到 `oha.group_dispatch` / `<oha_group_dispatch>` / native 命名，并已有 ChatAPI + 真实 NativeRunEngine 闭环回归；旧 `run_yachiyo_*`、`<yachiyo_delegation>` 和 `<yachiyo_group_dispatch>` 不再作为有效入口。
- Workflow 与主聊天共享 NativeRunEngine 的路径已存在，已有 focused 回归、UI 入口 guard、同步 UI flow contract、浏览器级 route smoke、部分按钮级 smoke、无模型 Chat readiness Browser E2E、可用 fake 模型 Chat Browser E2E、Vite Browser DOM selector smoke、source Bridge Run Detail approval 浏览器点击 E2E、source Bridge Run Detail artifact/rerun/delete Browser E2E、slow fake model 的 Chat 取消 late-output Bridge 复验与 Chat 停止按钮 Browser smoke、Chat approval-card approve Browser smoke、Chat composer approval reject Browser smoke，以及 Chat message approval reject Browser smoke；主聊天多轮/图片已补 executor/API/Bridge 合同、TaskRunner 级图片 roundtrip、image-only 默认图片分析提示的 ChatAPI 与 HTTP route→TaskRunner→NativeRunEngine→RunEvent 回归、live source Bridge 图片 E2E、HTTP route 图片附件发送 / attachment FileResponse roundtrip 和 Run Detail/RunEvent route projection，主聊天审批等待、approval roundtrip、live source Bridge 审批 E2E 和重复 approval 防重复执行已补回归，Chat 图片粘贴/上传/移除、停止生成、消息审批卡与 composer 审批卡、Chat 审批卡到 Agent Studio Run Detail 的 route/replay handoff、委派 Run 结束后 summary task processing 状态已补 source-level UI wiring guard，Chat 图片/取消/审批/Run Detail、Agent Studio agents 定义 CRUD、Agent Studio Skill Library sync/install/update/delete、Agent Studio Skill mounting attach/detach/bulk update、Agent Studio Skill folder create/rename/open/delete、Agent Studio Run Detail/approval/replay/artifact、Workflow Studio 编辑/节点配置/保存并运行路径已暴露稳定 `data-testid` 选择器并由 source guard 锁定，Workflow Save and Run 也已锁定保存草稿后必须用 `saved.workflow_id` 创建 Workflow Run、刷新 run target 并打开 Run Detail，Chat 上传后附件预览/移除已有稳定 selector guard，且 source guard 会确认 header/composer 两个图片按钮都连接同一个 hidden file input，hidden file input 也共享同一禁用条件，paste / hidden input `onChange` / `addImageFiles()` 会在处理文件前复核该禁用语义，避免未来 Browser file upload 直接驱动时绕过 UI 状态，Workflow 节点执行与审批等待 facts 已接入 RunEvent replay，并新增真实 HTTP route roundtrip 覆盖 Agent/Workflow approval、Run Detail、RunEvent replay 和 artifact 读取；群聊派发、主聊天自动委派、Bubble / Live2D launcher 会话总结和 Workflow 子审批已有 source Bridge Browser smoke；Chat delegated summary Electron smoke 现在同时验证源 delegated Agent Run 和 summary `main_chat_run` 都能从 Chat 打开对应 Run Detail 并展示 RunEvent replay payload；Chat group summary Electron smoke 现在也验证群聊 summary `main_chat_run` 和 group Agent Run 都能从 Chat 打开对应 Run Detail，并展示 `model.output.completed` / `run.completed` / `agent.run.completed` replay payload；Chat 图片 hidden file input `change` 路径与 Chromium `DOM.setFileInputFiles` 级真实文件注入已有 Electron UI smoke 覆盖，但仍需要补系统 file picker 和桌面 `.app` 内完整成熟功能 E2E。
- Chat composer 上传预览现在暴露 `data-attachment-id/name/mime/size/width/height`，发送后的 message attachment item 也有稳定 `data-testid` 和 `data-attachment-id/name/kind/mime`，与 composer 上传预览/移除 selector 配套，后续真实 file upload 浏览器 E2E 可以稳定断言“选择文件 → 预览 → 发送 → 消息附件渲染”闭环。
- Chat 图片附件现在还提供仅开发环境注册的 `oha-chat-e2e-add-image` 自定义事件，Browser smoke 可在缺少系统 file picker / `setInputFiles()` 能力时注入 data URL 图片并复用同一条 `addImageFiles()`、尺寸校验、composer preview、发送和 message attachment 渲染路径；source guard 锁定该 hook 必须受 `import.meta.env.DEV` 保护，packaged app verifier 会阻断生产 `app.asar` 残留该开发专用事件名。
- 可重复本地 UI smoke `node scripts/smoke_chat_image_attachment_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 Chat 页面，先点击 header / composer 两个图片上传按钮并拦截 hidden `chat-image-file-input.click()`，确认两个真实按钮都指向同一个文件输入；随后在页面上下文构造真实 `File` 并通过 hidden `chat-image-file-input` 的 `DataTransfer.files` 派发 `change`，断言 composer preview，点击 `chat-composer-attachment-remove` 后确认预览消失且发送按钮重新 disabled；最后通过 Chromium DevTools Protocol `DOM.setFileInputFiles` 给同一个 hidden file input 设置磁盘上的 `smoke-image-cdp.svg`，断言 composer preview、`/ui/chat/messages` 发送 payload、message attachment item，并真实点击消息附件打开 image viewer modal 后再点击 `chat-image-viewer-close`，确认 backdrop / modal / stage 均关闭。该 smoke 不依赖 dev-only image event，覆盖 `button → input.click()`、`input.files → onChange → addImageFiles() → FileReader → preview → remove → DOM.setFileInputFiles → send → message attachment click → image viewer open/close` 路径，并由 source-level pytest guard 锁定不能退回 `oha-chat-e2e-add-image` 注入。
- 可重复本地 UI smoke `node scripts/smoke_chat_cancel_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 processing Chat 会话，分别真实点击 composer stop 与 header stop，断言两个入口都调用 `/ui/chat/session/cancel`，并验证 Chat UI 清除 processing 状态、禁用 header stop、移除 composer stop 和展示 cancelled assistant message。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_chat_approval_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载带 `pending_approval` 的 Chat 会话，断言 message approval card 与 composer approval notice 同时展示同一 Run / approval / tool preview；随后分别真实点击 message approval 和 composer approval 的 Run Detail 入口，确认 Agent Studio 打开同一 `main_chat_run`、展示 approval request，并在 `agent.tool.approval_required` replay payload 中展示 `terminal.run`、命令、cwd 和 checkpoint preview；再分别真实点击 message approve / message reject / composer approve / composer reject 四个入口，确认两次调用 `/ui/runs/{run_id}/approval/approve`、两次调用 `/ui/runs/{run_id}/approval/reject`，并验证 Chat UI 清除审批 UI、展示 completed / rejected assistant message。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_chat_delegated_summary_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载带自动委派 activity approval 的 Chat 会话，断言 composer approval notice 来源为 `activity` 并指向同一 delegated `agent_run`；随后先真实点击 composer reject，确认 `/ui/runs/{run_id}/approval/reject` 被调用、Chat 清除审批 UI、创建 cancelled delegated summary 且不泄露 `run_oha_agent` / `<oha_delegation>`，再点击 activity Run Detail 验证 delegated Run cancelled 结果和 `agent.tool.approval_rejected` / `agent.run.cancelled` replay；重置 mock pending 状态后继续真实点击 composer 的 Run Detail 入口确认 Agent Studio 展示 `agent.tool.approval_required` replay，回到 Chat 后真实点击 composer approve，断言 `/ui/runs/{run_id}/approval/approve` 和 `/ui/chat/delegated-run-summary` 被调用、Chat 显示 completed delegated summary 且不泄露内部 directive；随后点击 summary 消息 Run Detail 验证同一 summary `main_chat_run` 的 `model.output.completed` / `run.completed` payload 展示 summary result，最后点击 activity Run Detail 验证 delegated Run completed 结果和 `agent.tool.approval_approved` / `model.output.completed` / `agent.run.completed` replay payload 展示 delegated result。source-level pytest guard 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_chat_group_summary_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 Chat 页面，真实点击群组 tab、创建群组、验证群头像预览/选择按钮在无桌面图片 picker 时回落到 hidden `chat-group-avatar-file-input`、通过 `DataTransfer.files` 注入头像、清除后重新注入、选择 Agent 成员、在新群组会话中发送消息，并断言 `/ui/chat/groups` 收到成员列表和群头像 data URL、`/ui/chat/messages` 带 `client_message_id` 且发送发生在新群组会话；随后 mock Bridge 返回带 `group_dispatch_run_group_id`、`group_agent_summary_task_id` 和 `group_agent_summary_pending` 的 Agent 汇总消息，前端必须渲染 pending `chat-message-summary-status` 并暴露 summary task、RunGroup、status 和 tone 属性；同一 smoke 再模拟主模型群总结完成，断言父 Agent 消息的 summary status/tone 切换到 completed、pending 文案消失，并渲染主模型 summary message；点击 summary 消息 Run Detail 后确认 summary `main_chat_run` 展示 `model.output.completed` / `run.completed` replay payload；随后真实发送同一群组任务的补充消息，断言 `chat-message-followup-status` 暴露 follow-up task ids 和 Agent message ids；最后让 summary activity 携带具体 `agent_run`，真实点击 `chat-message-activity-open-run-detail`，确认 Agent Studio 打开同一 Run、展示 completed 结果和 `agent.run.started` / `model.output.completed` / `agent.run.completed` replay payload。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_activity_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/activity-all` Activity feed，断言 `/ui/activity` 列表、搜索 query 过滤、`activity-row` 到 `#/activity-detail/{event_id}` 的 handoff、`/ui/activity/{event_id}` detail/trace 展示、Activity metadata `run_id` 打开同一 `#/agents/{run_id}` Run Detail 并展示 `/runs/{run_id}/events` replay payload，包括 started event 的 `task_id` 和 completed event 的 result；同时覆盖 trace expand 全文展示、删除确认弹窗和 `DELETE /ui/activity/{event_id}` 后列表刷新。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_diagnostics_screenshot_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/diagnostics`，真实点击 Diagnostics 的本地截图摘要按钮，断言 `/screen/current` 被调用一次、页面展示截图尺寸/status，并渲染本地缩略图 `data:image/png;base64`；同一 smoke 还会真实点击运行诊断、断言 `/ui/native-agent/diagnostic-command` 收到当前默认诊断命令，再通过桌面 `copyText()` 复制 raw output 并验证剪贴板 payload。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_live2d_settings_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/settings/live2d`，通过桌面 `chooseLive2DArchive()` / `chooseLive2DModelDirectory()` picker 返回资源包 ZIP 和模型目录路径，点击 Live2D 资源导入与模型目录检查，最后保存设置；mock Bridge 断言 `/ui/live2d/archive/import`、`/ui/live2d/model-path/prepare` 和 `/ui/settings` 均收到预期 payload，且保存包含 `live2d_mode.model_path` 与 `display_mode=live2d`。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_launcher_session_summary_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，分别加载 `#/bubble` 与 `#/live2d`，断言 `/ui/launcher?mode=bubble` 的 `chat.recent_sessions` 会进入 Bubble 可见 `bubble-launcher-summary` 与 hidden session summary probe，并真实点击 `bubble-launcher-button` 覆盖 `/ui/launcher/ack` 且通过桌面 `openView('chat', { session_id })` 打开同一群聊 summary session；同时断言 `/ui/launcher?mode=live2d` 的 latest reply 会进入 Live2D latest reply probe 和同一组 recent session DOM 属性，启用 Live2D quick input，真实填写并点击 `live2d-launcher-quick-input-submit`，确认 `/ui/launcher/quick-message` 收到 trimmed 文本、`mode=live2d` 且非主动关怀场景不携带 session_id，随后验证 reply bubble 恢复展示 latest reply，并真实点击 `live2d-launcher-stage` 覆盖 Live2D toggle reply 的 `/ui/launcher/ack`；同一 smoke 还会把 mock Live2D `click_action` 切换到 open-chat，验证 stage 触发 `/ui/launcher/ack` 后通过桌面 `openView('chat', { session_id })` 打开同一 delegated summary session。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_proactive_tts_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/proactive-tts`，断言主动关怀 / TTS 设置页、runtime status、GPT-SoVITS 服务管理和音色包区域可用；随后真实点击 GPT-SoVITS 服务刷新、启动本地后台/自启、停止本地后台确认弹窗，覆盖 `/ui/tts/gpt-sovits/service-status`、`/ui/tts/gpt-sovits/service/install`、`/ui/tts/gpt-sovits/service/uninstall` 与服务状态 DOM；同一 smoke 还会真实点击屏幕权限检查、主动关怀立即测试、通过桌面 `chooseTtsVoiceArchive()` picker 返回路径导入音色包 ZIP，并保存测试 TTS，确认分别调用 `/ui/proactive/screen-permission/check`、`/ui/proactive/test`、`/ui/tts/voice-resource/import`、`/ui/settings` 和 `/ui/tts/test`，并验证页面展示 permission / proactive / voice import / spoken text 结果。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_agent_studio_agents_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/agents`，真实点击 Agent Studio 新建、通过桌面 `chooseAvatarImage()` picker 选择头像、点击 `agent-avatar-clear` 清除后再次选择头像、填写 Name/Nickname/Description/Category/Instructions/Persona/Output Contract 并保存；mock Bridge 断言 `/ui/agents` POST 收到定义 payload 和 avatar_url，随后真实编辑同一 Agent 并通过 `/ui/agents/{agent_id}` PATCH 保存更新，最后真实点击删除、确认弹窗和 DELETE route，验证列表刷新为空、编辑器回到新建草稿。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_agent_studio_skills_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/skills`，真实点击 Native Skill Library 同步，断言 sync result 与 source root 计数；随后选择导入文件夹、填写 Skill 安装命令并保存，mock Bridge 断言 `/ui/skills/install` 收到 command 和 folder_id；同一 smoke 会真实点击 Skill 卡片“打开路径”并断言桌面 `openPath()` 收到 local_path，再真实切换 enabled、移动文件夹、删除 Skill 并确认弹窗，断言 `/ui/skills/{skill_id}` PATCH/DELETE payload 和列表刷新；最后通过桌面 `chooseSkillSources()` picker 返回本地 Skill 来源，断言 `/ui/skills/import` 收到 source_path 和 folder_id，并渲染导入结果与 Skill card。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_agent_studio_skill_mount_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/agents` 并选择 Agent，断言 Mounted Skills 区域展示两个可挂载 Skill；随后真实点击 Native/Installed 筛选、搜索框和 folder filter，确认可见 Skill 数与挂载计数跟随筛选变化；再真实点击单个 Skill 覆盖 `/ui/agents/{agent_id}/skills` attach route，点击同一项覆盖 detach route；同一 smoke 还真实点击“全选当前筛选”和“清空当前筛选”，断言批量路径通过 `/ui/agents/{agent_id}` PATCH 写入 `skill_ids` 并刷新挂载计数。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_agent_studio_skill_folders_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/skill-groups`，真实创建 Skill 文件夹、重命名、点击“查看”跳转 Skill Library 并验证导入目标与列表筛选指向同一 folder，最后返回分组页删除文件夹并确认弹窗；mock Bridge 断言 `/ui/skill-folders` POST、`/ui/skill-folders/{folder_id}` PATCH/DELETE payload。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_agent_run_detail_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，先加载 approval_required Native Agent Run，断言 `agent-run-detail-approval`、`agent-run-approval-request`、approve/reject 操作和 `terminal.run` preview，点击 `agent-run-detail-approval-approve` 后 mock Bridge 通过 `/ui/runs/{run_id}/approval/approve` 投影 completed Run，并断言审批 UI 消失、result 与 `agent.tool.approval_required` / `agent.tool.approval_approved` / approved `agent.tool.call` / `agent.run.completed` replay，且 approval Run Detail replay payload 展示 goal、`terminal.run` 命令和 completed result；随后加载等待子 Agent 审批的 Workflow Run Detail，断言 `agent-run-detail-workflow-child-approval`、子 Run 工具 preview、批准/拒绝/取消/打开子 Run 操作，分别真实点击独立 Workflow child 的 `agent-run-detail-workflow-child-reject` 与 `agent-run-detail-workflow-child-cancel`，确认 `/approval/reject` / `/cancel` route 被调用、父 Workflow 投影为 cancelled、审批桥消失、Workflow step 为 cancelled 且 replay 包含 `workflow.run.cancelled`，并确认 reject/cancel 父 Workflow cancelled replay payload 展示对应 child Run id；再点击 `agent-run-detail-workflow-child-approve` 后通过子 Run approval route 完成父 Workflow，断言父 Run Detail 的 `workflow.run.child_resumed` / `workflow.run.resumed` / `workflow.node.artifact` / `workflow.run.completed` replay、Workflow Steps 和子 Run replay，并确认父 Workflow replay payload 展示 child Run id、artifact path 和 completed result，子 Agent Run replay payload 展示 goal、`terminal.run` 命令和 completed result；最后加载 completed Native Agent Run、TaskRunLink 投影、RunGroup、artifact 和 201 条 `/runs/{run_id}/events` replay facts，真实进入 Run History 管理态，点击全选与清空选择并断言 bulk actions / checkbox / 删除禁用态同步变化，再勾选一条 completed Run、点击批量删除并确认，mock Bridge 断言 `/ui/runs/{run_id}` DELETE 被调用且当前 Run Detail 保持选中；随后断言 initial replay 请求使用 `after_sequence=0&limit=200`、加载更多请求使用 `after_sequence=200&limit=200`、UI 合并第 201 条 replay、artifact preview、rerun route 与 rerun replay，并确认 rerun replay payload 展示 source Run id 与 rerun result。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_chat_run_detail_handoff_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/chat` 中一条普通 completed assistant 消息，消息 metadata 携带 `task_id`、`run_id`、`run_status=completed` 和 `source=main_chat`；脚本先真实点击 `chat-message-copy` 和 `chat-code-copy`，断言桌面 `copyText()` 分别收到 assistant content 与代码块内容，再真实点击 `chat-message-open-run-detail`，断言 Agent Studio 打开同一 Native Run 的 `agent-run-detail`，保留 Task / session metadata，并通过 `/runs/{run_id}/events` 展示 `agent.run.started` / `model.output.completed` / `agent.run.completed` replay；现在还会断言 `model.output.completed` 的 `output` payload 和 `agent.run.completed` 的 `result` payload 真实渲染到 Run Detail Execution 中，避免 Chat completed Run Detail handoff 只验证事件类型而漏掉 payload 展示。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_chat_agent_progress_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/chat` 中一条空内容、`processing` 状态的 assistant 消息，消息 metadata 指向 running Native Agent Run 并渲染 `chat-agent-run-progress-card`；脚本真实点击 `chat-agent-run-progress-open-run-detail`，断言 Agent Studio 打开同一 running Run Detail，保留 Task / session / RunGroup metadata，并展示 `agent.run.started` replay；现在还会断言 started replay payload 中的 `task_id` 和 goal 真实渲染到 Execution 内容，避免 running progress handoff 只验证事件类型。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- 可重复本地 UI smoke `node scripts/smoke_workflow_save_run_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/workflows`，真实点击 Workflow Studio 新建、Agent palette、Artifact 节点、填写 artifact path、Goal 和 `workflow-save-and-run`；mock Bridge 断言 `/ui/workflows` 保存的画布包含所选 Agent 节点和 Artifact 节点，`/ui/workflow-runs` 使用保存返回的 `workflow_id`、携带 `client_run_id` 和用户 Goal，前端随后自动打开同一 Workflow Run 的 Run Detail，并通过 `/runs/{run_id}/events` 展示 `workflow.run.started` / `workflow.node.agent.completed` / `workflow.node.artifact` / `workflow.run.completed` replay，再点击 artifact item 读取 `/ui/runs/{run_id}/artifacts/{path}` 并展示 preview；同一 smoke 还会创建 Approval → Artifact Workflow，填写审批 criteria 和 artifact path，保存运行后断言 Run Detail 显示 `workflow.approval` 审批卡、`workflow.node.approval_required` replay，真实点击批准后断言 `workflow.node.approval_approved` / `workflow.node.artifact` / `workflow.run.completed` replay 和 approved artifact preview；现在还会断言普通 Workflow artifact/result、approval criteria、approved artifact/result 等 replay payload 真实渲染到 Execution 内容，避免 Workflow Run Detail 只验证事件类型而漏掉 payload 展示。source-level pytest guard 和 release verifier 均锁定该 smoke，macOS release workflow 会在打包前运行。
- 可重复本地 UI smoke `node scripts/smoke_workflow_management_ui.mjs` 会启动 mock Bridge、Vite dev server 和 Electron BrowserWindow，加载 `#/agents/workflows`，真实进入 Workflow 管理态、点击全选与清空选择并断言批量操作栏、checkbox 和批量删除禁用态同步变化；随后勾选列表 checkbox、点击批量删除并确认，再打开剩余 Workflow 走单个删除确认；mock Bridge 断言 `/ui/workflows/{workflow_id}` DELETE 按批量删除和单个删除顺序各触发一次，前端列表刷新为空且编辑器回到新建草稿。source-level pytest guard、packaged app selector verifier 和 macOS release workflow 均锁定该 smoke。
- Chat 图片附件的大图预览 modal / stage / close action 已补稳定 `data-testid`，本地 Electron smoke 现在也断言“点击消息附件 → 预览打开 → 关闭预览”的交互闭环；同一 smoke 还锁定 composer preview 的 id/mime/size/width/height、提交给 `/ui/chat/messages` 的 client attachment id/mime/size/dimensions/data URL，以及消息附件 DOM 的 id/kind/mime/name/size 元数据，避免图片 UI 上传路径丢失附件 handoff 信息。release verifier 现在还会检查 `scripts/smoke_chat_image_attachment_ui.mjs` 必须保留 Chromium CDP `DOM.setFileInputFiles`、真实文件路径和四图 file input 覆盖，防止该 smoke 退化为只 dispatch change 的弱模拟。
- Bubble / Live2D launcher 现在锁定更多浏览器 E2E 断言点：Bubble button/status/summary、Live2D stage/canvas/fallback/resource hint/reply/quick input，以及 hidden session summary probe 的 latest reply/status/recent sessions 和 `data-task-id` Task handoff 元数据；本地 Electron smoke 已覆盖 Live2D 快速输入提交路径，后续仍可继续把群聊/自动委派/会话总结进入 launcher 的 source Browser 数据源证据做厚。
- Live2D settings 本地 Electron smoke 现在不只覆盖 ZIP 导入、模型目录 prepare 和保存，也真实点击“打开导入目录”和“打开 Releases”，断言前端分别调用桌面 `openPath(default_assets_root)` 与 `openExternalUrl(releases_url)`；source-level guard 同步锁定 `live2d-open-assets-dir` / `live2d-open-releases` selector 和桌面 API 调用。
- Secret 清洗已补主路径回归、旧 chat.db 迁移清洗、标准 logging、桌面后端 excepthook、crash 文件生成扫描、HTTPException detail、UI JSON error/message、provider catalog 失败缓存、artifact 文件清洗、artifact.write secret payload 写入前拒绝与落盘扫描、provider/tool exception 端到端落盘扫描、Workflow child Agent provider exception 到父 Workflow projection / RunEvent / runtime DB 的清洗、terminal / workspace.write_patch approval secret payload 审批前拒绝与落盘扫描、approved terminal 非零退出 stdout/stderr 失败投影与落盘扫描、approval reject/cancelled RunEvent payload 清洗、Workflow continuation failure replay payload 清洗和默认 runtime 落盘扫描；仍建议继续补真实 provider / 外部工具集成环境下的异常日志联调。
- `workspace.write_patch` 已收敛为单文件 UTF-8 unified diff patch；content 全量写入已从 tool schema 移除，并在 validator / ToolBroker direct 入口拒绝。
- Runtime 发起的 skill 安装子进程与手动 TTS command provider 已复用敏感环境变量清洗，避免 `SSH_AUTH_SOCK`、`GITHUB_TOKEN`、云厂商凭据和 `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 从旁路传入外部命令；`terminal.run`、skill install 与 TTS command 现在使用同一套 `scrubbed_subprocess_env()` helper。
- release/alpha/stable 源码级 guard、release-facing verifier、packaged app resources scan、签名导入/签名构建 workflow guard、签名脚本 runtime options / entitlements / verify guard、Gatekeeper 首启说明/当前 notarization 状态/屏幕录制权限 release notes guard、macOS hardened runtime / entitlements / usage descriptions guard、release metadata JSON 发布 guard、latest JSON 更新字段 guard、release DMG/SHA staging/upload guard、关键 smoke tests 构建前执行顺序 guard、opt-in 真实 provider streaming/tool-call smoke workflow guard 与 release 目录 binary-safe artifact scan 已覆盖；workflow 会排除本地 `node-pty/build` native artifact 并只打包 clean prebuilds，release verifier 也会阻断 tracked `.vite` cache、`apps/frontend/dist`、`apps/frontend/dist-electron`、release artifact 路径和内容中的旧产品身份 token、`HermesRuntime` / `hermes_runtime`、`HermesExecutor`、旧 Hermes Agent / capability resolver、旧 Hermes setup/doctor/installer/CLI/bridge/env 入口 token（含 `HERMES_HOME` / `HERMES_CONFIG` / `HERMES_PROFILE`）、旧 `run_yachiyo`/delegation/group dispatch/workspace init 协议 token、release workflow 丢失 Task API protocol/AppState task lifecycle/TaskRunner native approval roundtrip/TaskRunner approval timeout projection/TaskRunner image attachment Native runtime flow/TaskRunner auto delegation Native runtime flow/TaskRunner group dispatch summary Native runtime flow/TaskRunner direct group summary Native runtime flow/TaskRunner rejected direct group summary Native runtime flow/TaskRunner proactive screenshot Native runtime flow/Native approval timeout replay idempotency/main chat approved tool failure replay/main chat repeated approval idempotency/durable approval claim across runtime instances/ApprovalResumeCoordinator approved tool resume flow/ApprovalResumeCoordinator fatal tool failure boundary/ApprovalResumeCoordinator custom API resume flow/approval approve route idempotency/approval reject route idempotency/concurrent Run cancellation idempotency/UI Run cancel route idempotency/Chat cancel late-output HTTP roundtrip/NativeAgentExecutor Task-to-Run boundary/NativeAgentExecutor 多轮上下文过滤与 context size limit/NativeAgentExecutor image attachment payload/TaskRunLink replay projection/Native runtime shutdown cancellation facts/Native runtime shutdown resource closure/write_patch boundary validation before approval/ToolBroker symlink workspace escape guard/workspace.write_patch schema validation contract/workspace.write_patch single-file hash application/workspace.write_patch hash and context mismatch refusal/workspace.write_patch multifile and binary patch refusal/terminal workspace argv and env scrub/terminal startup structured sanitized errors/terminal output redaction and truncation/terminal timeout process-group kill/provider reasoning privacy non-stream direct chat and main chat loop/OpenAI-compatible streaming provider contracts/legacy Hermes kernel removal/Native runtime injection boundary/AppRuntime Native service aggregation/desktop backend Native startup/desktop launcher startup wiring/shell app Electron entrypoint/desktop MainWindow API modes/model capability and image input guards/model profile credentials and provider contracts/provider catalog metadata and cache redaction/packaged backend build command guards/release-like build metadata guards/release-like CredentialStore guards/runtime secret redaction verifier/security logging redaction/截图/主动关怀/launcher notifications and proactive attention/ChatSession/ChatStore persistence and redaction/ChatBridge session summary/Chat API/ActivityStore feed and redaction/UI Bridge/成熟 UI preservation/UI flow contract/Bridge Host Origin session token guard/Bridge loopback bind guard/mutating Bridge token guard/Chat image HTTP roundtrip/Chat image NativeRunEngine replay roundtrip/Chat approval failed tool HTTP roundtrip/Agent approval approve/reject/cancel Run Detail HTTP roundtrip/Workflow approval approve/reject/cancel Run Detail HTTP roundtrip/Workflow child approval approve/reject/cancel Run Detail HTTP roundtrip/Workflow rerun artifact replay HTTP roundtrip/group chat Native summary flow/auto delegation Native summary flow/TTS/desktop display mode normalization/settings effect policy/Live2D smoke 覆盖、真实 provider tool-call smoke 的 `workspace_read` 名称、`README.md` 参数 substring 和 `path=README.md` JSON 字段断言、opt-in 真实 provider smoke 入口和 packaging config 丢失 `.vite` 排除；本地 unsigned `.app` / DMG 产物已验证不包含旧产品身份 token。Electron Framework 内部自带的通用 `Hermes` 字符串不属于本项目产品身份或执行内核残留。
- release workflow 打包后 `Verify packaged app resources` 现在会用 `--check-packaged-app` 验证 `.app` bundle 结构，确认 `Info.plist` 产品身份、bundle id、productivity category、Apple Events / Documents / Downloads / Microphone 权限说明、主 executable、`Resources/backend/oha-yachiyo-backend` 与 `Resources/app.asar` 都存在且关键 executable 可执行，再执行 packaged resources binary scan。
- 新增本地 RC 验收入口 `python scripts/verify_release_candidate.py --require-artifacts`：先运行 source-level release guard，再对 `dist/backend`、`dist/electron` 和 `release` 执行 binary/package verifier；需要把 Electron UI smoke 纳入本地 RC gate 时可加 `--run-ui-smoke`。该脚本会列出 Gatekeeper 首启、Bridge 启动隔离、屏幕录制权限和真实 provider smoke 等人工复验项，并可写出 `release/rc-verification.json` 作为可归档验收报告；release workflow smoke 也会运行其单测，release workflow 会在生成 release metadata 后、上传 DMG 前运行该 RC gate 并上传 report，release verifier 会阻断 RC gate 测试、workflow 步骤或 report 输出漏接入发布门禁。
- 2026-06-12 起收尾切换为验收驱动：先跑 release / RC gate 找真实阻断项，再修阻断项，不再继续做低收益 runtime 微边界拆分。本轮 `python scripts/verify_release_artifacts.py` 已通过；`python scripts/verify_release_candidate.py --report-json tmp/release-candidate-dry-run.json` 的 source release guards 通过，但自动拾取到本机旧 `dist/electron` 并因 `app.asar` 缺最新 packaged selector 失败，证明当前旧 `.app` 不能计作 RC 产物。新增 `python scripts/verify_release_candidate.py --source-only --report-json tmp/source-only-rc.json` 用于未重新打包时只验证源码级 release guard；最终 RC 仍必须重新打包后运行 `--require-artifacts`。
- packaged app verifier 现在还会扫描 `Resources/app.asar` 原始字节，确认 Chat 图片上传/预览/消息附件/image viewer open-close、群聊创建/Agent 成员选择/群组 follow-up 状态/Activity Run Detail handoff、Diagnostics 本地截图摘要/运行诊断/复制输出、Live2D settings 资源导入、Bubble / Live2D session summary、Live2D quick input、Proactive TTS settings/status/result、Chat 取消、Chat 审批 approve/reject/reveal/open-run、Chat completed message Run Detail、Chat Agent progress Run Detail、Agent Studio agents 定义 CRUD/头像 picker、Agent Studio Skill Library sync/install/update/delete/source picker/open path、Agent Studio Skill mounting attach/detach/bulk update、Agent Studio Skill folder create/rename/open/delete、Run Detail replay/artifact/rerun/Run History 管理删除、Workflow child approval approve/reject/cancel/open-run 和 Workflow Studio 编辑/save-and-run/Run Detail 投影/管理删除的关键 UI selector 进入发布产物；扫描范围也会动态纳入 `scripts/smoke_*_ui.mjs` 中显式使用的 `data-testid`，避免后续 Browser/Desktop E2E 所依赖的成熟 UI 入口在 build/packaging 阶段被剥掉。
- release artifact verifier 单测现在会直接从 release workflow 解析十九个 Electron UI smoke 脚本，并通过动态 packaged selector gate 验证这些脚本显式使用的 `data-testid` 都会进入 `.app` 产物扫描范围，避免后续 smoke 继续新增成熟 UI 入口时漏同步 packaged app selector gate。
- release artifact verifier 现在会动态发现 `scripts/smoke_*_ui.mjs`，要求 release workflow 在 packaging 前逐个执行这些 Electron UI smoke；单测会模拟新增成熟 UI smoke 未接入 release workflow 的场景并报错，避免后续新增 Browser/Desktop 回归脚本但发布门禁漏跑。
- release verifier 现在还会逐项检查 release workflow 的必备 smoke guard 文本出现在 packaged backend / DMG build 之前；即使 smoke 文本仍存在，只要被移动到打包之后也会被阻断。
- release workflow smoke 现在会在 packaging 前直接运行 Chat 图片附件、Chat completed message Run Detail handoff、Chat Agent progress Run Detail handoff、Chat 取消、Chat 审批、Chat delegated summary、群聊 summary、Activity feed/detail、Diagnostics local screenshot、Live2D settings、launcher session summary、Proactive TTS、Agent Studio agents 定义 CRUD、Agent Studio Skill Library、Agent Studio Skill mounting、Agent Studio Skill folders、Agent Run Detail replay / Workflow child approval、Workflow save-and-run 和 Workflow management/delete 十九个 Electron UI smoke；release verifier 会阻断 workflow 丢失这些关键 smoke。
- release workflow 的 opt-in 真实 provider 文本流 smoke 现在要求 `finish_reason=stop`，tool-call smoke 要求 `finish_reason=tool_calls` 且要求 synthetic `workspace_read` tool-result 后第二轮 stream 输出内容与 `finish_reason=stop`；release verifier 会阻断丢失任一断言的 workflow，避免真实 provider 未完成标准结束协议或不接受 tool-result history 时误过发布门禁。release verifier 也会要求 workflow 在 `OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL` 或 `OHA_YACHIYO_SMOKE_API_KEY` 任一缺失时显式 skip 并输出 opt-in secret 未完整配置提示，避免无凭据环境误跑真实 provider smoke。
- NativeRunEngine 与 opt-in streaming smoke helper 现在也接受 OpenAI-compatible gateway 预处理后的单数 `tool_call` frame：`choices[].delta.tool_call` / `choices[].message.tool_call` 会和既有 `tool_calls[]` 分片一样归并，进入 `workspace.read` 执行与 tool-result provider history，仍只落 `agent.tool.call` / `model.output.completed` 完成态 facts，不写 token 级 delta；smoke helper 摘要继续不打印 raw arguments。该 NativeRunEngine 产品路径回归已纳入 release workflow smoke，release verifier 会阻断发布门禁漏跑单数 SSE tool-call frame 覆盖。
- NativeRunEngine Agent Run 现在也覆盖 Responses `output_item.done` message snapshot、`content_part.done` snapshot、`refusal.done` snapshot、reasoning privacy、provider message tools、OpenAI SDK object tools、object-shaped arguments、split/coalesced/multiline SSE content、Responses call_id history 和多 tool call history；对应测试已纳入 release workflow smoke 和 release artifact verifier。
- NativeRunEngine Agent Run 与 opt-in streaming smoke helper 均已覆盖无 `index`、交错到达但带不同 `id` 的 SSE tool-call delta 按 id 归并，避免真实 provider 省略 index 时把多个工具调用拼接到同一个 call；公开 smoke summary 继续只输出参数长度，不回显 raw arguments。
- release artifact verifier 现在会动态发现 Main Chat 与 Agent Run provider contract tests，并要求它们在 packaged backend / DMG build 之前运行；Agent Run discovery 已覆盖 `http_sse`、`streaming`、`responses`、`function_call`、`provider_message`、`sdk`、`reasoning` 和 `refusal` 类测试，避免后续新增 provider 合同但忘记接入 release workflow。
- release verifier 现在除了 release / alpha / stable metadata，也会模拟 `OHA_YACHIYO_PACKAGED_BUILD=1`，确认 packaged build env 即使带 `OHA_YACHIYO_DEV=1` 也不能启用 development features、Bridge debug routes 或 `DevFileCredentialStore` fallback。
- release workflow smoke 现在也强制包含 Bridge debug routes release metadata / packaged build guard，直接覆盖 `debug_routes_enabled()` 在 release-like metadata 与 packaged env 下不会因 `OHA_YACHIYO_DEV=1` 被重新打开。
- release workflow smoke 现在也强制包含 approved terminal failure output redaction 回归，确保批准后的 `terminal.run` 非零退出不会把 stdout / stderr secret 写入 Run projection、RunEvent 或 runtime SQLite。
- release workflow smoke 现在也强制包含 skill install env scrub 回归，确保 Runtime 发起的 Skill 安装子进程不会继承 `SSH_AUTH_SOCK`、`GITHUB_TOKEN`、云厂商凭据或 `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD`。
- release workflow smoke 现在也强制包含 TTS command env scrub 回归，确保本地手动 TTS 命令不会继承 `SSH_AUTH_SOCK`、`GITHUB_TOKEN`、云厂商凭据或 `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD`。
- release workflow smoke 现在也强制包含主聊天 provider exception / tool exception redaction 回归，以及 Workflow child Agent provider exception redaction 回归，避免异常文本中的 secret 进入 Run projection、父 Workflow projection、RunEvent、tool result message 或 runtime SQLite。
- release workflow smoke 现在也强制包含 main chat approval resume claim boundary 回归，确认 `main_chat_run` 批准恢复也通过 `ApprovalResumeCoordinator.claim_and_project_approved_tool()` 执行 claim/projection。
- release workflow smoke 现在也强制包含 tool approval shared context boundary 回归，确保主聊天与 Agent Run 的 tool approval reject / timeout 继续共享 `ToolApprovalTransitionContext` 解析 pending tool request。
- release workflow smoke 现在也强制包含 ApprovalResumeCoordinator claim projection boundary 回归，确保批准后的 pending approval claim 与 running projection 不回退到 NativeRunEngine 私有分支。
- release workflow smoke 现在也强制包含 ToolApprovalClaimProjection running payload boundary 回归，确保 approved-tool claim 成功后的 running projection payload 继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 ToolApprovalContinuationOutcome resume state projection boundary 回归，确保 approved-tool resume 后 completed / approval_required / failed outcome 分派继续由显式 outcome boundary 维护。
- release workflow smoke 现在也强制包含 ToolApprovalExecutionFailureProjection timeline boundary 回归，确保 approved-tool fatal failure 的 timeline replay payload 继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 NativeRunEngine approval resume claim boundary 回归，确认 standalone Agent approval resume 通过 `ApprovalResumeCoordinator.claim_and_project_approved_tool()` 进入 approved-tool claim/projection 边界。
- release workflow smoke 现在也强制包含 approved-tool resume wait / failure projection 边界回归，确认主聊天与 Agent Run 的连续审批、批准后失败投影不回退到 approve 分支私有实现。
- release workflow smoke 现在也强制包含 ToolApprovalExecutionRequest approved call boundary 回归，确保 approved-tool 调用参数继续由显式 request boundary 维护。
- release workflow smoke 现在也强制包含 ToolApprovalExecutionFollowup remaining-tool boundary 回归，确保 approved-tool 成功后的 tool-result message 与 remaining tool requests 续跑参数继续由显式 follow-up boundary 维护。
- release workflow smoke 现在也强制包含 ToolApprovalCustomApiContinuationRequest handoff boundary 回归，确保 approved-tool 后 custom API 模型续跑参数继续由显式 request boundary 维护。
- release workflow smoke 现在也强制包含 ApprovalResumeProjectionCoordinator resume state projections 回归，确保 approved-tool resume 的 running / completed / approval_required / failed 投影继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 ToolApprovalResumeContext pending payload parsing 回归，确保 approved-tool resume 上下文继续统一解析 messages、tool request、remaining requests、next iteration、timeline、artifacts 和 budget 输入。
- NativeRunEngine 的主聊天与 standalone Agent approved-tool resume 现在共用 `_resume_approved_tool_run()` 恢复步骤；主聊天仍保留 `model.output.completed` / running Task 投影，Agent Run 仍保留 running group / parent Workflow child projection 和 completed/failed group 投影，但 claim、tool-result follow-up、二次审批、失败清洗统一由同一内部步骤编排。release workflow 已锁定的 main chat / Agent claim-boundary 回归现在也显式断言两条路径都经过该共享恢复步骤。
- release workflow smoke 现在也强制包含 WorkflowParentResumeCoordinator completed child handoff / replay idempotency 回归，确保 completed child 只恢复父 Workflow 一次，并写入 child completed 与 workflow resumed replay facts。
- release workflow smoke 现在也强制包含 Workflow child run replay payload projection 回归，确保 child run 状态、result preview、artifact count 和 node metadata payload 继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 WorkflowParentResumeCoordinator child approval replay idempotency 回归，确保重复 child approval_required update 不会重复投影父 Workflow replay fact 或重复更新父 Run / RunGroup。
- release workflow smoke 现在也强制包含 WorkflowParentResumeCoordinator child cancellation / failure replay idempotency 回归，确保重复 child cancelled / failed update 不会重复投影父 Workflow replay fact 或重复更新父 Run / RunGroup。
- release workflow smoke 现在也强制包含 Workflow cancellation target projection 回归，确保 pending approval / waiting child 两类取消目标继续由显式 target boundary 生成 timeline payload 和 result 文本。
- release workflow smoke 现在也强制包含 Run cancellation update projection 回归，确保普通 Run / Workflow Run 取消后的状态、result、timeline、artifact 和 pending approval 清理字段继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 Workflow agent-node child run handoff 回归，确保 child Agent、child goal、upstream context、node metadata 和 replay payload 继续由显式 handoff 边界维护。
- release workflow smoke 现在也强制包含 RunTransitionProjectionCoordinator child and workflow group projection 回归，确保 child Run 状态变化和 root Workflow cancelled RunGroup 投影继续由显式 transition boundary 维护。
- release workflow smoke 现在也强制包含 sensitive `client_run_id` rejection 回归，确保外部幂等键误带 API key / token 时不会进入 `runs.client_request_id` 持久化投影。
- release workflow smoke 现在也强制包含 sensitive HTTP `Idempotency-Key` 回归，确保 Chat route 不创建消息/Task，通用 `/runs`、Agent Run 和 Workflow Run route 不创建 Run / `runs.client_request_id`，Agent/Workflow route 的错误响应也不会回显 header secret。
- release workflow smoke 现在也强制包含 WorkflowCancellationProjectionCoordinator child cancellation projection 回归，确保父 Workflow 取消等待中的子 Agent Run 时继续写入 child cancellation replay fact，并保留 workflow node metadata / child outcome 投影。
- release workflow smoke 现在也强制包含 WorkflowContinuationCoordinator approval pause / resume、background failure projection 与 artifact node handoff 回归，确保 Workflow approval node、批准后 continuation、异步后台失败投影和 artifact 写入继续走显式 step continuation 边界。
- release workflow smoke 现在也强制包含 Workflow continuation failure projection boundary 回归，确保 Workflow continuation 异常时的 failed timeline、RunEvent payload 和 Run update 字段继续由显式 projection boundary 维护。
- release workflow smoke 现在也强制包含 WorkflowContinuationCoordinator failure redaction boundary 回归，确保 Workflow continuation 未知节点失败不会把 node kind 中的 secret 写入 Run projection、RunEvent、timeline 或 RunGroup summary。
- release workflow smoke 现在也强制包含 `TaskRunLinkRepository` projection boundary 回归，确保 Task↔Run link、Run status projection 和 replay `last_event_sequence` 继续由显式边界维护。
- release workflow smoke 现在也强制包含 `RunArtifactRepository` redaction / file read 和 `RunRepository` artifact cleanup callback 回归，确保 artifact 投影清洗、文件读取清洗和 Run 删除文件清理不从发布路径回退。
- release workflow smoke 现在也强制包含 `RunGroupRepository` insert / summary redaction 和旧库 secret scrub 回归，确保 root RunGroup title/source/workspace_dir 和状态 summary 的新写入与升级迁移不会把用户 goal、source 或路径中的明显 secret 留在当前 SQLite 文件中。
- release workflow smoke 现在也强制包含 RunEvent 并发写入 sequence / replay cursor projection 回归，确保 `RunEventRepository.append()` 与 TaskRunLink cursor projection 在共享 SQLite connection 上不会重新出现并发事务交错。
- release workflow smoke 现在也强制包含 RunEvent HTTP replay pagination/filtering 回归，确保 `/runs/{run_id}/events` 的 `after_sequence`、limit clamp、user-visible 默认过滤和 secret hiding 不从发布路径回退。
- release workflow smoke 现在也强制包含 runtime SQLite database guard，确保 schema metadata、foreign keys、WAL、busy timeout 和 Run 删除后的 TaskRunLink cascade 不从发布路径回退。
- release workflow smoke 现在也强制包含 Workflow save-and-run latest canvas route contract，确保 Workflow Studio 保存草稿后必须用最新 `workflow_id` / canvas 创建 Workflow Run，并继续覆盖 step approval、artifact 和 RunEvent replay。
- release workflow smoke 现在也强制包含 Workflow approval shared context boundary 回归，确保 Workflow approval approve / reject / timeout 继续共享 `WorkflowApprovalTransitionContext` 解析 pending approval 字段。
- release workflow smoke 现在也强制包含 Workflow approval resume context boundary 回归，确保 Workflow approval approve 恢复时的 context、next index、timeline 和 artifact 继续由显式上下文解析。
- 新 Agent Run 的 runtime metadata / prompt / compiled timeline 已从旧 `yachiyo_agent` / `Yachiyo Agent Runtime` 收敛为 `oha_agent` / `Oha Agent Runtime`；源码级 legacy kernel guard 和 release artifact verifier 的 binary scan 都会阻断 `yachiyo_agent` 与 `Runtime: Yachiyo Agent Runtime` 旧 context artifact runtime 标记回归，同时避免误伤合法的 `Oha-Yachiyo Agent Runtime` 产品文案。
- Electron 桌面 Bridge 重启会轮换 session token；前端 `restartDesktopBridge()` 现在会清空 renderer 侧 cached Bridge token，确保重启后的 mutating request 重新从 preload 读取新 token。
- CredentialStore release/packaged guard 现在同时覆盖 direct DevFile fallback 禁用与 `create_credential_store()` factory 选择：即使 `OHA_YACHIYO_DEV=1`，release/alpha/stable metadata 或 packaged build env 也不会选择 development file fallback；macOS release-like build 仍选择 Keychain。
- release workflow 的 app build metadata 生成已从内联 JSON 收敛到 `python scripts/prepare_app_build_metadata.py`，本地 RC 重新打包前可用同一脚本刷新 `.app` 与 packaged backend 共用 metadata；release verifier 会阻断 workflow 退回非脚本路径或漏跑脚本单测。
- 本轮已用当前 commit metadata 临时刷新本地构建、重建 `dist/backend/oha-yachiyo-backend` 与 `dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg`。首次 `python scripts/verify_release_candidate.py --require-artifacts --report-json tmp/rc-verification-local.json` 暴露 packaged `app.asar` 缺 `bubble-launcher-*` / `live2d-launcher-*` session summary 具体 selector；已把 Launcher session summary probe 从模板字符串 selector 改为显式 selector 常量，重打包后该 RC artifact gate 通过。`node scripts/smoke_launcher_session_summary_ui.mjs` 也通过，确认 Bubble / Live2D session summary selector 仍支撑真实 Electron 交互。随后提升权限运行 `python scripts/verify_release_candidate.py --require-artifacts --run-ui-smoke --report-json tmp/rc-verification-local-ui.json`，source guards、built artifact guards 和十九个 Electron UI smoke 全部通过；剩余仍需人工 Gatekeeper / 屏幕录制权限复验，以及具备真实 provider credentials 时运行 opt-in streaming/tool-call provider smoke。
- 桌面 `.app` 已实际启动并验证 bridge；主要 UI 页面已有静态入口 guard、浏览器级 route smoke、source Browser 按钮级交互 smoke 和十九个本地 Electron UI smoke。剩余 UI 验收重点不再是入口是否存在，而是当前 Browser runner 尚不能完整驱动的真实图片 file upload、真实外部 provider 环境、以及 release candidate 包的跨页面人工复验。

## 下一步建议

1. 做 PR-3 成熟功能 UI 级回归：
   - Chat UI 图片附件的真实 file upload 仍是最大浏览器级缺口；当前图片已有 source Bridge E2E、HTTP route roundtrip、TaskRunner image roundtrip、RunEvent replay 和本地 Electron smoke 的 CDP file input / 附件预览 / 提交闭环，且 release verifier 会阻断该 Electron smoke 退化，但 Codex in-app Browser 当前缺少 `setInputFiles()` / 虚拟剪贴板能力，不能直接计作完整 Browser upload E2E。
   - 群聊、自动委派、会话总结、Agent Studio、Workflow、Run Detail、approval UI、主动关怀、本地截图、手动 TTS 和 Live2D 已有 source Browser / Electron smoke / packaged selector gate 的组合覆盖；后续重点是 release candidate `.app` 内跨页面人工复验，而不是继续只补静态 selector。

2. 做 NativeRunEngine 组件边界收敛：
   - 逐步把 approval resume execution 编排拆成可测试的恢复步骤，保持 API 行为不变。
   - 继续审计 Workflow/Agent child-run 编排，避免 `NativeRunEngine` 重新变成单体。
   - 保持现有 API 不变，只减少单类内聚。

3. 做 streaming/event replay 硬化：
   - 在具备真实 provider credentials 的环境运行 `.github/workflows/release-macos.yml` 中 opt-in 的 `scripts/smoke_openai_compatible_stream.py` 文本流与 tool-call 流，确认真实网关也满足 `finish_reason`、`workspace_read` 参数和 tool-result follow-up 合同。
   - contract tests 已覆盖主流 chunk 形态；后续只在发现真实 provider 新 frame 形态时继续补 NativeRunEngine / smoke helper 对称回归。
   - RunEvent replay/projection 已有 HTTP pagination/filtering、Run Detail、Workflow child approval、rerun/artifact 和 packaged selector gate 覆盖；剩余重点是 release candidate UI 中的人工抽样复验。

4. 做最终发布验收切片：
   - release/alpha/stable 的旧产品身份扫描、debug routes guard、dev credential fallback guard、release metadata、packaged resources scan 和 generated artifact guard 已由 `scripts/verify_release_artifacts.py` 与 release workflow 锁定。
   - 当前免费分发策略是 `.app` 自签名、DMG 不签名且不 notarize，并在 release notes 中明确 Gatekeeper 首启提示和屏幕录制权限；如果后续引入 Apple Developer ID，再新增 notarization / stapling / `spctl` 实测切片。
   - 最终 RC 前仍需对实际产出的 `.app` / DMG 运行 `python scripts/verify_release_candidate.py --require-artifacts --run-ui-smoke`，并人工确认首次启动文案与权限提示；当前本机已有旧 `dist/electron` 产物会被该脚本识别为 stale artifact 并报出缺少最新 packaged selector，需要重新打包后再计作 RC 通过。
