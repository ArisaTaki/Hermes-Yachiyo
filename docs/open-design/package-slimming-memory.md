# Hermes-Yachiyo 包体瘦身记录

更新时间：2026-05-12

## 本轮目标

- 确认旧 UI 功能已迁移后，删除不再被新版 open-design 路由使用的旧前端代码。
- 降低前端首屏 JS 压力，把重页面拆成按需加载 chunk。
- 优先处理 DMG 体积里最明显、最不该存在的可删内容：macOS 包不应携带完整 `node_modules` 和 Windows `node-pty` 预构建文件。

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
- 当前仍留在主路径的大头：
  - `OpenDesignView.tsx`
  - `LauncherView.tsx`
- 原因：新版 Live2D 设置页复用了 `LauncherView` 里的 `Live2DPreviewStage`，所以 Launcher/Live2D 渲染相关代码还会进入主路径。下一轮如果要继续优化加载时间，应先拆 Live2D preview runtime。

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
- 显式排除：
  - Windows `node-pty` prebuilds
  - `.pdb`
  - source trees
  - tests
  - sourcemaps
  - `deps/third_party/scripts/typings`

## 验证结果

- `npm --prefix apps/frontend run build` 通过。
- `git diff --check` 通过。
- 用临时命令验证 macOS `.app` 目录构建通过：
  - `electron-builder --mac dir`
  - 临时禁用 backend resources 和签名，仅验证 builder 文件规则。

关键体积数据：

- 前端 `dist`：约 `2.4MB`。
- `dist-electron`：约 `100KB`。
- 打包验证后 `Contents/Resources`：约 `4.5MB`。
- 打包验证后 `app.asar.unpacked/node_modules`：约 `444KB`。
- 原本本地 `node-pty/prebuilds`：约 `58MB`，其中大头是 Windows prebuild 和 `.pdb`。
- 打包验证后 `.app` 仍约 `276MB`，主要来自 Electron Framework。

## 结论

- 140MB 左右 DMG 的主要来源不是 React UI。
- Electron runtime/Chromium 是基础成本，压缩后仍会占据 DMG 的大部分。
- 本轮已移除最不合理的 node_modules 打包浪费，尤其是 Windows `node-pty` 文件。
- 后续 DMG 体积如果仍偏大，应优先检查 packaged Python backend，而不是继续压前端 UI。

## 下一步候选项

1. 完整 CI/本地 DMG 构建后记录：
   - `dist/backend/hermes-yachiyo-backend`
   - `.app/Contents/Resources`
   - `.app/Contents/Frameworks`
   - 最终 DMG
2. 优化 PyInstaller backend：
   - 查看实际二进制大小。
   - 根据依赖树排除无用模块。
   - 谨慎处理 `Pillow`、`uvicorn[standard]`、`pydantic`、`fastapi` 的隐式依赖。
3. 拆分 `Live2DPreviewStage`：
   - 从 `LauncherView.tsx` 中提取 preview/runtime 公共模块。
   - 让桌面表现态 Launcher 不再被主 open-design 页面静态拉入。
4. 压缩静态资源：
   - `docs/open-design/logo.png` 当前约 `1.3MB`。
   - 收益小，但风险低。
5. 如包体目标非常严格，再评估是否继续使用 Electron：
   - Electron 是当前体积下限的大头。
   - 替代方案如 Tauri 会显著降低壳体体积，但迁移成本和功能兼容风险更高。
