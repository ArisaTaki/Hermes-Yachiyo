# Session Summary

## 本轮完成内容 — Milestone 30: Live2D 配置最小可编辑能力

### 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/settings.py | HTML 模板重构为可编辑控件版（input + toggle）；build_settings_html() 参数更新 |
| apps/shell/modes/live2d.py | Live2DWindowAPI 新增 update_settings()；open_settings() 传入 js_api=self |
| apps/shell/main_api.py | update_settings() 支持 live2d.* 嵌套字段；_EDITABLE_LIVE2D_FIELDS 白名单 |
| apps/shell/window.py | Live2D 设置区域输入控件 + refreshSettings() active-element 守护 |
| memory/progress/current-state.md | Milestone 30 记录 |
| memory/handoff/session-summary.md | 本次汇报 |

### Live2D 可编辑字段

| 字段 | 控件 |
|------|------|
| live2d.model_name | text input |
| live2d.model_path | text input |
| live2d.idle_motion_group | text input |
| live2d.enable_expressions | toggle checkbox |
| live2d.enable_physics | toggle checkbox |
| live2d.window_on_top | toggle checkbox |

### 两处设置入口

1. **主窗口内嵌设置面板**（window.py）
   - 通过 `MainWindowAPI.update_settings({'live2d.*': value})` 保存
   - `refreshSettings()` 填充 `.value`/`.checked`，active-element 守护防止覆盖输入

2. **Live2D 模式独立设置窗口**（settings.py + live2d.py）
   - `open_settings()` 传 `js_api=self`（Live2DWindowAPI 实例）
   - JS `saveLive2D(field, value)` → `window.pywebview.api.update_settings({'live2d.field': value})`
   - 保存结果在"已保存"提示区显示（3秒后消失）

### 架构决策

- `Live2DWindowAPI.update_settings()` 独立实现（不调用 main_api），保持模式边界清晰
- `_EDITABLE_LIVE2D_FIELDS` 白名单在两处各自维护（main_api / live2d.py），字段一致
- 真正渲染逻辑继续留给未来 `live2d_renderer.py`，本次不触及

### 仍为占位的部分

| 功能 | 状态 |
|------|------|
| Live2D 模型实际加载/渲染 | 等待 live2d_renderer.py |
| 配置修改后热更新模型 | 等待渲染器实现 |
| model_state = PATH_VALID / LOADED | 等待渲染器实现 |


### 修改的文件

| 文件 | 变更 |
|------|------|
| integrations/astrbot-plugin/handlers/utils.py | 新增 `fmt_error()` + `_fmt_http_error()` |
| integrations/astrbot-plugin/command_router.py | catch 块改用 `fmt_error(exc, command)` |
| integrations/astrbot-plugin/handlers/codex.py | 不再发起 HTTP，直接返回占位消息 |
| integrations/astrbot-plugin/handlers/status.py | hermes_ready=False 时新增指引行 |

### 统一的错误分类与口径

| 场景 | 输出 |
|------|------|
| Bridge 不可达（连接被拒绝） | ⚠️ 无法连接到 Hermes-Yachiyo\n请确认桌面应用正在运行，Bridge 已启用 |
| 连接超时 | ⚠️ 连接 Hermes-Yachiyo 超时\n请检查桌面应用是否正常运行 |
| 读取超时 | ⚠️ 请求 /y {cmd} 超时\nBridge 响应过慢，请稍后重试 |
| HTTP 503（Hermes 未就绪） | ⚠️ Hermes Agent 未就绪\n请在桌面应用中确认 Hermes 安装状态 |
| HTTP 500/5xx（Bridge 内部错误） | ⚠️ Bridge 内部错误 [状态码]\n{detail} |
| HTTP 422（参数有误） | ⚠️ 请求参数有误\n{detail} |
| HTTP 404（资源不存在） | ⚠️ 资源不存在\n{detail} |
| HTTP 4xx（其他客户端错误） | ⚠️ 请求错误 [状态码]\n{detail} |
| /y codex（Hapi 占位） | 🤖 /y codex 即将推出\nCodex CLI 通过 Hapi 执行，后端端点正在对接中 |
| Hermes 未就绪（来自 /status） | 正常输出 + 末行：请在桌面应用中完成 Hermes 安装配置 |
| 未知异常 | ⚠️ 未知错误\n{exc} |

