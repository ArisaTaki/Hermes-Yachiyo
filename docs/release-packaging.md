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
python scripts/build_release_candidate_artifacts.py --channel experimental --repository kuguya-AI-app-develop/oha-yachiyo
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
3. 运行关键 smoke tests。
4. 通过 `python scripts/prepare_app_build_metadata.py` 写入当前 channel / commit / latest URL 的 build metadata。
5. PyInstaller 构建后端，并把同一份 build metadata 打入后端可执行文件。
6. 如果配置了自签名证书，electron-builder 生成 `.app` 目录后由脚本签名 `.app` 并创建未签名 DMG；否则 electron-builder 直接生成 unsigned DMG。
7. Verify packaged app resources 会检查 `.app` 结构、后端可执行文件、`app.asar`、关键 UI selector 和 packaged resources 旧身份扫描；启用自签名时，还会对最终 packaged `.app` 运行 `codesign --verify --deep --strict --verbose=2`。
8. 生成版本化 DMG、latest DMG、SHA256、latest JSON 和 release notes。
9. 对 `release/` 目录执行 binary-safe release artifact scan，确认最终 DMG、JSON、checksum 和 notes 没有旧产品身份或旧执行内核 token，并校验每个 DMG 的 `.sha256` 文件、latest JSON 的 `name` / `channel` / `branch` / `source_branch` / `version` / `commit` / `short_commit` / `build_number` / `run_number` / `run_id` / `tag` / `signing` / `published_at` / `changelog` 元数据格式和一致性，以及 latest JSON 的 `dmg_name` / `sha256` 均与同目录 DMG 内容一致；随后运行最终 RC gate，并在配置真实 provider smoke secrets 时把 opt-in streaming/tool-call provider smoke 结果写入 `release/rc-verification.json`。
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

本地重新打包 RC 时，优先使用 `build_release_candidate_artifacts.py`。它会临时刷新 `.app` 和 packaged backend 共用的 build metadata、运行 PyInstaller 和 electron-builder，并在结束或失败时恢复 tracked `apps/frontend/public/oha-yachiyo-build.json` 开发占位，避免本地 RC evidence 因工作区 dirty 变成不可签核：

```bash
python scripts/build_release_candidate_artifacts.py --channel experimental --repository kuguya-AI-app-develop/oha-yachiyo
```

CI 仍直接运行 `python scripts/prepare_app_build_metadata.py`、`python scripts/build_backend.py --clean` 和 `npm --prefix apps/frontend run dist:mac`，因为 workflow 工作区不会把临时 metadata 改动提交回仓库。

如果要一次刷新当前 HEAD 的本地 RC evidence、Screen Recording attempt、provider-not-applicable 草稿和 final signoff preview，运行：

```bash
python scripts/refresh_local_rc_signoff.py --channel experimental --repository kuguya-AI-app-develop/oha-yachiyo
```

该命令会生成 `tmp/rc-verification-<short-commit>-packaged-batch.json`、`tmp/rc-verification-<short-commit>-screen.json`、`tmp/rc-signoff-<short-commit>-current.json`、`tmp/rc-signoff-<short-commit>-current.md` 和 `tmp/rc-signoff-<short-commit>-preview.json`；如果 final signoff 只因为 Gatekeeper / Screen Recording 仍为 `manual_required` 而失败，命令仍返回成功，方便把“还差多少”作为状态刷新而不是构建失败处理。签核人可以直接填写 Markdown checklist，再用 `--manual-checks-markdown` 进入最终 gate。

只查看当前 HEAD 还剩哪些签核项时，运行：

```bash
python scripts/refresh_local_rc_signoff.py --print-status
```

该命令只读取 `tmp/rc-signoff-<short-commit>-current.json` 并打印剩余项，不运行 build、DMG 或 UI gate。

需要按当前 draft 完成最后的 Gatekeeper / Screen Recording 收证时，可以先打印聚合操作指南；该命令只读已有 draft / screen report，不会写入 evidence，也不会把人工项标为通过：

```bash
python scripts/refresh_local_rc_signoff.py --print-os-signoff-guide
```

