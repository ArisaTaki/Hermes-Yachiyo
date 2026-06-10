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
  - 负责 runs 表 get / list / insert / update / idempotency lookup。
  - 保留 `NativeRunEngine` 公开方法作为薄委托，路由和业务调用不变。
  - update 继续统一处理 secret redaction、timeline/artifact/pending approval 投影同步。

- `RunEventRepository`
  - 负责 RunEvent durable append / replay list。
  - sequence 分配在 `BEGIN IMMEDIATE` 事务内完成。
  - 默认 list 只返回 user-visible 且非 secret events。
  - limit clamp 保持默认 200、最大 1000。

- `ApprovalRepository`
  - 负责 `run_approvals` pending / resolved 投影同步。
  - 保留 approve / reject 现有幂等业务语义。

- `ApprovalCoordinator`
  - 负责 approval approve / reject / timeout 的通用 lifecycle transition。
  - 统一写入 approval timeline、RunEvent 和 pending approval 清理。

- `ApprovalResumeCoordinator` / `ToolApprovalResumeContext`
  - 负责批准后恢复时的已批准工具调用执行。
  - 主聊天和 Agent Run 的工具审批恢复共用同一个 resume context 和 coordinator。
  - 保留 `NativeRunEngine` 对最终模型继续执行和 Run 状态落库的编排职责。

- `WorkflowParentResumeCoordinator`
  - 负责子 Agent Run 状态变化后标记父 Workflow running / approval_required / failed / cancelled / resumed。
  - 负责合并子 Run 结果、子 artifact references、父 Workflow timeline 和 RunGroup 状态更新。

- `WorkflowContinuationCoordinator`
  - 负责 Workflow start / agent / approval / artifact 节点执行。
  - 负责 Workflow 节点 timeline、child Agent Run 创建、approval pause、artifact write、completed/failed 状态落库。
  - `NativeRunEngine._continue_workflow_run()` 保留为薄 wrapper，成熟调用点不变。

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
- `RunGroupRepository` 直接覆盖 child membership、list/get、status/summary update 和空 group 清理。
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
- ChatAPI 主聊天审批投影修复 `_linked_main_chat_run_for_task()` 错误 staticmethod，确保 RUNNING Task 可通过当前 runtime service 的 Task↔Run link 读取 main_chat_run，并把 `approval_required` 稳定投影到 ChatSession metadata、ActivityStore 和 `approval_count`。
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
.venv/bin/python -m pytest tests/test_executor.py::TestNativeAgentExecutor::test_run_delegates_yachiyo_agent_before_final_reply tests/test_executor.py::TestNativeAgentExecutor::test_group_mode_returns_dispatch_for_chat_layer tests/test_executor.py::TestExecutorHelpers::test_run_oha_delegation_accepts_structured_directive tests/test_agent_runtime.py::test_delegation_targets_and_delegate_run -q
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

本轮补一条更接近真实 provider 差异的 NativeRunEngine 回归：fake HTTP provider 的 SSE stream 可以在 `choices[].delta.content` / `choices[].message.content` 中返回 OpenAI-compatible content-part 数组，Runtime 仍会合并为单条可见 `model.output.completed` RunEvent，不写 token/delta 级事实。

随后检查真实 provider smoke 环境变量，`OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL`、`OHA_YACHIYO_SMOKE_API_KEY` 均未设置，因此本轮未进行外部 provider 调用。作为可重复替代，补充 smoke helper contract：`scripts/smoke_openai_compatible_stream.py` 能接受同样的 content-part array stream，并在 `--require-content` / `--expect-finish-reason` 下正确统计内容长度而不打印原文；后续也已覆盖 content-part 数组中的 `reasoning` / `thinking` 私有片段只计入 reasoning 长度、不进入可见 content。

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

## 设计书差距

### 已基本满足

