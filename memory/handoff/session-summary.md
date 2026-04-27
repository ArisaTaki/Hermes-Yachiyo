# Session Summary

## 本轮完成内容 — Milestone 63/64: Desktop UX, shared settings, runtime context, memory design

### 核心结果

本轮围绕真实桌面使用体验做了一轮收敛：Hermes 长任务不再被 60 秒截断，模型调用获得当前本地时间和用户称呼上下文；Control Center 成为共通设置主入口；Bubble/Live2D 的 Chat Window 入口改为打开或置前；Chat Window 支持可选中文本和图标复制；并补齐本地记忆架构文档。

### 主要变更

#### 1. Hermes 执行与上下文

- 默认 Hermes 执行超时提升到 30 分钟，并支持 `HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS`。
- streaming bridge / CLI 记录首事件、首输出、完成、进程结束和超时耗时。
- 每轮请求注入当前本地时间、星期、时段，减少相对时间和问候误解。
- prompt 包装加入用户称呼，顺序为环境上下文 → 人设 → 用户称呼 → 用户请求。

#### 2. 共享助手资料与设置确认

- 新增 `assistant.user_address`，从配置、Bridge profile、协议 schema、MainWindowAPI 到 Hermes 调用链贯通。
- 助手人设 Prompt 与用户称呼收敛到 Control Center 主设置。
- 共通文本/数字/大段文本设置改为待确认保存，显示“应用共通设置修改”。
- dirty 判断基于当前已提交值，改动后改回原值会自动清除 pending。
- 工作空间创建时间在主控台和设置页显示为本地可读格式。

#### 3. Bubble / Live2D launcher 行为

- Bubble 默认位置改为屏幕百分比，默认右下角。
- Bubble 靠边吸附正式实现，拖动释放后吸附最近边缘。
- Bubble 呼吸灯语义：黄色处理中，绿色未读成功，红色未读失败；Chat Window 打开时抑制状态点并确认可见结果。
- Bubble / Live2D 点击聊天入口时只打开或置前 Chat Window，不再关闭已存在窗口。

#### 4. Chat Window 交互

- 消息文本可选择，消息右上角提供复制图标。
- 复制成功后图标短暂变为对勾，后端剪贴板失败时回退浏览器剪贴板和 textarea。
- 移除“重新编辑/重编”入口。
- 既有 Chat Window 聚焦路径增强，并修复初始化期 focus 失败导致第二个白屏窗口的问题。

#### 5. 记忆架构与文档

- 新增 `docs/memory-architecture.md`。
- 明确 SQLite 聊天记录只是原始会话存档；长期记忆优先复用 Hermes 原生能力。
- Yachiyo 侧定位为本地控制层：授权、项目/目的归类、可视化管理、Bridge 边界和检索注入。
- README 更新为当前桌面入口与设置体系说明。

### 测试覆盖

- `tests/test_executor.py`：执行超时、环境上下文、用户称呼 prompt 注入。
- `tests/test_assistant_profile_route.py`：assistant profile 读写用户称呼。
- `tests/test_mode_settings.py`：Bubble 百分比位置、edge snap 设置、共通设置不在模式窗口渲染。
- `tests/test_chat_bridge.py`：Bubble 状态点语义、Chat Window 打开时抑制状态点、Bubble/Live2D 点击置前。
- `tests/test_chat_window.py` / `tests/test_chat_window_singleton.py`：复制按钮、移除重编、单例置前和白屏重复窗口回归。
- `tests/test_window_exit.py`：Control Center 共通设置按钮、dirty 回退、创建时间格式化。

### 验证结果

- 完整测试：`python -m pytest` → 360 passed。
- VS Code diagnostics：本轮修改相关文件无错误。

### 后续建议

1. 在真实 pywebview/macOS 桌面环境中手工验证 Bubble/Live2D 重复点击、Chat Window 复制、创建时间格式和设置 dirty 回退。
2. 用真实 Hermes 冷启动/续接请求验证耗时日志和 30 分钟超时策略。
3. 调研 Hermes 原生记忆能力，决定 `HermesMemoryAdapter` 的第一版接口。

---

## 本轮完成内容 — Milestone 62: PR #4 review fixes

### 核心结果

本轮按 PR #4 的 3 条 Copilot inline review comment 做最小修复：主动桌面观察 failed 状态不再永久卡死，Live2D TTS 不再朗读截断摘要，Bubble 状态点恢复 `visible` class 逻辑。

### 主要变更

#### 1. 主动桌面观察 failed 重试

- failed 后优先返回错误状态，保留用户可见的失败原因。
- 到达配置间隔后自动重新创建低风险截图任务。
- 未到间隔时不会重复创建任务，避免失败态循环刷任务。

#### 2. Live2D TTS 使用完整文本

- `ChatBridge` 增加 `latest_reply_full`，保留完整 assistant 回复。
- `latest_reply` 继续作为 UI 摘要截断字段。
- Live2D `_maybe_trigger_tts()` 优先使用 `latest_reply_full`，fallback 到 `latest_reply`。