输出会列出当前 `tmp/rc-signoff-<short-commit>-current.json`、DMG、稳定 Screen Recording app path、稳定 backend executable path、可执行的 `open -R ...` / System Settings Screen Recording URL、授权后要 rerun 的 `--run-dmg-screen-smoke` 命令、`--write-os-evidence` 命令和最终 `--require-manual-checks-complete` 命令。只有在签核人实际完成 Finder Gatekeeper 首启和 Screen Recording 授权验证后，才能把对应 evidence 写入 OS evidence JSON。

Gatekeeper / Screen Recording 已人工确认后，可以生成只包含剩余 OS evidence 的小 JSON；该文件会继承当前 `tmp/rc-signoff-<short-commit>-current.json` 里的 `manual_release_candidate_check_source_revisions`，避免最终 gate 因人工证据缺少源码版本而失败：

```bash
SHORT_COMMIT="$(git rev-parse --short=8 HEAD)"
python scripts/refresh_local_rc_signoff.py \
  --write-os-evidence "tmp/rc-signoff-${SHORT_COMMIT}-os-evidence.json" \
  --gatekeeper-evidence "Mounted dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg and opened Oha-Yachiyo.app through Finder Control-click -> Open." \
  --screen-recording-evidence "Granted Screen Recording to tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app and its Contents/Resources/backend/oha-yachiyo-backend helper, then reran --run-dmg-screen-smoke successfully."
```

最终签核时先传当前自动 evidence draft，再传这个 OS evidence 文件，让后者只覆盖两个手动 OS 项：

```bash
python scripts/verify_release_candidate.py \
  --require-artifacts \
  --manual-checks-json "tmp/rc-signoff-${SHORT_COMMIT}-current.json" \
  --manual-checks-json "tmp/rc-signoff-${SHORT_COMMIT}-os-evidence.json" \
  --require-manual-checks-complete \
  --report-json "tmp/rc-signoff-${SHORT_COMMIT}-final.json"
```

如果一次刷新在 batch 或 screen 阶段后中断，可以断点续跑：

```bash
python scripts/refresh_local_rc_signoff.py --reuse-current-reports
```

该模式只会复用 `source_revision.commit` 能以当前 `<short-commit>` 为前缀且 `dirty=false` 的已有 batch / screen report；不匹配、缺失、损坏或 dirty 的 report 会照常重新生成，避免把旧 commit 的自动 evidence 合入当前 final signoff。

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

## 本地 RC 验收

本地 release candidate 产物生成后，先运行统一验收入口：

```bash
python scripts/verify_release_candidate.py --require-artifacts
```

该命令会运行 source-level release guard，并对已生成的 `dist/backend`、`dist/electron` 和 `release` 执行 binary/package verifier。需要确认 DMG 内真实 `.app` 也可扫描时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount
```

需要从 DMG 内真实 `.app` 启动并等待 packaged Bridge `/status` 时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-dmg-app-smoke
```

`--run-dmg-app-smoke`、`--run-dmg-screen-smoke` 和 `--run-dmg-ui-sampling-smoke` 的 RC report 都会在对应 `dmg_*` section 写入 `bridge_statuses`，记录 DMG 路径、`service`、`version`、`native_agent_ready` 和 packaged Bridge `/status` 返回的 `build_metadata`。`--run-dmg-chat-native-file-smoke` 还会在 `dmg_chat_native_file_smoke.uploads[*].app_build_metadata` 归档 packaged Electron app 暴露的 build metadata。如果打包时已刷新 `oha-yachiyo-build.json`，这些记录会把真实启动的 DMG 内 Bridge 或 Electron app 追溯到 commit / short commit；当当前 `source_revision.commit` 可用时，RC gate 也会要求 packaged `build_metadata.commit` / `app_build_metadata.commit` 与它一致，避免 stale DMG、旧 backend 或旧 Electron app 被误用于最终签核。

需要从 DMG 内真实 `.app` 抽样 packaged renderer 关键页面时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-dmg-ui-sampling-smoke
```

`--run-dmg-ui-sampling-smoke` 会启动 DMG 内 `.app`、等待 packaged Bridge `/status`，再通过 Chromium DevTools 端口抽样 Chat、Agent Studio、Workflow、Activity、Diagnostics、Proactive TTS 和 Live2D settings 的稳定 selector。通过时同一轮 gate 会把 `packaged_bridge_isolation` 和 `packaged_ui_sampling` 自动标为 `passed`；该 gate 不会打开系统原生文件选择器，因此 `chat_native_file_upload` 仍需人工确认 packaged app 的 OS file picker 弹窗。

需要从 DMG 内真实 `.app` 验证 Chat 原生图片选择、预览、发送、图片查看器和 Run Detail handoff 时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-dmg-chat-native-file-smoke
```