- 不再把 Hermes 作为默认或回退执行路径。
- 成熟业务层没有被删除或 Run-only 重写。
- `NativeAgentExecutor` 维护 Task 到 Run 的映射。
- `NativeRunEngine` 承载模型、RunEvent、工具、审批、取消和预算。
- Hermes 执行内核入口已有源码级 guard：`apps` / `integrations` / `packages` / `scripts` / `pyproject.toml` 不得重新出现 `HermesExecutor`、Hermes CLI/stream/installer/readiness、`hermes_profile`、旧 `run_yachiyo*` / `yachiyo_delegation` / `yachiyo_group_dispatch` 和旧 workspace/product token。
- `builtin:yachiyo-main` 已作为系统虚拟 Agent 暴露给 Runtime / Agent Studio 读取面，使用默认 Chat ModelProfile，不落普通 agents 表，不可作为普通 Agent 创建、修改或删除，并被排除出自动委派目标。
- RunRepository、RunGroupRepository、RunEvent、approval projection、ApprovalCoordinator、ApprovalResumeCoordinator、WorkflowParentResumeCoordinator、WorkflowContinuationCoordinator、RunArtifactRepository、tool descriptor 和 policy gate 已开始从 `NativeRunEngine` 中显式拆边界。
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
- Secret 持久化前清洗已覆盖 ChatSession、ChatStore、旧 chat.db 迁移、ActivityStore、RunEvent payload、Run projection、Run artifact projection、terminal/tool 输出、terminal 子进程 env 继承边界、provider/tool exception projection、自动委派 summary runtime error projection、标准 logging 输出、桌面后端未捕获异常输出、Bridge HTTPException detail、UI JSON error/message、provider catalog 失败缓存、ModelProfile/NativeRunEngine failure projection，以及 ModelProfile / Agent Studio 旧明文 API Key 迁移后的 raw SQLite 清理；Chat transcript 清洗不折叠空白、不截断正文。
- 主聊天 PR-1 上下文合同已有 executor 级回归：多轮上下文、当前 task 排除、32k 字符限制、图片附件 data URL、最多 4 张图片。
- 主聊天自动委派和群聊派活均已具备内部结构化 directive；自动委派提示和 parser 已收敛到 `run_oha_agent` / `run_oha_workflow`，旧 `run_yachiyo_*` / `<yachiyo_delegation>` 不再是有效入口；群聊派活提示已切到 `oha.group_dispatch` native envelope，旧 `<yachiyo_group_dispatch>` 文本协议已移除为有效入口且不会通过内嵌 OHA JSON 绕过。
- Skill library source API / UI 已从 `Yachiyo` 来源命名收敛为 `Installed`，仅保留角色/产品人格层面的 Yachiyo 命名。
- Workspace 初始化、备份、恢复和卸载协议已收敛到 OHA 命名：`.oha_yachiyo_init`、`configs/oha-yachiyo.json`、`oha_workspace`、`oha-workspace`、`oha_only`；旧 workspace 标记和旧卸载 scope 不再是有效入口。
- release-like source guard 已验证：release/alpha/stable metadata 下 debug routes 关闭，development credential fallback 不会被 factory 选中，macOS release-like factory 会选择 Keychain；release verifier 会阻断 stable 渠道误放行开发能力，也有负向回归确认 debug route modules、`debug_routes_enabled()` 和 `DevFileCredentialStore` fallback 被错误放开时会报错。
- release-facing artifact guard 已接入 macOS release workflow，构建 metadata 文件名、release 文档、workflow 和实际本地 `.app` / DMG 产物旧产品身份已有检查；workflow 现在会先用 binary-safe verifier 扫描 `dist/backend` 与 unpacked `.app/Contents/Resources`，再在生成 release DMG/JSON 后扫描 `release/` 目录；release verifier 自身也会阻断 workflow 丢失依赖安装前 security guard、签名导入/签名构建路径、签名脚本 runtime options / entitlements / verify 步骤、Gatekeeper 首启提示、当前未使用 Apple Developer ID / notarization 状态提示、屏幕录制权限提示、packaged resources scan、release 目录 binary scan、release metadata 生成后置扫描顺序、上传 JSON metadata 或 latest channel JSON metadata；release verifier 也会阻断重新打包本地 `node-pty/build` native artifact，避免旧 workspace 路径进入 `.app`，并锁定 hardened runtime、entitlements 与 macOS 权限说明文案。
- 三语 README、release packaging、Live2D/TTS 资源说明和桌面前端架构等活跃用户/开发入口文档已收敛到 Oha-Yachiyo / Native Agent / AppRuntime / NativeRunEngine 命名，并新增 source-level guard 防止这些入口重新出现旧 `Hermes` 产品身份、旧 CLI/env 前缀、旧用户目录、旧仓库 URL 或旧外部执行内核安装语义；历史 5 月首用报告和截图索引仍作为迁移前材料保留，不纳入当前入口 guard。
- Backend import、route registration、standalone packaged backend startup、packaged desktop startup 均已验证。
- `/status` 发布版本与产品版本已同步，版本同步脚本也覆盖该路径。
- 成熟 UI 入口已有 pytest 级 feature-preservation guard，覆盖 Chat、群聊、Agent Studio、Workflow、Run Detail、approval、Activity、Proactive TTS、local screenshot、manual TTS、Live2D。
- 本地截图权限不足时 `/screen/current` 返回结构化 `screen_capture_permission_denied` 并提示系统设置授权，且已有真实 FastAPI/TestClient HTTP 层回归；ChatAPI 用户请求桌面截图失败时返回/记录结构化且已清洗 secret 的 `desktop_snapshot_error`，同步 ActivityStore 用户可见失败事件，并通过 `verify_secret_redaction()` 扫描本次 ChatStore / ActivityStore SQLite 落盘目录；主动关怀屏幕权限检查继续返回 `permission_denied` / `settings_opened` 结构化结果。
- 主动关怀桌面观察已有 TaskRunner 级集成回归：`ProactiveDesktopService` 创建低风险 Screenshot Task、写入专用主动关怀会话、复用图片附件链路传递 `image_url` data URL，并由 `NativeAgentExecutor` / `NativeRunEngine` 完成 main_chat_run、RunEvent replay 和 ChatSession 投影，不会污染当前可见聊天会话。
- 成熟 UI 入口已有浏览器级 route smoke，覆盖主控台、Chat、Agent Studio、Workflow、Run history、Diagnostics、Settings、Proactive TTS、Live2D、Tool Center、Model Profiles、Resources、Workspace、Activity feed/detail、App Update。
- 成熟 UI 入口已有浏览器级按钮 smoke，覆盖 Chat 提交 readiness、Agent Studio tab 切换、Workflow/Run Detail shell、Live2D 资源设置、主动关怀语音保存。
- 成熟 UI flow contract 已有同步 pytest 覆盖，锁定 Chat 文本/图片发送、idempotency、停止生成、会话列表/搜索/加载/清空/丢弃空会话/删除、ChatBridge 会话摘要 / conversation overview、群聊 create/update、自动委派 summary task、Bubble / Live2D launcher 最近会话摘要、Chat 审批卡跳转 Run Detail 后读取同一 main_chat_run detail / RunEvent replay、Agent Studio 定义 list/create/update/delete、Skill Library 本体 list/import/source/sync/install/get/update/delete、Skill 文件夹 list/create/update/delete 与 Agent Skill attach/detach、Workflow Studio 定义 list/create/update/delete、Model Profiles 本体 list/create/get/update/defaults/test/delete、Model Sources list/create/get/update/test/fetch-models/delete、Run / RunGroup 列表与详情、Run artifact、rerun、delete、approval approve/reject 和 Run cancel 的 Bridge 合同。
- Chat readiness 已有真实浏览器级 E2E：source preview 打到 localhost-only source Bridge，未配置模型时 UI 入口保留、显示 native readiness、console error 为空，直接 POST 返回 `native_agent_not_ready / model_profile_required`。
- Chat 可用模型路径已有真实浏览器级 E2E：source preview 打到 localhost-only source Bridge 和本地 OpenAI-compatible fake model，真实提交用户消息，TaskRunner 走 `NativeAgentExecutor`，Run 完成并回放 `model.output.completed`，ChatSession 投影 assistant 回复。
- Chat 取消 late-output 已加固，并已补可重复 pytest 级 Bridge route 回归：慢模型返回前通过 `/ui/chat/session/cancel` 取消任务后，Run 可靠进入 `cancelled`，late model response 不再写 `model.output.completed` 或把 Run 覆盖回 running/completed，且 `/ui/runs` list/detail projection 可读取同一 cancelled Native main_chat_run 的 Task↔Run 映射、`task_run_link_run_status`、`task_run_link_last_event_sequence` 与 `run.cancelled` fact。
- Chat 图片附件已有 live source Bridge E2E，并已补可重复 pytest 级 Bridge route 回归：`/ui/chat/messages` 提交 image data URL attachment，ChatSession 只暴露公共 attachment URL，TaskRunner / NativeAgentExecutor 将图片传给 NativeRunEngine fake model，并可通过 `/runs/{run_id}/events` 读取 `model.output.completed` / `run.completed` replay。
- Chat 审批已有 live source Bridge E2E，并已补可重复 pytest 级 Bridge route 回归：真实 `/ui/chat/messages` 触发 `workspace.write_patch` approval，`/ui/runs/{run_id}/approval/approve` 批准后实际修改 workspace 文件，恢复模型并完成 `agent.tool.approval_required` / `agent.tool.approval_approved` / approved `agent.tool.call` / `model.output.completed` / `run.completed` replay。
- Chat 审批到 Run Detail 的同步 UI flow contract 已扩展到批准后刷新：Chat approval card / composer approval 调用同一 `/ui/runs/{run_id}/approval/approve` route 后，Chat messages 投影会清空 `pending_approval` 并进入 completed，Agent Studio Run Detail 读取同一 main_chat_run 也会显示 completed，`/runs/{run_id}/events?after_sequence=12` 可继续读取 `agent.tool.approval_approved` / `agent.tool.call` / `model.output.completed` / `run.completed` replay。
- Run API 现在直接投影 `task_id`、`session_id`、`task_run_link_created_at`、`task_run_link_updated_at`、`task_run_link_run_status` 和 `task_run_link_last_event_sequence`，让 Task↔Run 映射、当前状态和 replay 游标不必从 timeline 反推；Agent Studio Run Detail 的 `RunSpec` 与元数据行也已显式承接并展示这些字段，source-level guard 与同步 UI flow contract 会阻断前端回退成只看裸 Run timeline。
- Chat 图片附件产品路径已有 TaskRunner/route 级集成回归：真实 ChatAPI 保存 pasted image、TaskRunner 执行、NativeAgentExecutor 传递 OpenAI-compatible `image_url` data URL、NativeRunEngine 完成 RunEvent 和 ChatSession 投影，并且 `/ui/runs` Run Detail projection 与 `/runs/{run_id}/events` replay API 均可读取同一 Native main_chat_run。
- 主聊天工具审批等待已有 Chat API 级投影兜底：RUNNING Task 可通过当前 runtime service 的 Task↔Run link 投影 `approval_required` 到 ChatSession metadata、ActivityStore 和 `approval_count`，审批恢复后会清空旧 `pending_approval`；TaskRunner 和 ChatAPI 的终态投影均会移除过期审批进度，避免 completed assistant message 继续显示旧审批卡。
- 主聊天工具审批往返已有 TaskRunner 级集成回归：真实 TaskRunner / NativeAgentExecutor / NativeRunEngine 可让 main_chat_run 暂停审批、批准后执行 `workspace.write_patch`、恢复模型、完成 Task 与 ChatSession；并发重复 approval 和跨 NativeRunEngine 实例的重复 claim 不会重复执行工具。
- 主聊天自动委派已有 TaskRunner 级集成回归：真实 TaskRunner / NativeAgentExecutor / NativeRunEngine 可解析 `run_oha_agent` directive、创建 delegation Agent Run、记录 ActivityStore 委派活动、把 delegated result 回填给主模型并完成最终 ChatSession 回复；delegated Run 结束后创建主模型 follow-up summary Task 已有真实 NativeRunEngine Run projection 回归，并已补 `/ui/chat/delegated-run-summary` Bridge route 闭环，覆盖 route 创建 summary Task、NativeAgentExecutor 完成新的 main_chat_run、RunEvent replay 与 Run Detail projection；自动委派 summary 路径已修正为同时使用当前注入 runtime service 与 runtime activity store，不再隐式打开全局 NativeRunEngine / ActivityStore。
- 会话总结已有 ChatBridge 行为回归，覆盖真实 ChatSession / ChatStore 中当前会话的 `get_recent_sessions()` 摘要、`get_conversation_overview()` 给模式壳暴露的 `recent_sessions` / `latest_reply`，以及 processing / failed 状态摘要文案；现有 launcher route 回归也锁定 Bubble / Live2D 入口复用该 conversation overview。
- 群聊派活已有 ChatAPI + 真实 NativeRunEngine 级集成回归，并已补 Bridge route 级闭环：`/ui/chat/groups` 创建群聊后通过 `/ui/chat/messages` 触发主模型 `oha.group_dispatch`，创建真实 Agent Run，群组 upstream 进入 Agent context，Agent 完成后回写群聊消息并创建主模型群总结 Task，随后通过 `NativeAgentExecutor` 生成新的 main_chat_run / RunEvent replay / Run Detail projection / ChatSession 投影；群聊直接点名 Agent 的路径也已有 TaskRunner + 真实 NativeRunEngine 回归，覆盖 direct Agent Run 完成后创建主模型整理 Task，以及工具审批拒绝/取消后继续创建主模型整理 Task，并继续通过 `NativeAgentExecutor` 生成 main_chat_run / RunEvent replay / ChatSession 投影；群聊主模型整理 task 标签已收敛到 Oha-Yachiyo 命名，后台 TaskRunner 终态投影也会保留 summary metadata 以清理父消息 pending 状态；ChatAPI 的 Agent/Workflow/Run 状态读取入口现在统一经 `_agent_runtime_service()`，避免成熟业务路径直接绕过 runtime 注入边界。
- Workflow start / agent / artifact 节点执行、Workflow approval node、Workflow 等待子 Agent 审批、子 Agent 审批恢复/拒绝现在都有 replayable RunEvent：`workflow.node.start` / `workflow.node.agent` / `workflow.node.artifact` / `workflow.node.approval_required` / `workflow.run.approval_required` / `workflow.run.child_resumed` / `workflow.run.resumed` / `workflow.run.cancelled` 已接入 `/runs/{run_id}/events`，并有 route 级 Run Detail projection 回归；Workflow 子 Agent 审批 approve route 也已覆盖子 Run 自身 approve 后的 Run Detail 刷新，以及 `/runs/{child_run_id}/events` 中的 `agent.tool.approval_approved` / `agent.tool.call` / `agent.run.completed` replay；Workflow 子 Agent 审批 reject route 也已覆盖子 Run 自身 cancelled Run Detail 与 `agent.tool.approval_rejected` / `agent.run.cancelled` replay；Workflow rerun route 现在也会持久化 `run.rerun.started` RunEvent，route 回归覆盖 rerun 后 Run Detail、artifact 和 replay API；真实 FastAPI/TestClient HTTP roundtrip 已覆盖 `/ui/workflows` 创建 Workflow、`/ui/workflow-runs` 进入 Workflow approval node 审批和子 Agent 审批、`/ui/runs/{run_id}/approval/approve` 恢复 Workflow approval node、`/ui/runs/{run_id}/approval/reject` 取消 Workflow approval node、`/ui/runs/{run_id}/cancel` 取消 Workflow approval node、`/ui/runs/{run_id}/rerun` 重跑 Workflow 并读取新 Run Detail / artifact / replay、`DELETE /ui/runs/{run_id}` 删除 completed Workflow 及子 Run / RunGroup / artifact / replay、`/ui/runs/{child_run_id}/approval/approve` 恢复父 Workflow、`/ui/runs/{child_run_id}/approval/reject` 取消父 Workflow、`/ui/runs/{child_run_id}/cancel` 取消子 Agent 并投影父 Workflow、父/子 Run Detail、父/子 RunEvent replay 与 artifact 读取。
- Agent Studio Run Detail 已接入 `/runs/{run_id}/events` replay API，Execution 区优先展示 replayable RunEvent facts，选中 Run 的状态/更新时间/timeline 变化时会刷新 replay，支持按 `after_sequence` 继续加载更多 replay facts，常见 RunEvent facts 已映射为可读标题/语气，保留旧 timeline 回退；Run Detail replay 标题映射、分页加载、sequence 去重合并、loading/error 状态的 source guard 已覆盖；Run Detail 的 Workflow 子 Agent 审批桥接已补 source-level guard，锁定父 Workflow 选中态、子 Run approve/reject/cancel、子 Run 打开、approval 后 child/parent Run cache、RunGroup 刷新和审批后父 Run 刷新链路，并有 route contract 覆盖批准/拒绝/取消后子 Run、父 Workflow Run 和 RunEvent replay 刷新；Run rerun 后前端会立即缓存新 Run Detail 并刷新 RunGroup，Run 删除后前端会同步清理 Run list / Run Detail cache / RunEvent replay cache / 已空 RunGroup cache，并有 source-level guard；真实 FastAPI/TestClient HTTP roundtrip 也已覆盖 Agent Run 进入 `approval_required`、Run Detail 读取、approval approve 恢复、approval reject 取消、Run cancel 取消待审批 Run、Agent rerun 新 Run Detail / replay、Agent delete 清理 Run / RunGroup / replay、RunEvent replay 中的审批/工具/完成或取消 facts。
- AppRuntime 已提供主聊天默认 tool/workspace policy 并接入 `select_executor()`；主聊天产品路径默认进入同一套 ToolDescriptor / PolicyGate / approval / workspace boundary 体系，ToolBroker 已有 realpath/symlink 越界回归。
- 未配置模型时返回结构化 native readiness 错误，不再引导安装旧执行内核。

