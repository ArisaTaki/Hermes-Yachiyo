# Session Summary

## 本轮完成内容 — Milestone 40: Hermes 就绪状态细化分级

### 问题

1. **版本显示错误**：`hermes --version` 输出为多行，旧解析器扫描全部 token 命中 `3.11.12`（Python 版本），未能提取 `v0.9.0`（Hermes 版本）
2. **状态二元**：UI 显示"已就绪"但实际有 7 项工具受限，用户无法感知
3. **`hermes doctor` 信息未被消费**

### 根因

- `hermes --version` 第一行：`Hermes Agent v0.9.0 (2026.4.13)`；Python 版本 `3.11.12` 出现在后续行
- `HermesInstallStatus.READY` 是二元状态，不描述能力完整程度

### 解决方案

新增 `HermesReadinessLevel`（`basic_ready` / `full_ready` / `unknown`）与 `check_hermes_doctor_readiness()` 函数：

| 分级 | 含义 |
|------|------|
| `basic_ready` | 可运行，但部分工具受限（当前实测状态） |
| `full_ready` | 零 issue，完整就绪 |
| `unknown` | doctor 超时/失败，不阻塞启动 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `packages/protocol/enums.py` | 新增 `HermesReadinessLevel` |
| `packages/protocol/install.py` | `HermesInstallInfo` 新增 readiness 字段 |
| `apps/installer/hermes_check.py` | 修复版本解析；新增 `check_hermes_doctor_readiness()` |
| `apps/core/runtime.py` | `get_status()` 包含 readiness 数据 |
| `apps/shell/main_api.py` | 传递 readiness 数据到前端 |
| `apps/shell/window.py` | 仪表盘/设置面板：分级显示状态 + 受限工具列表 |

### 当前环境实测

```
version: 0.9.0  (修复前误显示 3.11.12)
readiness_level: basic_ready
limited_tools: homeassistant, image_gen, moa, rl, messaging, vision, web
doctor_issues_count: 1  (建议 hermes setup)
```

### UI 展示效果

- 仪表盘 Hermes 卡：`⚠️ 基础可用 · 部分工具受限` + 受限工具行
- 设置面板：能力就绪行 + 受限工具行（含"运行 hermes setup 可补全"提示）

### 已验证通过链路

install → setup → workspace init → ready → normal mode → runtime → bridge → tray (GCD) → **readiness 分级显示**

### 如何接手

```bash
cd /Users/hacchiroku/AI/Hermes-Yachiyo
.venv/bin/python -m apps.shell.app
```

### 下一步建议

1. **Task 系统真实 CLI 联调**
2. **AstrBot 真实 QQ 联调**
3. **Live2D 渲染器**
4. **Bridge HTTPS/认证**

---

## 历史记录 — Milestone 39: 修复 GCD dispatch_get_main_queue 符号不可用

### 问题

`AttributeError: dlsym(RTLD_DEFAULT, dispatch_get_main_queue): symbol not found`

Milestone 38 实现的 GCD 方案在实际运行时报错，因为 `dispatch_get_main_queue` 在 macOS libdispatch 中是内联函数，不作为符号导出，`ctypes.CDLL(None).dispatch_get_main_queue` 失败。

### 根因

```c
// Apple libdispatch 真实定义（内联，不导出符号）：
DISPATCH_INLINE DISPATCH_ALWAYS_INLINE
dispatch_queue_main_t dispatch_get_main_queue(void) {
    return DISPATCH_GLOBAL_OBJECT(dispatch_queue_main_t, _dispatch_main_q);
}
```

底层对象 `_dispatch_main_q` 是稳定导出的符号，其地址 = 主队列句柄。

### 修复

```python
# 旧（symbol not found）:
lib.dispatch_get_main_queue.restype = ctypes.c_void_p
queue = lib.dispatch_get_main_queue()

# 新（正确）:
main_q_obj = ctypes.c_void_p.in_dll(lib, "_dispatch_main_q")
queue = ctypes.addressof(main_q_obj)
```

