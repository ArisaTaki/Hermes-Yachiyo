# Oha-Yachiyo macOS 打包与发布

本文记录当前 macOS DMG 打包链路。目标是把 Yachiyo 做成独立桌面应用，而不是依赖开发机上的 Python、Node 或源码工作树。

## 发布渠道

- `main` 分支发布正式版 DMG。
- `develop` 分支发布实验版 DMG，并在 GitHub Release 中标记为 prerelease。
- Oha-Yachiyo 使用内置 Native Agent 运行时；正式版/实验版只由本仓库的发布渠道决定。

## 本地打包

```bash
python -m pip install -e ".[packaging]"
npm ci --prefix apps/frontend
python scripts/build_backend.py --clean
npm --prefix apps/frontend run dist:mac
```

输出位置：

- Python 后端：`dist/backend/oha-yachiyo-backend`
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
scripts/build_macos_self_signed_dmg.sh "Oha-Yachiyo Self Signed"
```

`MACOS_CODESIGN_IDENTITY` 是证书名，不是发布渠道名。自签名阶段建议使用中性的 `Oha-Yachiyo Self Signed`；`main` 和 `develop` 可以共用同一张自签名证书。发布渠道由分支、release tag、DMG 文件名和下载链接区分。

CI 中如果检测到 `MACOS_CODESIGN_CERTIFICATE_BASE64`，会自动导入证书、构建 `.app`、签名 `.app`，再打包未签名 `.dmg`。如果没有配置该 Secret，workflow 会退回完全 unsigned DMG，发布流程不会因此失败。

## 打包结构

Electron packaged 模式会启动：

```text
Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend
```

这由 `apps/frontend/electron/main.ts` 中的 packaged backend 路径控制。`scripts/build_backend.py` 使用 PyInstaller 把 `apps.desktop_backend.app` 冻结为单文件后端，`apps/frontend/electron-builder.yml` 再把它放进 Electron Resources。

打包版默认 Bridge 地址是 `http://127.0.0.1:18420`，开发模式默认是
`http://127.0.0.1:8420`。如果打包版启动时发现 `18420` 已被占用，会临时
分配一个空闲本地端口并传给内置 Python backend，避免连接到本地 develop
环境的旧 backend。

## 权限与首次启动

主动桌面观察依赖 macOS 屏幕录制权限。开发模式下，TCC 权限可能落在 Terminal、Python、Electron 或启动器进程上，表现会不稳定；打包后用户只需要给 `Oha-Yachiyo.app` 授权，链路更清楚。

首次启动需要检查：

- 系统设置 -> 隐私与安全性 -> 屏幕录制：允许 Oha-Yachiyo。
- 如果读取当前窗口失败，再检查辅助功能或自动化权限。
- Web/Image/TTS provider 与模型配置仍按工具中心和主控台读取用户本机配置。
- GPT-SoVITS 等本地 TTS 服务不会被打进 DMG，仍需要用户自己启动服务并填写地址。

## 自动发布

`.github/workflows/release-macos.yml` 会在 `main` 和 `develop` push 后执行：

1. 先运行 release-facing product identity and security guards，确认发布配置、旧产品身份扫描、debug route、CredentialStore fallback 和关键 smoke 清单没有退化。
2. 安装 Python 与 Node 依赖。
3. 运行关键 smoke tests；如果配置了真实 provider smoke secrets，还会执行 opt-in streaming/tool-call provider smoke。
4. 写入当前 channel / commit / latest URL 的 build metadata。
5. PyInstaller 构建后端，并把同一份 build metadata 打入后端可执行文件。
6. 如果配置了自签名证书，electron-builder 生成 `.app` 目录后由脚本签名 `.app` 并创建未签名 DMG；否则 electron-builder 直接生成 unsigned DMG。
7. Verify packaged app resources 会检查 `.app` 结构、后端可执行文件、`app.asar`、关键 UI selector 和 packaged resources 旧身份扫描；启用自签名时，还会对最终 packaged `.app` 运行 `codesign --verify --deep --strict --verbose=2`。
8. 生成版本化 DMG、latest DMG、SHA256、latest JSON 和 release notes。
9. 对 `release/` 目录执行 binary-safe release artifact scan，确认最终 DMG、JSON、checksum 和 notes 没有旧产品身份或旧执行内核 token，并校验每个 DMG 的 `.sha256` 文件、latest JSON 的 `name` / `channel` / `branch` / `source_branch` / `version` / `commit` / `short_commit` / `build_number` / `run_number` / `run_id` / `tag` / `signing` / `published_at` / `changelog` 元数据格式和一致性，以及 latest JSON 的 `dmg_name` / `sha256` 均与同目录 DMG 内容一致。
10. 上传 workflow artifact，并创建或更新 GitHub Release 与 latest channel release。

Release tag 格式：

```text
stable-v<产品版本>-build.<构建号>-<短SHA>
alpha-v<产品版本>-build.<构建号>-<短SHA>
experimental-v<产品版本>-build.<构建号>-<短SHA>
```

产品版本由 `pyproject.toml` 管理，采用 SemVer，例如 Phase 4 对应 `0.4.0`。每次 workflow 运行只更新 `build_number`，不会再把 `GITHUB_RUN_NUMBER` 加进 patch 版本；同一产品版本下的不同构建由 `build_number`、短 SHA 和 tag 区分。需要升级产品版本时运行：

```bash
python scripts/app_version.py set 0.4.0
python scripts/app_version.py check
```

固定下载链接：

- 最新正式版 DMG：<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases/latest/download/Oha-Yachiyo-main-latest.dmg>
- 最新正式版滚动 release：<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases/download/main-latest/Oha-Yachiyo-main-latest.dmg>
- 最新 Alpha 版 DMG：<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases/download/alpha-latest/Oha-Yachiyo-alpha-latest.dmg>
- 最新实验版 DMG：<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases/download/develop-latest/Oha-Yachiyo-develop-latest.dmg>

`main` 的版本化 release 会显式标记为 GitHub Latest，并额外上传 `Oha-Yachiyo-main-latest.dmg`，因此门户网站可以使用 `releases/latest/download/...`。`alpha` 与 `develop` 都是 prerelease，GitHub 的 `releases/latest` 不会稳定指向它们，所以 workflow 分别维护 `alpha-latest` 与 `develop-latest` 滚动 release。

渠道区分规则：

- `main` -> `stable` release，固定 DMG 名为 `Oha-Yachiyo-main-latest.dmg`。
- 手动 `alpha` -> `alpha` prerelease，固定 DMG 名为 `Oha-Yachiyo-alpha-latest.dmg`。
- `develop` -> `experimental` prerelease，固定 DMG 名为 `Oha-Yachiyo-develop-latest.dmg`。

固定 DMG 旁边会同时发布同名 `.sha256` 和 `.json` 文件，门户或安装页可以用它们展示版本、commit 和校验值。

Release workflow 会基于当前渠道上一条 `stable-v*` / `alpha-v*` / `experimental-v*` tag 生成更新日志。更新日志来源是 `git log`，会按 commit 前缀粗分为“新增/改进”“修复”“工程/发布”“文档”“测试”“重构/优化”等分组，并同时写入：

- 版本化 GitHub release notes。
- `main-latest` / `alpha-latest` / `develop-latest` 滚动 release notes。
- 固定 latest JSON 的 `changelog` 字段，应用内“应用更新”页面会直接展示这份更新内容。

后续如果要面向普通用户无 Gatekeeper 警告地分发，需要再补 Apple Developer ID 签名与 notarization；当前链路先保证可重复构建和可安装 DMG。