#### 3. Bubble 状态点 visible 逻辑

- 未读/主动提醒输出 `visible attention`。
- 处理中输出 `visible processing`。
- 失败输出 `visible failed`。
- idle / empty / ready 且无未读时继续隐藏；`show_unread_dot=false` 继续抑制可见点。

### 测试覆盖

- `tests/test_proactive.py`：failed 间隔前返回错误、间隔后重试。
- `tests/test_chat_bridge.py`：完整最新回复字段与 Bubble 状态点 class 逻辑。
- `tests/test_tts.py`：Live2D TTS 使用完整长回复。

### 验证结果

- `python -m pytest tests/test_proactive.py tests/test_chat_bridge.py tests/test_tts.py tests/test_mode_settings.py tests/test_native_window.py`
- 结果：87 passed

### 后续建议

1. 在真实桌面窗口中手工验证 Bubble 未读/处理/失败状态点视觉表现。
2. 使用真实 HTTP/command TTS provider 验证长回复朗读完整文本。
3. 在真实 Hermes 执行环境中验证主动观察 failed 后的间隔重试。

---

## 本轮完成内容 — Milestone 61: Chat auto-open behavior and Bubble settings clarity

### 核心结果

本轮修复了 Bubble / Live2D 聊天窗口误弹出风险：两种桌面入口都不再允许 hover 打开或切换 Chat Window，聊天窗口只能由点击入口触发。

同时澄清了 Bubble 设置的生效认知，扩大尺寸范围并修复视觉尺寸不随配置变化的问题；为后续 AstrBot 记忆/人设共享新增了最小 profile API，并明确不默认同步 QQ 原始聊天文本。

### 主要变更

#### 1. Bubble / Live2D click-only 聊天入口

- Bubble 移除 `pointerenter` / hover 打开逻辑；运行视图固定返回 `expand_trigger=click`。
- 旧配置 `bubble_mode.expand_trigger=hover` 会在加载时规整为 `click`，设置 API 也会拒绝新的 hover 写入。
- Bubble 与 Live2D 均移除 hover 聚焦入口，避免 hover/focus 间接触发用户误解。
- Live2D `default_open_behavior` 只控制回复泡泡/快捷输入，不打开 Chat Window。
- `live2d_mode.auto_open_chat_window` 保留为启动时行为，并标记为需重启当前模式后生效。

#### 2. Bubble 设置认知与尺寸逻辑

- Bubble 尺寸范围扩展为 `80-192`。
- launcher CSS 与原生命中测试随窗口尺寸缩放，不再固定在 `108px` 视觉大小。
- 设置页移除 hover 选项，显示“点击打开聊天（固定）”。
- 尺寸、位置、置顶、头像字段明确标注“需重启当前模式”。
- 新增“应用并重启应用 / 重启应用”入口作为当前模式重启未拆出前的兜底。
- `edge_snap` 仍保持禁用/待实现。

#### 3. Chat Window 单例清理

- `open_chat_window()` 会忽略 stale closed/destroyed window 并重新创建。
- `is_chat_window_open()` 会清理已关闭/销毁的单例引用。
- `close_chat_window()` 对已关闭窗口保持 no-op，不再误判状态。

#### 4. Assistant profile / 记忆共享设计基础

- 新增 `GET /assistant/profile` 与 `PATCH /assistant/profile`。
- canonical 人设仍是桌面端 `assistant.persona_prompt`。
- profile 响应声明 prompt 注入顺序：`persona` → `relevant_memory` → `current_session` → `request`。
- 记忆事实同步暂不实现原始 QQ 聊天自动同步；后续只接收显式摘要/事实，由 Hermes-Yachiyo 本地端存储、筛选和注入。

### 测试覆盖

- `tests/test_mode_settings.py`：hover 拒绝/旧配置规整、Bubble 尺寸范围、设置页重启文案。
- `tests/test_chat_bridge.py`：Bubble/Live2D 前端不再包含 hover 打开入口，Bubble view 固定 click。
- `tests/test_native_window.py`：Bubble 圆形命中测试随 `80-192` 窗口缩放。
- `tests/test_chat_window_singleton.py`：关闭、stale window、复用与重建。
- `tests/test_assistant_profile_route.py`：profile 读取/更新共享人设。

### 验证结果

- 验收测试集：161 passed
- 完整测试：320 passed

### 后续建议

1. 在真实 pywebview/macOS 窗口中手工验证 hover/focus/刷新都不会打开 Chat Window。
2. 手工验证 Bubble 尺寸 `80-192`、头像/位置/置顶重启后生效。
3. 继续设计本地 memory facts 存储与 AstrBot 显式摘要上传协议。

---

## 上轮完成内容 — Milestone 60: Live2D assistant settings and AstrBot intent bridge

### 核心结果

本轮修复了 Bubble / Live2D 多个“设置已保存但运行时不响应”的问题，并补齐 Live2D 可选 TTS、共享助手人设 Prompt、Bubble + Live2D 主动桌面观察、AstrBot 低风险自然语言入口。

