# Hermes-Yachiyo 包体瘦身记录

更新时间：2026-05-12

## 本轮目标

- 确认旧 UI 功能已迁移后，删除不再被新版 open-design 路由使用的旧前端代码。
- 降低前端首屏 JS 压力，把重页面拆成按需加载 chunk。
- 优先处理 DMG 体积里最明显、最不该存在的可删内容：macOS 包不应携带完整 `node_modules` 和 Windows `node-pty` 预构建文件。
- 在不改变桌面体验和 HTTP API 的前提下，验证并收紧 PyInstaller backend 依赖。

## 已完成改动

### 前端源码瘦身

- 删除旧 UI 入口 `apps/frontend/src/views/MainView.tsx`。
- 删除只服务旧 `phase3-*` 工作台的 CSS。
- 删除旧 UI 专属样式：`dashboard-hermes-center`、`capability-config-card`、`hermes-secondary-actions`。
- 删除前已核对旧 `MainView` 使用的 `/ui/...` 接口，新版页面均已有对应入口或调用路径。

### 路由级拆包

- 在 `apps/frontend/src/App.tsx` 中使用 `React.lazy` / `Suspense`。
- 已按需拆分：
  - Chat
  - Installer
  - Diagnostics
  - ToolCenter
  - Mode/Prompt settings
  - Proactive/GPT-SoVITS settings
  - App Update
  - desktop Launcher
  - Live2D preview/runtime
- 当前仍留在主路径的大头：
  - `OpenDesignView.tsx`
- 已将 `Live2DPreviewStage` 与 Live2D renderer runtime 从 `LauncherView.tsx` 提取到独立模块，并在新版 Live2D 页面中动态导入。
- 已把 `LauncherView` 自身改成桌面表现态按需加载，主 open-design 页面不再静态拉入桌面 Launcher 交互代码。
- Live2D 页面保留 `App.tsx` 的路由级 keep-alive，并固定在同一个 React 槽位；首次进入后切换到其他页面不会卸载预览舞台。
- `Live2DPreviewStage` 会在模型就绪后写入 warm cache；同一个模型后续重建时不再反复显示加载态，体积影响仅为少量 JS 逻辑。

### 静态资源瘦身

- 将 `docs/open-design/logo.png` 从 1024×1024 压到 512×512。
- PNG 保留透明通道，文件体积从约 `1.3MB` 降到约 `73KB`。

### Electron 打包瘦身

- 收紧 `apps/frontend/electron-builder.yml`。
- 移除宽泛的：
  - `node_modules/**`
  - `asarUnpack: node_modules/node-pty/**`
- 只保留 macOS 运行必需内容：
  - `node-pty/package.json`
  - `node-pty/LICENSE`
  - `node-pty/lib/**`
  - `node-pty/prebuilds/darwin-arm64/**`
  - `node-pty/prebuilds/darwin-x64/**`
  - `node-addon-api/**`
- 收紧 `extraResources` 的 `assets` 拷贝范围，只带运行时会查找的：
  - `icon.png`
- 运行时窗口/Dock 图标优先使用 Electron 已放入 `Contents/Resources/icon.icns` 的应用图标，避免 `assets/icon.icns` 重复复制。
- 显式排除：
  - Windows `node-pty` prebuilds
  - `.pdb`
  - source trees
  - tests
  - sourcemaps
  - `deps/third_party/scripts/typings`

### PyInstaller backend 瘦身

- 将 Python 依赖中的 `uvicorn[standard]` 收紧为 `uvicorn`。
- Bridge 显式使用：
  - `loop="asyncio"`
  - `http="h11"`
  - `ws="none"`
  - `lifespan="on"`
- 新增 `packaging/pyinstaller_hooks/hook-uvicorn.py`，避免 PyInstaller 的第三方 uvicorn hook 收集整个 uvicorn 包。
- 在 `scripts/build_backend.py` 中显式排除当前未使用的 server extras：
  - `uvloop`
  - `watchfiles`
  - `httptools`
  - `websockets`
  - `wsproto`
  - `gunicorn`
- 保留 Pillow 格式支持，未裁剪 image codec，避免影响截图、头像、附件等图像体验。

## 验证结果

- `npm --prefix apps/frontend run build` 通过。
- `/tmp/hermes-yachiyo-pyinstaller-min-venv/bin/python scripts/build_backend.py --clean` 通过。
- PyInstaller 产物启动通过，并验证：
  - `/status`
  - `/ui/dashboard`
  - `/ui/launcher?mode=bubble`
  - `/ui/settings`
  - `/live2d/runtime`
- `/tmp/hermes-yachiyo-pyinstaller-min-venv/bin/python -m pytest` 通过：`492 passed, 1 warning`。
- `git diff --check` 通过。
- 用本地命令验证 macOS DMG 构建通过：
  - `CSC_IDENTITY_AUTO_DISCOVERY=false npm --prefix apps/frontend run dist:mac`
  - 签名回退到 ad-hoc，本地未做 notarization。

关键体积数据：

- 前端构建后 logo asset：约 `74.63KB`，原先约 `1.4MB`。
- 前端主 JS chunk：约 `236.66KB`（gzip 约 `72.10KB`）。
- 新增按需 chunk：`Live2DPreviewStage` 约 `8.38KB`（gzip 约 `3.71KB`），`LauncherView` 约 `29.14KB`（gzip 约 `10.64KB`）。
- 前端 `dist`：约 `1.1MB`（不含后续 Electron 壳体）。
- `dist-electron`：约 `100KB`。
- 新 PyInstaller backend：`dist/backend/hermes-yachiyo-backend` 约 `18MB`。
- 打包验证后 DMG：约 `129MB`。
- 打包验证后 `.app`：约 `285MB`。
- 打包验证后 `Contents/Frameworks`：约 `262MB`。
- 打包验证后 `Contents/Resources`：约 `23MB`，其中 backend 约 `18MB`，`app.asar` 约 `1.5MB`。
- 打包验证后 `Contents/Resources/assets` 只包含 `icon.png`，约 `640KB`。
- 打包验证后 `app.asar.unpacked/node_modules`：约 `548KB`。
- 原本本地 `node-pty/prebuilds`：约 `58MB`，其中大头是 Windows prebuild 和 `.pdb`。
- 打包验证后 `.app` 主要来自 Electron Framework。

## 结论

- 140MB 左右 DMG 的主要来源不是 React UI。
- Electron runtime/Chromium 是基础成本，压缩后仍会占据 DMG 的大部分。
- 本轮已移除最不合理的 node_modules 打包浪费，尤其是 Windows `node-pty` 文件。
- PyInstaller backend 已从旧本地约 `23MB` 降到约 `18MB`，release DMG 本地验证约 `129MB`，相对 148MB release 包有明显下降。
- 后续 DMG 体积如果仍偏大，最大头仍是 Electron Framework；继续压前端 UI 或 backend 的收益会逐步变小。

## 下一步候选项

1. 在正式 CI release 环境复测 notarized DMG 大小，确认是否接近本地 ad-hoc 的 `129MB`。
2. 如包体目标非常严格，再评估是否继续使用 Electron：
   - Electron 是当前体积下限的大头。
   - 替代方案如 Tauri 会显著降低壳体体积，但迁移成本和功能兼容风险更高。
3. 不建议继续裁剪 Pillow codec，除非明确接受减少可导入图片格式。