### 架构决策

- **所有命令统一通过 command_router.py 的 catch 块处理异常**，各 handler 无需单独捕获
- **codex.py 不发起网络请求**：Hapi 端点未确认前，直接返回占位文案，避免产生噪音错误
- **错误分类逻辑在 utils.py**，不在 handler 或 router 中内联，可复用

### 仍为占位的部分

| 命令 | 状态 | 说明 |
|------|------|------|
| /y codex | ⚠️ 占位 | Hapi /codex 端点确认后接入 |
| /y screen（图片） | ⚠️ 占位 | base64 → AstrBot 图片消息待联调 |
| AstrBot 宿主绑定 | ⚠️ 待完成 | on_y_command() 与 AstrBot 事件系统挂钩 |

## 下一步重点

**AstrBot 宿主绑定**：在 AstrBot 插件框架中注册 /y 命令监听，调用 `on_y_command()`。

### 目标
完善 AstrBot bridge 各命令的用户可读 QQ 输出格式。

### 修改的文件

| 文件 | 变更 |
|------|------|
| packages/protocol/schemas.py | `StatusResponse` 新增 `hermes_ready: bool = False` |
| apps/bridge/routes/status.py | `/status` 端点填充 `hermes_ready = rt.is_hermes_ready()` |
| integrations/astrbot-plugin/api_client.py | 新增 `_raise_readable()` 函数，HTTP 错误时提取 JSON detail 字段 |
| integrations/astrbot-plugin/handlers/utils.py | 新建：`fmt_status / fmt_status_icon / fmt_uptime / fmt_dt` 共享工具 |
| integrations/astrbot-plugin/handlers/status.py | 新增 Hermes Agent 就绪状态行；任务统计改用图标精简格式 |
| integrations/astrbot-plugin/handlers/tasks.py | 每条任务新增短 ID（8位）和创建时间 |
| integrations/astrbot-plugin/handlers/window.py | 新增查询时间行；空标题改为"（无标题）" |
| integrations/astrbot-plugin/handlers/screen.py | 格式大写、时间格式化、文案整洁 |
| integrations/astrbot-plugin/handlers/do.py | 状态改为中文标签（fmt_status）；ID 截短为 8 位；文案改为"任务已提交" |

### 各命令输出格式

**/y status**
```
📊 Hermes-Yachiyo 状态
版本: v0.1.0  运行: 5m 3s
Hermes Agent: ✅ 已就绪
任务: ⏳ 0  🔄 0  ✅ 0
```

**/y tasks（有任务时）**
```
📋 任务列表（共 2 条）
  ⏳ [abc12345] 帮我写一段代码
       04-15 08:22:47
  ✅ [def67890] 截图
       04-15 07:10:00
```

**/y window**
```
🪟 当前活动窗口
应用: Visual Studio Code
标题: main.py - project
PID: 12345
查询时间: 04-15 08:22:47
```

**/y screen**
```
📸 截图已获取
分辨率: 1920×1080  格式: PNG
拍摄时间: 04-15 08:22:47
（图片消息待 AstrBot 联调后发送）
```

**/y do 帮我查看文件**
```
✅ 任务已提交
ID: abc12345
描述: 帮我查看文件
状态: ⏳ 等待中
```

### 仍为占位的部分

| 命令 | 状态 | 说明 |
|------|------|------|
| /y codex | ⚠️ 占位 | Hapi /codex 端点 schema 待确认 |
| /y screen（图片） | ⚠️ 占位 | base64 → AstrBot 图片消息待联调 |
| AstrBot 宿主绑定 | ⚠️ 待完成 | on_y_command() 与 AstrBot 事件系统挂钩 |