现有 `/y status/tasks/screen/window/do/check/cancel/codex` 命令族保持兼容；AstrBot 仍只做 QQ bridge，不直接执行本机控制，也不成为第二 runtime。

### 主要变更

#### 1. 设置生效闭环

- Bubble
  - `show_unread_dot` 控制状态点显隐。
  - `opacity` 影响 launcher 透明度。
  - `default_display` 区分 `icon` / `summary` / `recent_reply`。
  - `expand_trigger` 曾支持 `click` / `hover`；当前 Milestone 61 已废弃 hover 并统一为 click。
  - `auto_hide` 在空闲时降低 launcher 可见度。
  - `edge_snap` 暂未实现真实吸边，设置页已标记为待实现/禁用。
- Live2D
  - `get_live2d_view()` 的 `click_action` 不再硬编码为 `open_chat`。
  - JS 实现 `open_chat` / `toggle_reply` / `focus_stage`。
  - `show_reply_bubble` 控制回复气泡。
  - `enable_quick_input` 控制最小快捷输入条。
  - `default_open_behavior` 控制启动后初始表现。
  - `window_on_top` / `show_on_all_spaces` 继续保持“需重启当前模式生效”，设置页文案已明确。

#### 2. 共享 assistant 与 TTS 配置

- 新增共享 `assistant.persona_prompt`。
- 新增 `tts.enabled` / `tts.provider` / `tts.endpoint` / `tts.command` / `tts.voice` / `tts.timeout_seconds`。
- 配置加载、保存、序列化、设置页表单、字段校验、effect policy 已同步。
- Hermes 执行前按以下格式包装用户任务描述；空 prompt 保持原行为：

```text
[人设设定]
{persona_prompt}

[用户请求]
{original_description}
```

- 新增 `apps/shell/tts.py`：默认关闭，支持 `none` / `http` / `command`，失败只记录状态，不阻塞聊天。

#### 3. 主动桌面观察

- 新增 `apps/shell/proactive.py` 的 `ProactiveDesktopService`。
- Bubble 和 Live2D 共享该服务。
- 服务会检查：配置开关、Hermes ready、TaskRunner、`HermesExecutor`、vision 限制。
- 成功时创建 `TaskType.SCREENSHOT` / `RiskLevel.LOW` 任务。
- 维护 last task、ack、attention 状态。
- Live2D 视图返回 proactive 状态，并在有主动观察结果时触发视觉提示。

#### 4. Bridge / AstrBot 低风险自然语言入口

- 新增 Bridge 端点：`POST /assistant/intent`。
- 请求字段：`text` / `source` / `sender_id` / `dry_run`。
- 响应字段：`ok` / `action` / `task_id` / `message`。
- 默认策略：
  - 状态、截图、活动窗口摘要可直接返回。
  - 其他自然语言电脑操作只创建 `RiskLevel.LOW` 的 Hermes 任务并返回 `task_id`。
- AstrBot 新增 `/y ask <内容>` 与 `/y chat <内容>`。
- AstrBot 保留 allow-list 权限校验，并向 Bridge 透传 `sender_id`。

### 测试覆盖

- `tests/test_mode_settings.py`
  - 新字段默认值、序列化、保存、非法值拒绝。
- `tests/test_chat_bridge.py`
  - Bubble 视图返回并消费 `show_unread_dot` / `default_display` / `opacity` / `expand_trigger` / `auto_hide`。
  - Live2D 视图返回配置 `click_action`，并包含回复气泡、快捷输入、默认启动表现字段。
- `tests/test_proactive.py`
  - disabled、Hermes 未就绪、vision 受限、成功创建低风险截图任务。
- `tests/test_tts.py`
  - disabled、missing config、command/http validation。
- `tests/test_assistant_intent_route.py`
  - Bridge assistant intent 状态返回与低风险任务创建。
- `tests/test_astrbot_handlers.py`
  - `/y ask` / `/y chat` 路由、未授权 sender 拒绝、既有命令族不回归。
- `tests/test_executor.py`
  - `format_persona_description()` 空 prompt 兼容和包装格式。

### 验证结果

- 验收测试集：
  - `python -m pytest tests/test_mode_settings.py tests/test_chat_bridge.py tests/test_native_window.py tests/test_astrbot_handlers.py tests/test_proactive.py tests/test_assistant_intent_route.py`
  - 结果：106 passed
- 完整测试：
  - `python -m pytest`
  - 结果：304 passed

### 后续建议

1. 手工验证 Bubble / Live2D 设置项在真实 pywebview 窗口中的表现。
2. 配置一个真实 HTTP TTS endpoint 和一个本地 command TTS，验证失败不影响聊天主流程。
3. 联调 AstrBot 宿主事件绑定，让 QQ 消息实际调用 `on_y_command()`。
4. 后续再实现 Bubble `edge_snap` 原生吸边和真正 Live2D renderer / 动作系统。
