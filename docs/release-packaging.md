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

## 免费自签名打包

免费试用阶段可以使用自签名证书让 `.app` 具备签名完整性，但不要自签名 `.dmg`。实测自签名且未公证的 DMG 会被 macOS 在挂载前直接拒绝，提示“Apple 无法验证此 DMG 是否包含可能危害 Mac 安全或泄漏隐私的恶意软件”。当前策略是：`.app` 自签名，`.dmg` 保持未签名，让用户至少能挂载安装包；首次启动应用时仍会看到未知开发者 / Gatekeeper 提示，需要使用 Finder 的 Control-click -> Open，或在系统设置的“隐私与安全性”中允许打开。

本地生成自签名证书：

```bash
scripts/create_macos_self_signed_cert.sh
```

该脚本会在 `dist/signing/` 下生成 p12、base64 和 GitHub Secrets 辅助文件，并默认导入当前用户的 login keychain。`dist/` 已被 `.gitignore` 排除，不要把这些文件提交到仓库。

需要在 GitHub 仓库 Secrets 中配置：

```text
MACOS_CODESIGN_CERTIFICATE_BASE64
MACOS_CODESIGN_CERTIFICATE_PASSWORD
MACOS_CODESIGN_IDENTITY
```

本地使用自签名证书构建 DMG：

```bash
python scripts/build_backend.py --clean
scripts/build_macos_self_signed_dmg.sh "Hermes-Yachiyo Self Signed"
```

`MACOS_CODESIGN_IDENTITY` 是证书名，不是发布渠道名。自签名阶段建议使用中性的 `Hermes-Yachiyo Self Signed`；`main` 和 `develop` 可以共用同一张自签名证书。发布渠道由分支、release tag、DMG 文件名和下载链接区分。

CI 中如果检测到 `MACOS_CODESIGN_CERTIFICATE_BASE64`，会自动导入证书、构建 `.app`、签名 `.app`，再打包未签名 `.dmg`。如果没有配置该 Secret，workflow 会退回完全 unsigned DMG，发布流程不会因此失败。

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
4. 如果配置了自签名证书，electron-builder 生成 `.app` 目录后由脚本签名 `.app` 并创建未签名 DMG；否则 electron-builder 直接生成 unsigned DMG。
5. 上传 workflow artifact。
6. 创建 GitHub Release。

Release tag 格式：

```text
stable-v<发布版本>-<短SHA>
experimental-v<发布版本>-<短SHA>
```

发布版本由 `pyproject.toml` 的基础版本加上 `GITHUB_RUN_NUMBER` 生成，例如基础版本 `0.1.0` 在第 20 次 workflow 运行时会生成 `0.1.20`。

固定下载链接：

- 最新正式版 DMG：<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/latest/download/Hermes-Yachiyo-main-latest.dmg>
- 最新正式版滚动 release：<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/download/main-latest/Hermes-Yachiyo-main-latest.dmg>
- 最新实验版 DMG：<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/download/develop-latest/Hermes-Yachiyo-develop-latest.dmg>

`main` 的版本化 release 会显式标记为 GitHub Latest，并额外上传 `Hermes-Yachiyo-main-latest.dmg`，因此门户网站可以使用 `releases/latest/download/...`。`develop` 是 prerelease，GitHub 的 `releases/latest` 不会稳定指向它，所以 workflow 维护 `develop-latest` 这个滚动 release。

渠道区分规则：

- `main` -> `stable` release，固定 DMG 名为 `Hermes-Yachiyo-main-latest.dmg`。
- `develop` -> `experimental` prerelease，固定 DMG 名为 `Hermes-Yachiyo-develop-latest.dmg`。

固定 DMG 旁边会同时发布同名 `.sha256` 和 `.json` 文件，门户或安装页可以用它们展示版本、commit 和校验值。

后续如果要面向普通用户无 Gatekeeper 警告地分发，需要再补 Apple Developer ID 签名与 notarization；当前链路先保证可重复构建和可安装 DMG。