## 下一步重点

**AstrBot 宿主绑定**：在 AstrBot 插件框架中注册 /y 命令监听，调用 `on_y_command()`。

| 文件 | 变更 |
|------|------|
| apps/bridge/server.py | 新增 `_state` 变量 + `get_bridge_state()`，start_bridge() 异常时设 failed |
| apps/shell/main_api.py | `_bridge_status()` 组合四状态；dashboard `bridge.running` 字段真实化 |
| apps/shell/modes/bubble.py | 导入 get_bridge_state，添加 `_bridge_status()`，JS 改为四状态标签 |
| apps/shell/window.py | `refreshDashboard()` bridge 行改为四状态标签展示 |

**四状态**：`disabled` / `enabled_not_started` / `running` / `failed`

---

### Milestone 9 — AstrBot 插件最小桥接骨架

新建文件结构：

```
integrations/astrbot-plugin/
├── main.py          ← 重写：入口 on_y_command() + parse_y_command()
├── config.py        ← PluginConfig 数据类（新建）
├── api_client.py    ← HermesClient + HapiClient（新建）
├── command_router.py← 路由分发 + 帮助文本（新建）
└── handlers/
    ├── __init__.py  ← 注册表 + dispatch()（新建）
    ├── status.py    ← /y status（新建）
    ├── tasks.py     ← /y tasks（新建）
    ├── screen.py    ← /y screen（新建）
    ├── window.py    ← /y window（新建）
    ├── do.py        ← /y do（新建）
    └── codex.py     ← /y codex → Hapi 占位（新建）
```

**命令映射**：

| 命令 | 路由目标 | Bridge 端点 | 状态 |
|------|---------|------------|------|
| /y status | Hermes Bridge | GET /status | ✅ 最小实现 |
| /y tasks | Hermes Bridge | GET /tasks | ✅ 最小实现 |
| /y screen | Hermes Bridge | GET /screen/current | ✅ 元信息；图片待联调 |
| /y window | Hermes Bridge | GET /system/active-window | ✅ 最小实现 |
| /y do \<task\> | Hermes Bridge | POST /tasks | ✅ 最小实现 |
| /y codex \<task\> | Hapi | POST /codex | ⚠️ 占位，端点待确认 |

**仍为占位的部分**：
- `codex.py`：Hapi /codex schema 待确认
- `screen.py`：base64 → AstrBot 图片消息待联调
- AstrBot 宿主绑定：`on_y_command()` 入口已定义，与 AstrBot 事件系统挂钩待联调

## 下一步重点

**AstrBot 宿主绑定**：在 AstrBot 插件框架中注册 /y 命令，调用 `on_y_command(text, sender_id, config)`。


### 主界面展示的 Bridge 信息

| 展示内容 | 位置 | 说明 |
|--------|------|------|
| Bridge 启用状态 | card3 “运行信息” | ✅ 已启用 / ❌ 已禁用 |
| Bridge 地址 | card3 “运行信息” | <http://host:port> |
| AstrBot / QQ | 新增全宽集成服务卡 | ⏳ 未接入（占位） |
| Hapi / Codex | 新增全宽集成服务卡 | ⏳ 未接入（占位） |

### bubble 模式展示的精简状态

| 行 | 内容 |
|----|------|
| Bridge | ✅ 127.0.0.1:8420 / ❌ 已禁用 |
| AstrBot | ⏳ 未接入（占位） |

气泡模式不展示 Hapi，保持轻量；完整集成信息通过“打开主窗口”入口查看。

### AstrBot / QQ 接入状态占位

- `get_dashboard_data()` 返回 `integrations.astrbot.status = "not_connected"`
- `get_dashboard_data()` 返回 `integrations.hapi.status = "not_connected"`
- `get_bubble_data()` 返回 `astrbot.status = "not_connected"`
- 主界面和气泡均显示 `⏳ 未接入`
- 状态字符串设计为可扩展：后续改为 `connected` / `error` 即可最新展示

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/main_api.py | `get_dashboard_data()` 新增 bridge + integrations 字段 |
| apps/shell/window.py | card3 增 bridge 行，新增集成服务全宽卡 |
| apps/shell/modes/bubble.py | `get_bubble_data()` 增 bridge/astrbot，HTML/JS 增 2 行 |
| memory/progress/current-state.md | 更新 Milestone 7 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。

