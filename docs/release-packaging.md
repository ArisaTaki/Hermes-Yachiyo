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

本地重新打包 RC 前，先刷新 `.app` 和 packaged backend 共用的 build metadata，确保产物可追溯到当前 commit：

```bash
python scripts/prepare_app_build_metadata.py --channel experimental
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

需要从 DMG 内真实 `.app` 验证屏幕录制权限和 `/screen/current` 路径时运行：

```bash
python scripts/verify_release_candidate.py --require-artifacts --run-dmg-screen-smoke
```

`--run-dmg-screen-smoke` 会启动 DMG 内 `.app`、等待 packaged Bridge `/status`，再请求 `/screen/current`。通过时 RC report 只记录截图 `width`、`height`、`format`、`captured_at` 等元数据，不归档 `image_base64`；同一轮 gate 会把 `packaged_bridge_isolation` 和 `screen_recording_permission` 自动标为 `passed`。

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
`--source-only` 不能和 artifact path、`--require-artifacts`、`--check-dmg-mount`、`--run-dmg-app-smoke`、`--run-dmg-screen-smoke`、`--run-provider-smoke` 或 `--run-ui-smoke` 混用；DMG mount、DMG app startup smoke、DMG screen recording smoke、真实 provider smoke 和 Electron UI smoke 只属于完整本地 RC 复验。

macOS release workflow 会在生成 release metadata 后、上传 DMG 前运行 `python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --report-json release/rc-verification.json`，确保 CI 与本地 RC 验收入口一致，并把 `release/rc-verification.json` 作为可归档验收报告随 release artifacts 上传。workflow 也会生成并上传 `release/manual-rc-checks.template.json`，用于发布签核人从零填写 Gatekeeper、屏幕录制、原生图片上传、packaged UI 抽样以及任何未被自动 gate 证明的 packaged bridge / 真实 provider evidence；同一轮 RC report 生成后还会输出 `release/manual-rc-checks.draft.json`，该草稿已合并 `automated_rc_gate` evidence，可直接补人工 evidence 后交给 `--manual-checks-json` 做最终签核；随后还会输出 `release/manual-rc-checks.md`，作为可读人工签核 checklist。打包前的 Electron UI smoke 由 `python scripts/run_electron_ui_smokes.py --report-json release/electron-ui-smoke.json` 动态发现并运行所有 `scripts/smoke_*_ui.mjs`，其结构化结果会作为 `release/electron-ui-smoke.json` 随 artifacts 上传。`--check-dmg-mount` 会只读挂载发现到的 DMG，并对 DMG 内真实 `.app` 的 `Contents/Resources` 再执行 packaged app scan；如果 `OHA_YACHIYO_SMOKE_BASE_URL`、`OHA_YACHIYO_SMOKE_MODEL` 和 `OHA_YACHIYO_SMOKE_API_KEY` 都已配置，workflow 会向同一个 RC gate 传入 `--run-provider-smoke`，让 report 的 `provider_smoke` 字段记录真实 provider 文本流与 tool-call follow-up 结果。带 `--run-dmg-app-smoke` 的 packaged app 启动检查、带 `--run-dmg-screen-smoke` 的屏幕录制权限检查和带 `--run-ui-smoke` 的完整 Electron UI smoke 仍保留给本地 RC 复验，因为它们会启动本地 Electron 应用或 BrowserWindow。

脚本仍会列出首次启动 / Gatekeeper、屏幕录制权限、Chat 原生图片上传、packaged UI 抽样、packaged bridge 和真实 provider 的最终签核项，并在 `release/rc-verification.json` 中写入结构化 `manual_release_candidate_check_statuses` 与 `manual_release_candidate_check_summary`。这些条目默认是 `manual_required`，并带有稳定 id、证据说明和下一步动作；当前固定 id 包括 `gatekeeper_first_launch`、`packaged_bridge_isolation`、`screen_recording_permission`、`chat_native_file_upload`、`packaged_ui_sampling` 和 `real_provider_smoke`。summary 会给出 `remaining_count`、`remaining_check_ids`、`remaining_next_actions`、`failed_check_ids` 和 `automated_evidence_check_ids`，用于快速判断最终签核还差多少项以及下一步该跑哪个 gate 或做哪项人工复验。如果同一次 RC gate 中 `--run-dmg-app-smoke` 通过，`packaged_bridge_isolation` 会自动标为 `passed` 并写入 `evidence_source=automated_rc_gate`；如果 `--run-dmg-screen-smoke` 通过，`packaged_bridge_isolation` 和 `screen_recording_permission` 会自动标为 `passed`；如果 `--run-provider-smoke` 通过，`real_provider_smoke` 也会自动标为 `passed`。自动 evidence 只填充仍为 `manual_required` 的项，不会覆盖签核人已经写入的 `passed`、`failed` 或 `not_applicable`。可先生成人工验收模板：

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

已有人工 evidence 时可传入项目内 JSON：

```bash
python scripts/verify_release_candidate.py --require-artifacts --manual-checks-json tmp/final-rc-signoff.json --require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json
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

