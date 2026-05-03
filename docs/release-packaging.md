# Hermes-Yachiyo macOS 打包与发布

本文记录当前 macOS DMG 打包链路。目标是把 Yachiyo 做成独立桌面应用，而不是依赖开发机上的 Python、Node 或源码工作树。

## 发布渠道

- `main` 分支发布正式版 DMG。
- `develop` 分支发布实验版 DMG，并在 GitHub Release 中标记为 prerelease。
- Hermes Agent 自身仍按用户本机安装的 Hermes 更新来源运行；Yachiyo 的正式版/实验版不自动把 Hermes 上游 `main` 当成稳定来源。

## 本地打包

```bash
python -m pip install -e ".[packaging]"
npm ci --prefix apps/frontend
python scripts/build_backend.py --clean
npm --prefix apps/frontend run dist:mac
```

输出位置：

- Python 后端：`dist/backend/hermes-yachiyo-backend`
- Electron DMG：`dist/electron/*.dmg`

## 打包结构

Electron packaged 模式会启动：

```text
Hermes-Yachiyo.app/Contents/Resources/backend/hermes-yachiyo-backend
```

这由 `apps/frontend/electron/main.ts` 中的 packaged backend 路径控制。`scripts/build_backend.py` 使用 PyInstaller 把 `apps.desktop_backend.app` 冻结为单文件后端，`apps/frontend/electron-builder.yml` 再把它放进 Electron Resources。

## 权限与首次启动

主动桌面观察依赖 macOS 屏幕录制权限。开发模式下，TCC 权限可能落在 Terminal、Python、Electron 或启动器进程上，表现会不稳定；打包后用户只需要给 `Hermes-Yachiyo.app` 授权，链路更清楚。

首次启动需要检查：

- 系统设置 -> 隐私与安全性 -> 屏幕录制：允许 Hermes-Yachiyo。
- 如果读取当前窗口失败，再检查辅助功能或自动化权限。
- Hermes CLI、Web/Image/TTS provider 仍按工具中心和主控台配置读取用户本机配置。
- GPT-SoVITS 等本地 TTS 服务不会被打进 DMG，仍需要用户自己启动服务并填写地址。

## 自动发布

`.github/workflows/release-macos.yml` 会在 `main` 和 `develop` push 后执行：

1. 安装 Python 与 Node 依赖。
2. 运行关键 smoke tests。
3. PyInstaller 构建后端。
4. electron-builder 生成 DMG。
5. 上传 workflow artifact。
6. 创建 GitHub Release。

Release tag 格式：

```text
stable-v<版本>-<UTC时间>-<短SHA>
experimental-v<版本>-<UTC时间>-<短SHA>
```

后续如果要面向普通用户分发，需要再补 Apple Developer ID 签名与 notarization；当前链路先保证可重复构建和可安装 DMG。
