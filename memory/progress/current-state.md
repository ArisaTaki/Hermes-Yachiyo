# Current State

## 已完成

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