`--run-dmg-chat-native-file-smoke` 会启动 DMG 内 packaged Electron app，并在显式 smoke mode 下让主进程 `chooseChatImages` IPC 读取脚本生成的本地图片路径；随后通过 Chromium DevTools 点击 Chat 图片附件按钮，验证 attachment preview、发送 payload、message attachment、image viewer open/close 和 Run Detail replay handoff。report 会同时归档 packaged Electron app 的 `app_build_metadata`，并在当前 `source_revision.commit` 可用时拒绝 stale app build。通过时同一轮 gate 会把 `chat_native_file_upload` 自动标为 `passed`。正常用户运行不设置 smoke env，仍使用系统原生 file picker。

需要从 DMG 内真实 `.app` 验证屏幕录制权限和 `/screen/current` 路径时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-dmg-screen-smoke
```

`--run-dmg-screen-smoke` 会从 DMG 内复制 `.app` 到稳定的 `tmp/rc-screen-smoke/<dmg-name>/Oha-Yachiyo.app`，再启动该副本、等待 packaged Bridge `/status`，并请求 `/screen/current`。如果 macOS Screen Recording 权限未授权，RC report 会在 `dmg_screen_probe.app_launch_paths` 和 manual checklist supporting note 中写入这个稳定 app path 以及 `Contents/Resources/backend/oha-yachiyo-backend` backend executable path，方便签核人对实际执行截图的 helper 进程授权后复跑，而不是每次授权随机 mount path。通过时 RC report 只记录截图 `width`、`height`、`format`、`captured_at` 等元数据，不归档 `image_base64`；同一轮 gate 会把 `packaged_bridge_isolation` 和 `screen_recording_permission` 自动标为 `passed`。

具备真实 OpenAI-compatible provider smoke 凭据时，运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-provider-smoke
```

`--run-provider-smoke` 会复用 release workflow 的 opt-in provider smoke 合同，要求 `OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL` 和 `OHA_YACHIYO_SMOKE_API_KEY` 都已配置；它会分别验证文本流 `finish_reason=stop`，以及 `workspace_read` tool-call、`README.md` 参数、`path=README.md` JSON 字段、`finish_reason=tool_calls` 和 synthetic tool-result follow-up 的 `finish_reason=stop`。