### bubble 模式新增能力

| 能力 | 说明 |
|------|------|
| 状态摘要 | 显示 Hermes Agent 就绪状态、工作空间初始化状态、运行时间 |
| 打开主窗口 | 在当前 pywebview 会话中创建第二个完整仪表盘窗口 |
| 刷新状态 | 手动刷新数据，15 秒自动刷新 |
| 关闭入口 | `close_bubble()` 销毁气泡窗口 |
| 常驻最前 | `on_top=True` 使气泡窗口保持在其他窗口上层 |

### bubble 与 window 模式的区别

| 对比项 | window 模式 | bubble 模式 |
|--------|-------------|-------------|
| 窗口尺寸 | 560×520，可调 | 320×280，固定 |
| 内容 | 完整仪表盘 + 可编辑设置面板 | 状态摘要 + 操作按钮 |
| API | MainWindowAPI（get_dashboard/settings/update） | BubbleWindowAPI（get_bubble_data/open_main/close） |
| on_top | 否 | 是（常驻最前） |
| 设置编辑 | ✅ 支持 | ❌ 不支持（通过「打开主窗口」进入完整设置） |

### open_main_window 实现说明

pywebview 支持在 API 回调中调用 `webview.create_window()`，新窗口会加入当前 `start()` 的事件循环。
当前实现：气泡窗口持有全局 `BubbleWindowAPI`（通过 `webview.start(api=api)`），主窗口以只读仪表盘形式创建，共享同一 webview 会话。

### main_api.py 同步变更

- `get_settings_data()` 中 bubble 的 `available` 改为 `True`
- 设置页可选模式下拉 bubble 选项对用户可见

### live2d 后续接入方式

live2d 保持占位实现不变。后续接入时只需修改 `apps/shell/modes/live2d.py`：

1. 替换 `_LIVE2D_HTML` 为嵌入 Live2D WebGL 渲染器的 HTML
2. 添加 `Live2DWindowAPI` 提供角色控制 / 互动接口
3. `main_api.py` 中 live2d 的 `available` 改为 `True`

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/modes/bubble.py | 重写为最小可用实现（BubbleWindowAPI + 状态摘要 UI） |
| apps/shell/main_api.py | bubble available 改为 True |
| memory/progress/current-state.md | 更新 Milestone 6 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。
3. `_start_normal_mode(config)` → `launch_mode(runtime, config)`
4. `launch_mode()` 根据 `config.display_mode` 分发到对应 runner

### app.py 变更