### 仍未完全达成

- 模型输出 durable persistence 已有 batched completed-event 回归、dict-style stream iterator delta 合并压力测试、OpenAI SDK object-style content chunk 合并回归、OpenAI-style streaming tool_call delta 合并回归、OpenAI-compatible SSE stream parser / NativeRunEngine `stream=True` contract 回归、OpenAI-compatible SSE parser split UTF-8 chunk 回归、fake HTTP provider SSE 闭环回归、fake HTTP provider split UTF-8 SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider message-level content / reasoning SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider content-part array SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、content-part array 中 `reasoning` / `thinking` 私有片段不作为可见 output 落盘回归、streaming reasoning-only delta 不作为可见 output 落盘回归、fake HTTP provider coalesced/split/multiline `data:` SSE frame 到 NativeRunEngine completed RunEvent 的闭环回归、fake HTTP provider SSE tool-call、message-level SSE tool-call、split-frame SSE tool-call、indexless SSE tool-call delta、缺 `index` 但带稳定 tool-call `id` 的 interleaved delta、multiline `data:` SSE tool-call 闭环回归、fake HTTP provider legacy `delta.function_call` 帧透传回归，以及 fake HTTP provider SSE / multiline `data:` SSE error frame 失败/清洗闭环回归；现在也有 opt-in `scripts/smoke_openai_compatible_stream.py` 可用真实 provider 做 streaming / tool-call smoke，支持要求流式文本内容、content-part array、message-level content / reasoning frame、reasoning delta、content-part array 中 reasoning/thinking 私有片段、指定工具名、tool-call arguments substring 和 `finish_reason`，脚本自身已有 fake transport、role-only 首包、usage-only 尾包、多 choice 同 index tool-call delta、indexless tool-call delta、缺 `index` 但带稳定 tool-call `id` 的 interleaved delta、OpenAI SDK object-style tool_call / reasoning delta、multiline `data:` SSE tool_call、legacy streamed `function_call` delta、message-level content / reasoning frame、content-part array frame、reasoning 只统计长度不打印原文、finish_reason 断言和错误 secret 清洗回归，且摘要不打印 raw tool arguments；实际凭据环境下的真实外部 provider 联调仍需做。
- ApprovalCoordinator 已承接 approve/reject/timeout 的通用状态转换；主聊天工具审批、standalone Agent 工具审批和 Workflow approval node 的 reject / timeout 现在都有边界 spy 回归，确认 `NativeRunEngine.reject_run_approval()` / `timeout_run_approval()` 继续委托 ApprovalCoordinator 完成状态转换与 replay fact 写入；ApprovalResumeCoordinator 已承接批准后的工具执行和 custom-api 模型循环恢复入口，并已有 coordinator 级成功续跑 / fatal tool failure 阻断 / 工具后继续模型顺序回归；WorkflowParentResumeCoordinator 已承接父子 Run 联动，并已有 completed child replay / continuation handoff 的 coordinator 级回归，且重复 child approval_required / cancelled / failed update 不会重复投影父 Workflow replay fact 或重复更新父 Run；WorkflowContinuationCoordinator 已承接具体 Workflow step continuation，并已有 approval node pause / public pending projection / RunGroup handoff、artifact node write / completion handoff、failure replay payload secret 清洗的 coordinator 级回归。
- 主聊天自动委派和群聊派活都已引入内部结构化 directive；自动委派已收敛到 `run_oha_agent` / `run_oha_workflow`，并已有 TaskRunner 级 NativeRunEngine 闭环回归，群聊主提示与 parser 已收敛到 `oha.group_dispatch` / `<oha_group_dispatch>` / native 命名，并已有 ChatAPI + 真实 NativeRunEngine 闭环回归；旧 `run_yachiyo_*`、`<yachiyo_delegation>` 和 `<yachiyo_group_dispatch>` 不再作为有效入口。
- Workflow 与主聊天共享 NativeRunEngine 的路径已存在，已有 focused 回归、UI 入口 guard、同步 UI flow contract、浏览器级 route smoke、部分按钮级 smoke、无模型 Chat readiness 浏览器 E2E、可用 fake 模型 Chat 浏览器 E2E，以及 slow fake model 的 Chat 取消 late-output Bridge 复验；主聊天多轮/图片已补 executor/API/Bridge 合同、TaskRunner 级图片 roundtrip、live source Bridge 图片 E2E、HTTP route 图片附件发送 / attachment FileResponse roundtrip 和 Run Detail/RunEvent route projection，主聊天审批等待、approval roundtrip、live source Bridge 审批 E2E 和重复 approval 防重复执行已补回归，Chat 图片粘贴/上传/移除、停止生成、消息审批卡与 composer 审批卡、Chat 审批卡到 Agent Studio Run Detail 的 route/replay handoff、委派 Run 结束后 summary task processing 状态已补 source-level UI wiring guard，Chat 图片/取消/审批/Run Detail、Agent Studio Run Detail/approval/replay/artifact、Workflow Studio 编辑/节点配置/保存并运行路径已暴露稳定 `data-testid` 选择器并由 source guard 锁定，Workflow 节点执行与审批等待 facts 已接入 RunEvent replay，并新增真实 HTTP route roundtrip 覆盖 Agent/Workflow approval、Run Detail、RunEvent replay 和 artifact 读取；但仍需要恢复浏览器 runner 后补图片/审批/取消按钮级 E2E，以及群聊/委派/Workflow/Run Detail 的完整交互 E2E。
- Secret 清洗已补主路径回归、旧 chat.db 迁移清洗、标准 logging、桌面后端 excepthook、crash 文件生成扫描、HTTPException detail、UI JSON error/message、provider catalog 失败缓存、artifact 文件清洗、artifact.write secret payload 写入前拒绝与落盘扫描、provider/tool exception 端到端落盘扫描、terminal / workspace.write_patch approval secret payload 审批前拒绝与落盘扫描、approval reject/cancelled RunEvent payload 清洗、Workflow continuation failure replay payload 清洗和默认 runtime 落盘扫描；仍建议继续补真实 provider / terminal / tool 集成环境下的异常日志联调。
- `workspace.write_patch` 已收敛为单文件 UTF-8 unified diff patch；content 全量写入已从 tool schema 移除，并在 validator / ToolBroker direct 入口拒绝。
- Runtime 发起的 skill 安装子进程已复用敏感环境变量清洗，避免 `SSH_AUTH_SOCK`、`GITHUB_TOKEN`、云厂商凭据和 `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 从旁路传入外部命令；`terminal.run` 与 skill install 现在使用同一套 env scrub helper。
- release/alpha/stable 源码级 guard、release-facing verifier、packaged app resources scan、签名导入/签名构建 workflow guard、签名脚本 runtime options / entitlements / verify guard、Gatekeeper 首启说明/当前 notarization 状态/屏幕录制权限 release notes guard、macOS hardened runtime / entitlements / usage descriptions guard、release metadata JSON 发布 guard、latest JSON 更新字段 guard、release DMG/SHA staging/upload guard、关键 smoke tests 构建前执行顺序 guard 与 release 目录 binary-safe artifact scan 已覆盖；workflow 会排除本地 `node-pty/build` native artifact 并只打包 clean prebuilds，release verifier 也会阻断 tracked `.vite` cache、`apps/frontend/dist`、`apps/frontend/dist-electron`、release workflow 丢失 Task API protocol/AppState task lifecycle/TaskRunner native approval roundtrip/OpenAI-compatible streaming provider contracts/legacy Hermes kernel removal/Native runtime injection boundary/desktop backend Native startup/release-like build metadata guards/release-like CredentialStore guards/runtime secret redaction verifier/security logging redaction/截图/主动关怀/ChatSession/ChatBridge session summary/Chat API/ActivityStore feed and redaction/UI Bridge/成熟 UI preservation/UI flow contract/Bridge Host Origin session token guard/Bridge loopback bind guard/mutating Bridge token guard/Chat image HTTP roundtrip/Agent approval Run Detail HTTP roundtrip/Workflow approval Run Detail HTTP roundtrip/Workflow child approval Run Detail HTTP roundtrip/Workflow rerun artifact replay HTTP roundtrip/group chat Native summary flow/auto delegation Native summary flow/TTS/Live2D smoke 覆盖和 packaging config 丢失 `.vite` 排除；本地 unsigned `.app` / DMG 产物已验证不包含旧产品身份 token。Electron Framework 内部自带的通用 `Hermes` 字符串不属于本项目产品身份或执行内核残留。
- 桌面 `.app` 已实际启动并验证 bridge；主要 UI 页面已有静态入口 guard、浏览器级 route smoke 和部分按钮级交互 smoke，但仍缺少完整成熟功能 E2E。

## 下一步建议

1. 做 PR-3 成熟功能 UI 级回归：
   - 在现有入口 guard、同步 UI flow contract、route smoke、部分按钮级 smoke、Chat readiness Browser E2E 和 fake-model Chat Browser E2E 基础上补完整浏览器 E2E。
   - Chat UI 图片附件、审批等待/恢复和取消按钮的浏览器级交互复验；当前图片/审批已有 source Bridge E2E，但还不是完整 UI click/upload/approval-card E2E。
   - 群聊、自动委派、会话总结的完整浏览器交互。
   - Agent Studio、Workflow、Run Detail、approval UI。
   - 主动关怀、本地截图、手动 TTS、Live2D。

2. 做 NativeRunEngine 组件边界收敛：
   - 逐步把 approval resume execution 编排拆成可测试的恢复步骤，保持 API 行为不变。
   - 继续审计 Workflow/Agent child-run 编排，避免 `NativeRunEngine` 重新变成单体。
   - 保持现有 API 不变，只减少单类内聚。

3. 做 streaming/event replay 硬化：
   - 用 `scripts/smoke_openai_compatible_stream.py` 对真实 streaming provider 做联调，确认不同 provider chunk 形态都能正确合并。
   - 继续补 RunEvent replay/projection 的端到端 UI 展示验证。

4. 做最终发布验收切片：
   - release/alpha package grep。
   - 确认 release build 不注册 debug routes，不包含 dev credential fallback。
   - 代码签名、notarization 和首次启动权限提示验证。