同时在 `create_tray_macos()` 加 try/except 受控降级，GCD 失败时跳过 tray 不崩溃。

### 修改文件

| 文件 | 变更 |
|------|------|
| `apps/shell/tray.py` | `_dispatch_to_main_queue()` 取主队列方式从 `dispatch_get_main_queue()` 改为 `_dispatch_main_q` 取址；`create_tray_macos()` 加 try/except 降级 |

### 已验证通过链路

Hermes 安装 → setup → workspace init → ready → normal mode → runtime → bridge → **tray GCD 方案（修复）**

### 如何接手

```bash
cd /Users/hacchiroku/AI/Hermes-Yachiyo
.venv/bin/python -m apps.shell.app
```

### 下一步建议

1. **Task 系统真实 CLI 联调** — HermesExecutor 有 CLI 调用骨架，需真机测试
2. **AstrBot 真实 QQ 联调** — handler 已覆盖测试
3. **Live2D 渲染器** — 配置/校验/摘要层完备，可开始 moc3 渲染
4. **Bridge HTTPS/认证** — 当前无认证，生产环境需要

---

## 历史记录 — Milestone 38: macOS 托盘主线程修复

### 问题

进入 normal mode 后，`system-tray` 子线程调用 `create_tray()` → pystray 0.19.5 darwin 后端在 `__init__` 中直接创建 AppKit UI 对象（NSStatusBar / NSStatusItem 等）→ `NSWindow should only be instantiated on the main thread!` → 崩溃。

### 根因

- pystray darwin 后端的构造函数直接调用 `AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_()` 等，必须主线程
- 原代码用 `threading.Thread` 在子线程启动 `create_tray()` → `icon.run()` → 违反 macOS AppKit 线程要求

### 解决方案

利用 **GCD `dispatch_async_f`** + **pystray `run_detached()`**：

- `_dispatch_to_main_queue(fn)` — 在 `webview.start()` 前从主线程调用，将回调入队 GCD 主队列
- GCD 主队列与主线程 run loop 绑定：`NSApp.run()` 启动后自动在主线程执行回调
- 回调中构造 `pystray.Icon(...)` + 调用 `icon.run_detached()`
- `pystray._darwin._run_detached()` 只做 `_mark_ready()`，不运行第二个 NSApp 事件循环
- 图标通过 pywebview 已运行的 NSApp 接收系统事件

### 修改文件

| 文件 | 变更 |
|------|------|
| `apps/shell/tray.py` | 新增 `_GCD_CALLBACKS`, `_dispatch_to_main_queue()`, `create_tray_macos()`, `_create_tray_main_thread()` |
| `apps/shell/startup.py` | macOS 调 `create_tray_macos()`，其余平台保持 threading.Thread |

### 修复后启动流程

```
main thread: create_tray_macos(runtime)  ← GCD 入队（非阻塞）
main thread: launch_mode() → webview.start() → NSApp.run() 开始
                                              ↓
                              GCD 主队列处理（主线程）：
                              pystray.Icon() 构造 ✓
                              icon.run_detached() 激活 ✓
                              托盘图标挂载到 pywebview NSApp 循环 ✓
```

### 已验证通过链路

Hermes 安装 → setup → workspace init → 自动重启 → ready → normal mode → runtime → bridge → **tray（修复后）**

### 如何接手

```bash
# 运行桌面应用（使用 venv 中的 Python）
cd /Users/hacchiroku/AI/Hermes-Yachiyo
.venv/bin/python -m apps.shell.app
```

### 下一步建议

1. **Task 系统真实 CLI 联调** — HermesExecutor 有 CLI 调用骨架，需真机测试
2. **AstrBot 真实 QQ 联调** — handler 已覆盖测试
3. **Live2D 渲染器** — 配置/校验/摘要层完备，可开始 moc3 渲染
4. **Bridge HTTPS/认证** — 当前无认证，生产环境需要

### 问题

上一轮已将 `hermes setup` 阶段纳入状态流，但缺少：

1. `setup_in_progress` 状态 — 无法区分"需要 setup"和"setup 正在运行"
2. 进程检测 — 无法检测 `hermes setup` 是否已在终端运行
3. 防重复启动 — 用户可能重复点击"开始配置"打开多个终端