- 移除对 `create_main_window` 的直接导入
- `_start_normal_mode()` 末尾改为 `launch_mode(runtime, config)`
- 所有模式分支收敛到 `modes/`，`app.py` 无模式判断逻辑

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/modes/**init**.py | 实现 launch_mode() 分发器 |
| apps/shell/modes/window.py | 新建，窗口模式 runner |
| apps/shell/modes/bubble.py | 实现气泡模式占位 runner |
| apps/shell/modes/live2d.py | 实现 Live2D 模式占位 runner |
| apps/shell/app.py | 改用 launch_mode()，去掉 create_main_window 导入 |
| memory/progress/current-state.md | 更新 Milestone 6 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。

### 可编辑配置项实现

| 配置项 | 控件类型 | 位置 |
|--------|----------|------|
| 显示模式 | select 下拉（window/bubble/live2d） | 显示模式分组 |
| Bridge 开关 | toggle 开关 | Bridge 分组 |
| Bridge 地址 | input 文本框 | Bridge 分组 |
| Bridge 端口 | input 数字框（1024-65535） | Bridge 分组 |
| 系统托盘开关 | toggle 开关 | 应用分组 |

### config.py 扩展

- 新增 `bridge_enabled: bool = True` — Bridge 启用开关
- 新增 `tray_enabled: bool = True` — 系统托盘启用开关
- load_config() / save_config() 自动覆盖新字段

### main_api.py 扩展

- `get_settings_data()` 返回 bridge.enabled 和 app.tray_enabled 新字段
- 新增 `update_settings(changes)` 方法：
  - 白名单校验：仅允许 display_mode, bridge_enabled, bridge_host, bridge_port, tray_enabled
  - 类型校验：int/str/bool 分别验证，JS float→int 自动转换
  - 值域校验：display_mode 只接受 window/bubble/live2d，bridge_port 限 1024-65535
  - 通过后 setattr 修改运行时配置 + save_config() 持久化
  - 返回 {ok, applied, errors} 结构

### window.py 设置面板改造

- 显示模式：`<select>` 替代纯文本
- Bridge 开关：toggle 滑块
- Bridge 地址/端口：`<input>` 替代纯文本
- 系统托盘：toggle 滑块
- 新增 CSS：.s-select / .s-input / .s-toggle / .save-hint
- 新增 JS `onSettingChange(key, value)`：调用 update_settings + 显示保存结果 + 3秒后自动清除
- 修改后自动调用 refreshSettings() 同步最新值

### app.py 启动逻辑改造

- Bridge 启动受 `config.bridge_enabled` 控制（False 时跳过启动）
- 系统托盘启动受 `config.tray_enabled` 控制（False 时跳过启动）
- 退出清理逻辑同步适配开关状态

## 架构边界保持

- shell 是产品入口，config 由 shell 管理
- core 不暴露 HTTP
- bridge 只是内部通信桥，受 shell 配置控制
- 配置修改通过 WebView API（MainWindowAPI），不走 bridge HTTP

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/config.py | 新增 bridge_enabled、tray_enabled 字段 |
| apps/shell/main_api.py | 新增 update_settings()，settings data 增加新字段 |
| apps/shell/window.py | 设置面板改为可编辑控件，新增 CSS/JS |
| apps/shell/app.py | bridge/tray 启动受配置开关控制 |
| memory/progress/current-state.md | 更新 Milestone 5 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

实现 AstrBot 插件的 QQ 命令路由功能。

---

## Milestone 12 — 最小任务闭环

### 变更文件

| 文件 | 变更 |
|------|------|
| apps/core/state.py | 新增 update_task_status()，含终态保护 |
| packages/protocol/schemas.py | 新增 TaskGetResponse |
| apps/bridge/routes/tasks.py | 新增 GET /tasks/{task_id} 端点 |
| integrations/astrbot-plugin/api_client.py | 新增 get_task() + cancel_task() |
| integrations/astrbot-plugin/handlers/check.py | 新建：/y check <id> |
| integrations/astrbot-plugin/handlers/cancel.py | 新建：/y cancel <id> |
| integrations/astrbot-plugin/handlers/__init__.py | 注册 check + cancel |
| integrations/astrbot-plugin/command_router.py | HERMES_COMMANDS 更新，帮助文本更新 |
| integrations/astrbot-plugin/handlers/do.py | 输出完整 task_id + 使用提示 |

### 任务链路

- `/y do <描述>` → POST /tasks → 返回 task_id + 提示
- `/y tasks` → 列出全部任务
- `/y check <id>` → 查询单任务详情
- `/y cancel <id>` → 取消任务

### 下一步

AstrBot 宿主绑定：on_y_command() 与 AstrBot 事件系统挂钩。

---

## Milestone 13 — 任务状态最小推进

### 变更文件

| 文件 | 变更 |
|------|------|
| apps/core/task_runner.py | 新建：最小 asyncio 任务状态推进器 |
| apps/bridge/server.py | 新增 _lifespan，启动/停止 TaskRunner |
| integrations/astrbot-plugin/handlers/tasks.py | 状态标签改为完整文字 + updated_at |

### 任务状态链路

- PENDING → RUNNING（2s）→ COMPLETED（+5s），TaskRunner 在 Bridge lifespan 中启动
- cancel 直接置终态，TaskRunner 检测到终态冲突静默跳过
- 真实 Hermes 集成时只替换 `_execute()` 模拟逻辑

### 下一步

AstrBot 宿主绑定 / 真实 Hermes Agent 执行接入

---

## Milestone 14 — TaskRunner 执行策略抽象

### 变更文件

| 文件 | 变更 |
|------|------|
| apps/core/executor.py | 新建：ExecutionStrategy ABC + SimulatedExecutor + HermesExecutor 存根 |
| apps/core/task_runner.py | 重构：executor 策略注入，_execute_with_state() 纯状态机 |

### 接入 Hermes 路径

- 补全 `HermesExecutor.run()` → 传入 `TaskRunner(state, HermesExecutor())`
- 其余链路不变

---

## Milestone 15 — HermesExecutor 最小接入骨架

### 变更文件

| 文件 | 变更 |
|------|------|
| apps/core/executor.py | HermesExecutor 骨架：is_available()、run()、_call_hermes() 存根 + select_executor() 工厂 |
| apps/bridge/server.py | lifespan 改用 select_executor(rt)，导入整理 |

### 执行器选择逻辑

`select_executor(runtime)` 在 Bridge 启动时调用：
- `runtime.is_hermes_ready()` AND `HermesExecutor.is_available()` → 选 HermesExecutor
- 否则 → SimulatedExecutor（安全回退）

### 接 Hermes 还差什么

- `_call_hermes()` 实现（确认接口后：subprocess CLI 或 HTTP API）
- Hermes Agent 实际安装到测试机


---

## Milestone 16 — HermesExecutor 最小真实调用路径

### 变更文件

- apps/core/executor.py: 整体重写，HermesExecutor 实现 subprocess 调用路径

### 核心设计

- HermesCallError: 自定义异常，携带 returncode + stderr
- _call_hermes(): asyncio subprocess exec，60s 超时，超时后 proc.kill()
- fallback_to_simulated 开关：生产默认 False（FAILED 可见），调试可设 True
- CLI 命令集中在 _HERMES_CMD 常量，接口变更只改一处

### 接 Hermes 还差什么

- 确认 hermes run --prompt 是正确 CLI 接口
- 测试机安装 Hermes Agent
- (可选) 流式输出支持


---

## Milestone 17 — HermesExecutor 最小真实验证闭环

### 变更文件

| 文件 | 变更 |
|------|------|
| apps/core/executor.py | HermesInvokeResult dataclass + invoke_hermes_cli() 独立函数 + probe_hermes_available() |
| apps/core/task_runner.py | FAILED 时使用 HermesCallError.to_error_string() |

### 关键设计

- invoke_hermes_cli() 是最小调用单元，不抛异常，统一返回结构化结果
- CLI 接口变更只改 _HERMES_CMD 常量 + invoke_hermes_cli() 函数
- 失败信息完整保存到 TaskInfo.error（returncode + stderr）


---

## Milestone 18 — 真实 Hermes 安装流程

### 变更文件

| 文件 | 变更 |
|------|------|
| packages/protocol/enums.py | INSTALLING + INSTALL_FAILED 枚举值 |
| apps/installer/hermes_install.py | InstallResult dataclass + run_hermes_install() |
| apps/shell/installer_api.py | install_hermes() + get_install_progress() + recheck_status() |
| apps/shell/window.py | NOT_INSTALLED 界面新增一键安装+进度+重检流程 |

### 安装完成流程

NOT_INSTALLED → 点击安装 → 后台脚本 → 轮询进度 → recheck_status() → READY/INIT/失败


## Milestone 19 — 安装后环境刷新感知检测

三级探测策略：当前 PATH → 常见路径扫描 → 登录 Shell
`recheck_status()` 新增 `needs_env_refresh` 字段，前端区分"正常可用"与"需重启刷新PATH"两种成功路径。


## Milestone 20 — 安装成功后自动过渡闭环

PATH 注入 + 真正重启 + JS 流程修正。
安装完成后应用自动重拉起，进入 READY 或初始化向导，无中间悬停态。


## Milestone 21 — 初始化向导完整闭环

三处修复：API 始终挂载 + INITIALIZING 枚举 + init 进度 log。
首次启动 not_installed → installing → installed_not_initialized → initializing → ready → 主界面 全链路闭环。


## Milestone 22 — 统一启动决策层

新建 `apps/shell/startup.py`：StartupMode + 映射表 + launch()。
app.py 精简为加载配置后直接 launch(config)，状态分支不再分散。


## Milestone 23 — startup 决策层与显示模式衔接

DisplayMode 枚举 + resolve_display_mode() 加入 modes/__init__.py。
startup.py 同时表达两个决策维度：startup_mode + display_mode，都集中在一处记录。


## Milestone 24 — Live2D 模式骨架

live2d.py 新增 Live2DWindowAPI（状态/主窗口/设置），角色舞台区+状态条+工具栏 HTML 骨架。
与 bubble 模式边界：bubble 横版最小摘要，live2d 竖版角色舞台。
真正接入还差：live2d_renderer.py + load_model/play_motion API + canvas 替换。


## Milestone 25 — Live2D 模型配置入口骨架

新增 `Live2DConfig` dataclass 到 config.py（model_name/model_path/idle_motion_group/enable_expressions/enable_physics/window_on_top + is_model_configured()）。
AppConfig 新增 live2d 字段，load_config() 处理嵌套反序列化。
新建 `apps/shell/settings.py`：build_settings_html(config) → 独立设置窗口（live2d.open_settings() 使用）。
window.py 设置面板新增 Live2D 配置区块（7 个字段），refreshSettings() JS 填充 d.live2d。
main_api.py get_settings_data() 新增 live2d 键，包含所有配置 + renderer_available=False。
live2d.py model 字段改为读取 config.live2d，前端 label 分三态展示（加载中/已配置未加载/未配置）。


## Milestone 26 — Live2D 配置最小校验与状态闭环

新增 `ModelState` StrEnum（NOT_CONFIGURED / PATH_INVALID / PATH_VALID / LOADED）和 `Live2DConfig.validate()` 方法（检查路径是否存在）。
live2d.py model 字段加入 `state` 键，前端 label 用四态字典映射。
window.py 设置面板 s-l2d-configured → s-l2d-state，JS stateMap 四态着色。
main_api.py 新增 `model_state` 字段，settings.py 同步改为四态标签。


## Milestone 27 — Live2D 资源目录结构检查

ModelState 枚举新增 PATH_NOT_LIVE2D，共五态。
新增 check_live2d_model_dir()：检查 *.moc3 / *.model3.json（根目录 + 一级子目录）。
validate() 新增第三层检查：目录存在但无特征文件 → PATH_NOT_LIVE2D。
四处标签映射（live2d.py JS / window.py JS / settings.py）同步新增 path_not_live2d 条目。


## Milestone 28 — Live2D 最小模型信息摘要

新增 ModelSummary dataclass + scan_live2d_model_dir()：根目录→一级子目录顺序扫描 *.moc3 / *.model3.json，记录文件名、位置、extra count。
Live2DConfig.scan() 方法 → None 或 ModelSummary。
_serialize_summary() 辅助函数在 main_api.py，live2d.py 共用。
设置页（window.py + settings.py）新增三行：model3.json / moc3 / 文件位置。


## Milestone 29 — Live2D 摘要主候选入口整理

ModelSummary 新增 primary_model3_json_abs / primary_moc3_abs（绝对路径）+ renderer_entry property（model3.json 优先）。
scan_live2d_model_dir() 扫描时用 .resolve() 直接填充绝对路径。
_serialize_summary() 携带三个新字段，settings/window 新增"渲染器入口候选"行（小字绿/暗灰）。
接入模式文档化：renderer.load(summary.renderer_entry)。