需要把 Electron UI smoke 也纳入本地 RC gate 时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-ui-smoke
```

尚未重新打包、只想快速确认源码级 release guard 时，使用 source-only dry run：

```bash
python scripts/verify_release_candidate.py --source-only --report-json tmp/source-only-rc.json
```

`--source-only` 会跳过本机已有 `dist/` 或 `release/` 旧产物，避免 stale `.app` / DMG 干扰源码验收判断；最终 RC 仍必须重新打包并运行 `--require-artifacts`。
`--source-only` 不能和 artifact path、`--require-artifacts`、`--check-dmg-mount`、`--run-dmg-app-smoke`、`--run-dmg-screen-smoke`、`--run-dmg-ui-sampling-smoke`、`--run-dmg-chat-native-file-smoke`、`--run-provider-smoke` 或 `--run-ui-smoke` 混用；DMG mount、DMG app startup smoke、DMG screen recording smoke、DMG packaged UI sampling smoke、DMG Chat native file smoke、真实 provider smoke 和 Electron UI smoke 只属于完整本地 RC 复验。

macOS release workflow 会在生成 release metadata 后、上传 DMG 前运行 `python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --run-dmg-app-smoke --report-json release/rc-verification.json`，确保 CI 与本地 RC 验收入口一致，并把 `release/rc-verification.json` 作为可归档验收报告随 release artifacts 上传；RC report 会写入 `source_revision`，记录当前 git commit、short commit 和 dirty 状态。同一轮 RC report 生成后，workflow 也会生成并上传 `release/manual-rc-checks.template.json`，用于发布签核人从零填写 Gatekeeper、屏幕录制、原生图片上传、packaged UI 抽样以及任何未被自动 gate 证明的真实 provider evidence；随后输出的 `release/manual-rc-checks.draft.json` 已合并 `automated_rc_gate` evidence、source revision 摘要和 `release/electron-ui-smoke.json` 的 supporting notes，可直接补人工 evidence 后交给 `--manual-checks-json` 做最终签核；最终 RC report 也会把这些 manual evidence source revision 写入 `manual_release_candidate_check_source_revisions`，方便追溯 Gatekeeper / Screen Recording evidence 对应的源码版本；随后还会输出 `release/manual-rc-checks.md`，作为可读人工签核 checklist，并用同一个 `manual_release_candidate_check_source_revisions` 注释保留 source revision 链，避免 Markdown 签核路径丢失 traceability。打包前的 Electron UI smoke 由 `python scripts/run_electron_ui_smokes.py --report-json release/electron-ui-smoke.json` 动态发现并运行所有 `scripts/smoke_*_ui.mjs`，其结构化结果会作为 `release/electron-ui-smoke.json` 随 artifacts 上传。`--check-dmg-mount` 会只读挂载发现到的 DMG，并对 DMG 内真实 `.app` 的 `Contents/Resources` 再执行 packaged app scan；`--run-dmg-app-smoke` 会从 DMG 内启动真实 `.app` 并等待 packaged Bridge `/status`，通过后同一份 RC report 会把 `packaged_bridge_isolation` 标为 `passed`。本地最终复验可加 `--run-dmg-ui-sampling-smoke`，用真实 DMG 内 `.app` 自动填充 `packaged_ui_sampling` evidence；也可加 `--run-dmg-chat-native-file-smoke`，用真实 DMG 内 packaged Electron app 自动填充 `chat_native_file_upload` evidence。如果 `OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL` 和 `OHA_YACHIYO_SMOKE_API_KEY` 都已配置，workflow 会向同一个 RC gate 传入 `--run-provider-smoke`，让 report 的 `provider_smoke` 字段记录真实 provider 文本流与 tool-call follow-up 结果；如果这些 secrets 未完整配置，workflow 会向 RC report、draft 和 Markdown 传入 `--mark-provider-smoke-not-applicable-if-missing`，把归档签核材料中的 `real_provider_smoke` 标为 `not_applicable` 并写入缺失变量 evidence。带 `--run-dmg-screen-smoke` 的屏幕录制权限检查、带 `--run-dmg-ui-sampling-smoke` 的 packaged renderer 抽样、带 `--run-dmg-chat-native-file-smoke` 的 packaged Chat native file smoke 和带 `--run-ui-smoke` 的完整 Electron UI smoke 仍保留给本地 RC 复验，因为它们分别需要 Screen Recording 授权、真实 GUI renderer 抽样、packaged app GUI 或会启动额外 BrowserWindow。

脚本仍会列出首次启动 / Gatekeeper、屏幕录制权限、Chat 原生图片上传、packaged UI 抽样、packaged bridge 和真实 provider 的最终签核项，并在 `release/rc-verification.json` 中写入结构化 `manual_release_candidate_check_statuses` 与 `manual_release_candidate_check_summary`。这些条目默认是 `manual_required`，并带有稳定 id、证据说明和下一步动作；当前固定 id 包括 `gatekeeper_first_launch`、`packaged_bridge_isolation`、`screen_recording_permission`、`chat_native_file_upload`、`packaged_ui_sampling` 和 `real_provider_smoke`。summary 会给出 `remaining_count`、`remaining_check_ids`、`remaining_next_actions`、`remaining_commands`、`remaining_notes`、`failed_check_ids` 和 `automated_evidence_check_ids`，用于快速判断最终签核还差多少项、下一步该跑哪个 gate、可直接复制哪条自动收证命令，以及某个剩余项是否已有失败 gate 的 supporting notes。如果同一次 RC gate 中 `--run-dmg-app-smoke` 通过，`packaged_bridge_isolation` 会自动标为 `passed` 并写入 `evidence_source=automated_rc_gate`；如果 `--run-dmg-screen-smoke` 通过，`packaged_bridge_isolation` 和 `screen_recording_permission` 会自动标为 `passed`；如果 `--run-dmg-screen-smoke` 已到达 packaged Bridge 但 `/screen/current` 因权限失败，summary/status 输出会保留 `screen_recording_permission` 的 supporting note，直到授权后重新跑通；如果 `--run-dmg-ui-sampling-smoke` 通过，`packaged_bridge_isolation` 和 `packaged_ui_sampling` 会自动标为 `passed`；如果 `--run-dmg-chat-native-file-smoke` 通过，`chat_native_file_upload` 会自动标为 `passed`；如果 `--run-provider-smoke` 通过，`real_provider_smoke` 也会自动标为 `passed`。自动 evidence 只填充仍为 `manual_required` 的项，不会覆盖签核人已经写入的 `passed`、`failed` 或 `not_applicable`。可先生成人工验收模板：

```bash
python scripts/verify_release_candidate.py --write-manual-checks-template tmp/manual-rc-checks.json
```

已有上一轮 RC report 时，优先从 report 生成可编辑签核草稿，保留自动 gate 已填充的 evidence，并把仍需人工确认的项目留空：

```bash
python scripts/verify_release_candidate.py --manual-checks-json tmp/final-rc.json --write-manual-checks-draft tmp/final-rc-signoff.json
```

如果最终发布环境明确没有真实 provider credentials，可显式把 `real_provider_smoke` 写成 `not_applicable`，并自动附上缺失的 `OHA_YACHIYO_SMOKE_*` 变量名作为 evidence：

```bash
python scripts/verify_release_candidate.py --manual-checks-json tmp/final-rc.json --write-manual-checks-draft tmp/final-rc-signoff.json --mark-provider-smoke-not-applicable-if-missing
```

只想查看现有 RC report、draft 或 Markdown checklist 还剩哪些签核项时，使用只读状态命令；它不会运行 artifact / DMG / UI gate，也不会写出新文件：

```bash
python scripts/verify_release_candidate.py --manual-checks-json tmp/final-rc-signoff.json --print-manual-checks-status
```

已有人工 evidence 时可传入项目内 JSON：

```bash
python scripts/verify_release_candidate.py --require-artifacts --manual-checks-json tmp/final-rc-signoff.json --require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json
```

`--manual-checks-json` 可以重复传入，脚本会按命令行顺序合并 evidence；普通 `{ "checks": [...] }` 或 Markdown 转出的人工 evidence 后传入时可覆盖前一份里的同一 check。previous RC report 的 `manual_release_candidate_check_statuses` 合并时会保留先前已经通过、失败或 not_applicable 的自动 evidence，不会让后一份 report 里的 `manual_required` 抹掉已收集的自动 evidence。最终签核加 `--require-manual-checks-complete` 时，如果当前 git source revision 可用且工作区 dirty，RC gate 会失败并写入 `source_revision_final_signoff_findings`；如果传入外部 `--manual-checks-json` / `--manual-checks-markdown` 但没有 `manual_release_candidate_check_source_revisions`，会以 `final signoff requires manual release-candidate evidence source revisions` 失败；如果传入的 previous RC report / Markdown checklist 携带的 `manual_release_candidate_check_source_revisions` 是 dirty 或与当前 `source_revision.commit` 不一致，RC gate 也会失败并写入 `manual_release_candidate_check_source_revision_findings`。需要先提交或丢弃未提交改动、重新打包，并用当前源码重新生成或记录 manual evidence，再进行最终签核。这样可以先传多份自动 RC report，再传只包含人工补充项的小 JSON：

```bash
python scripts/verify_release_candidate.py --require-artifacts --manual-checks-json tmp/final-rc.json --manual-checks-json tmp/manual-evidence.json --require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json
```

如果最终发布环境明确没有真实 provider credentials，也可以在最终 RC gate 中显式传入 `--mark-provider-smoke-not-applicable-if-missing`，让 `real_provider_smoke` 在当前环境缺少任一 `OHA_YACHIYO_SMOKE_*` 变量时自动写入 `not_applicable` evidence，而不需要先手工编辑签核 JSON：

```bash
python scripts/verify_release_candidate.py --require-artifacts --manual-checks-json tmp/final-rc-signoff.json --mark-provider-smoke-not-applicable-if-missing --require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json
```

也可以直接把填好的 Markdown checklist 作为最终签核输入：

```bash
python scripts/verify_release_candidate.py --require-artifacts --manual-checks-markdown tmp/final-rc-signoff.md --require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json
```

也可以把同一份 JSON 输出为 Markdown checklist：

```bash
python scripts/verify_release_candidate.py --manual-checks-json tmp/final-rc-signoff.json --write-manual-checks-markdown tmp/final-rc-signoff.md
```

如果最终发布环境没有 provider credentials，也可以直接从 RC report 生成带 `real_provider_smoke=not_applicable` evidence 的 Markdown checklist：

```bash
python scripts/verify_release_candidate.py --manual-checks-json tmp/final-rc.json --write-manual-checks-markdown tmp/final-rc-signoff.md --mark-provider-smoke-not-applicable-if-missing
```

`--write-manual-checks-template` 输出的每项都带 `description`、`required_before`、`evidence_prompt`、空 `evidence` 和 `notes`，适合从零开始填写。`--write-manual-checks-draft` 会读取 `--manual-checks-json` 指向的上一轮 RC report 或 evidence JSON，输出同样可编辑、可再喂回 `--manual-checks-json` 的 `{ "checks": [...] }` 草稿；草稿会保留 `automated_rc_gate` evidence，并把仍是 `manual_required` 的项目 `evidence` 留空。`--write-manual-checks-markdown` 会读取同一份 evidence JSON 并输出可读 checklist，列出剩余人工项、下一步动作、可自动收证命令、需要记录的 evidence，以及已通过 / not_applicable 项的 evidence source；签核人也可以勾选并填写这份 Markdown，再用 `--manual-checks-markdown` 作为最终 gate 输入。生成 draft 或 Markdown 时，CLI 会立即打印同一套 progress、remaining ids 和 next actions，因此可以用已有 RC report 快速判断“还差多少”，不必为了看剩余项重跑完整 artifact / UI gate。源 RC report 如果包含已通过的 `electron_ui_smoke`，或把 `release/electron-ui-smoke.json` 作为额外 `--manual-checks-json` 传入，草稿会把通过的脚本列表预填到 `packaged_ui_sampling` 的 `Notes:`，并把 `smoke_chat_image_attachment_ui.mjs` 作为 `chat_native_file_upload` 的辅助 evidence 备注；该 source-level smoke 覆盖桌面 `chooseChatImages` API、hidden input fallback、CDP file input、preview、send、image viewer 和 Run Detail handoff，但仅凭 source-level Electron UI smoke 时，这两项仍保持 `manual_required`，只有 `--run-dmg-chat-native-file-smoke` 或人工 evidence 才会把 packaged `chat_native_file_upload` 标为通过。Markdown checklist 的填写规则是：保留 ``- [ ] `check_id` `` 表示该项仍是 `manual_required`；改成 ``- [x] `check_id` `` 表示通过，不写显式 `status` 会按 `passed` 解析；需要显式跳过或记录失败时，用 ``- [x] `check_id` - not_applicable`` 或 ``- [x] `check_id` - failed``。所有 `passed`、`failed` 和 `not_applicable` 项都必须填写非空 `Evidence:`，多行 evidence 可放在缩进续行中。`--mark-provider-smoke-not-applicable-if-missing` 可用于 RC report、draft 或 Markdown checklist；它只在 `real_provider_smoke` 仍为 `manual_required` 且当前环境缺少任一 `OHA_YACHIYO_SMOKE_*` 变量时写入 `not_applicable`，不会覆盖已经通过、失败或手工标记的 provider evidence。`--manual-checks-json` 支持顶层 list、`{ "checks": [...] }`，也支持直接传入上一轮 RC report 并读取其中的 `manual_release_candidate_check_statuses`；多份 JSON 会按传入顺序合并，其中 previous RC report 的 `manual_required` 不覆盖已有自动 evidence，后传入的人工 `{ "checks": [...] }` 仍可覆盖先前状态，因此自动 evidence 不需要手工复制到另一个模板文件。`--manual-checks-markdown` 支持脚本生成的 Markdown checklist 格式。每项至少包含 `id`、`status` 和必要时的 `evidence`。`status` 只能是 `manual_required`、`passed`、`failed` 或 `not_applicable`；`passed`、`failed` 和 `not_applicable` 必须带 evidence。未知 id、同一文件内重复 id、非法 status、缺 evidence 或显式 `failed` 都会让 RC gate 失败并写入 `manual_release_candidate_check_findings`。最终发布签核时加 `--require-manual-checks-complete`，任何在自动 evidence 和人工 evidence 合并后仍为 `manual_required` 的检查都会让 RC gate 失败。

后续如果要面向普通用户无 Gatekeeper 警告地分发，需要再补 Apple Developer ID 签名与 notarization；当前链路先保证可重复构建和可安装 DMG。
