# Session Summary

## 本轮完成内容 — Milestone 60: Live2D assistant settings and AstrBot intent bridge

### 核心结果

本轮修复了 Bubble / Live2D 多个“设置已保存但运行时不响应”的问题，并补齐 Live2D 可选 TTS、共享助手人设 Prompt、Bubble + Live2D 主动桌面观察、AstrBot 低风险自然语言入口。

现有 `/y status/tasks/screen/window/do/check/cancel/codex` 命令族保持兼容；AstrBot 仍只做 QQ bridge，不直接执行本机控制，也不成为第二 runtime。

### 主要变更

#### 1. 设置生效闭环

- Bubble
  - `show_unread_dot` 控制状态点显隐。
  - `opacity` 影响 launcher 透明度。
  - `default_display` 区分 `icon` / `summary` / `recent_reply`。
  - `expand_trigger` 支持 `click` / `hover`。
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
