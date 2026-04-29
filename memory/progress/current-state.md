# Current State

## 已完成

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

### Milestone 71 — 受保护路径集合缓存

- ✅ `protected_paths()` 改为复用按当前 home 路径缓存的受保护路径集合，避免备份导入/卸载安全检查中反复执行多组 `exists()` / `resolve()`。
- ✅ `is_protected_path()` 直接查询缓存的 `frozenset`，不再为每次判断重新构造受保护路径集合。
- ✅ 移除 `protected_paths()` 中不可达且引用未定义 `home` 的旧 return，避免静态检查与后续维护误判。

### Milestone 70 — 备份 ZIP 解压实际写入限流

- ✅ `_extract_zip_safely()` 不再只依赖 `ZipInfo.file_size` 头部声明；解压成员改为分块读写，并按实际写入字节数校验单条目和总解压体积限制。
- ✅ 解压过程中一旦实际写入量超出单条目或总量限制，会中止并删除当前部分输出文件，避免恶意 ZIP 通过虚假 header 触发磁盘填充风险。
