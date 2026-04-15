# Session Summary

## 本轮完成内容 — Milestone 10: AstrBot Handler 输出格式完善

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