### 解决方案

将状态流从四级扩展为五级：

```
NOT_INSTALLED → INSTALLED_NEEDS_SETUP → SETUP_IN_PROGRESS → INSTALLED_NOT_INITIALIZED → READY
     安装引导        Setup 配置引导       Setup 进行中         工作空间初始化         正常模式
```

### 修改文件

| 文件 | 变更 |
|------|------|
| packages/protocol/enums.py | 新增 `SETUP_IN_PROGRESS` 枚举值 |
| apps/installer/hermes_check.py | 新增 `is_hermes_setup_running()` 进程检测 + 检测链集成 |
| apps/installer/hermes_install.py | 新增 `SETUP_IN_PROGRESS` 安装指导分支 |
| apps/shell/startup.py | 映射 `SETUP_IN_PROGRESS → INSTALLER` |
| apps/shell/installer_api.py | `open_hermes_setup_terminal()` 防重复 + 新增 `check_setup_process()` |
| apps/shell/window.py | Setup UI 增强：进程状态提示 + 轮询 + 防重复按钮 |
| tests/test_startup.py | 新增 `test_setup_in_progress_to_installer` |

### Setup 引导 UI

- 窗口标题：「Hermes-Yachiyo - 配置 Hermes Agent」
- 状态栏：蓝色 info 样式，显示「Hermes Agent 已安装，需要完成初始配置」
- 操作区：
  - 「开始配置 Hermes」按钮 → 打开 Terminal.app 执行 `hermes setup`
  - 「我已完成配置，重新检测」按钮 → recheck_status() → 按结果跳转

### macOS Terminal 拉起实现

使用 osascript AppleScript：

```applescript
tell application "Terminal"
    activate
    do script "hermes setup"
end tell
```

### 用户流程闭环

1. 安装完成 → recheck 检测到 `installed_needs_setup` → 自动重启进入 setup 引导
2. 用户点击「开始配置 Hermes」→ Terminal.app 打开并执行 `hermes setup`
3. 用户在终端完成交互式配置
4. 用户回到应用点击「重新检测」
5. 检测通过 → 进入工作空间初始化 → 完成 → 正常模式

### 如何接手

| test_protocol.py | 14 | Enum、TaskInfo、Request/Response 模型 |
| test_state.py | 11 | 任务创建/取消/状态推进/终态保护 |
| test_executor.py | 7 | HermesCallError、SimulatedExecutor |
| test_effect_policy.py | 9 | 设置生效策略查询和混合效果 |
| test_integration_status.py | 11 | Bridge/AstrBot/Hapi 状态 + config_dirty |
| test_astrbot_handlers.py | 32 | 全 handler 输出、ACL、错误格式化 |
| test_startup.py | 6 | startup 决策树全路径 |

### 关键技术决策

- **astrbot-plugin 连字符目录**：使用 `importlib.util.spec_from_file_location` 注册为 `astrbot_plugin` 包解决导入问题
- **Bridge mock 注入**：conftest 在测试加载前注入 fake uvicorn/fastapi modules，避免真实服务依赖
- **pytest-asyncio strict mode**：所有异步 handler 测试使用 `@pytest.mark.asyncio` 标注

### 如何接手

```bash
# 运行全部测试
cd /path/to/Hermes-Yachiyo
.venv/bin/python -m pytest tests/ -v

# 运行桌面应用
.venv/bin/python -m apps.shell.app

# 测试依赖
pip install pytest pytest-asyncio httpx
```

### 下一步建议

1. **Task 系统真实 CLI 联调** — 当前 HermesExecutor 有 CLI 调用骨架但未经真机测试
2. **AstrBot 真实 QQ 联调** — handler 输出已覆盖测试，可尝试真实 AstrBot 环境接入
3. **Live2D 渲染器** — 配置/校验/摘要层已完备，可开始 moc3 渲染实现
4. **Bridge HTTPS/认证** — 当前 bridge 无认证，生产使用需增加