`--write-manual-checks-template` 输出的每项都带 `description`、`required_before`、`evidence_prompt`、空 `evidence` 和 `notes`，适合从零开始填写。`--write-manual-checks-draft` 会读取 `--manual-checks-json` 指向的上一轮 RC report 或 evidence JSON，输出同样可编辑、可再喂回 `--manual-checks-json` 的 `{ "checks": [...] }` 草稿；草稿会保留 `automated_rc_gate` evidence，并把仍是 `manual_required` 的项目 `evidence` 留空。`--write-manual-checks-markdown` 会读取同一份 evidence JSON 并输出可读 checklist，列出剩余人工项、下一步动作、需要记录的 evidence，以及已通过 / not_applicable 项的 evidence source；签核人也可以勾选并填写这份 Markdown，再用 `--manual-checks-markdown` 作为最终 gate 输入。源 RC report 如果包含已通过的 `electron_ui_smoke`，草稿会把 `--run-ui-smoke` 通过的脚本列表预填到 `packaged_ui_sampling` 的 `Notes:`，并把 `smoke_chat_image_attachment_ui.mjs` 作为 `chat_native_file_upload` 的辅助 evidence 备注；这两项仍保持 `manual_required`，不会因为辅助 smoke 自动通过。Markdown checklist 的填写规则是：保留 ``- [ ] `check_id` `` 表示该项仍是 `manual_required`；改成 ``- [x] `check_id` `` 表示通过，不写显式 `status` 会按 `passed` 解析；需要显式跳过或记录失败时，用 ``- [x] `check_id` - not_applicable`` 或 ``- [x] `check_id` - failed``。所有 `passed`、`failed` 和 `not_applicable` 项都必须填写非空 `Evidence:`，多行 evidence 可放在缩进续行中。`--mark-provider-smoke-not-applicable-if-missing` 只在写 draft 或 Markdown checklist 时生效，且只在 `real_provider_smoke` 仍为 `manual_required` 且当前环境缺少任一 `OHA_YACHIYO_SMOKE_*` 变量时写入 `not_applicable`。`--manual-checks-json` 支持顶层 list、`{ "checks": [...] }`，也支持直接传入上一轮 RC report 并读取其中的 `manual_release_candidate_check_statuses`，因此自动 evidence 不需要手工复制到另一个模板文件；`--manual-checks-markdown` 支持脚本生成的 Markdown checklist 格式。每项至少包含 `id`、`status` 和必要时的 `evidence`。`status` 只能是 `manual_required`、`passed`、`failed` 或 `not_applicable`；`passed`、`failed` 和 `not_applicable` 必须带 evidence。未知 id、重复 id、非法 status、缺 evidence 或显式 `failed` 都会让 RC gate 失败并写入 `manual_release_candidate_check_findings`。最终发布签核时加 `--require-manual-checks-complete`，任何在自动 evidence 和人工 evidence 合并后仍为 `manual_required` 的检查都会让 RC gate 失败。

后续如果要面向普通用户无 Gatekeeper 警告地分发，需要再补 Apple Developer ID 签名与 notarization；当前链路先保证可重复构建和可安装 DMG。
