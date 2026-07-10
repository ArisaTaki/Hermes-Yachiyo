# Desktop Provider Contract

Oha-Yachiyo 的桌面执行层通过一个本地 HTTP provider 接入真实隔离桌面或虚拟桌面后端。这个 contract 面向 Hermes/Hanako-style provider：Runtime 负责规划、审批、复盘；provider 负责发现应用、操作 UI、输入、验证，并且不能抢占用户当前前台鼠标键盘。

## 启动方式

### 内置 macOS VM guest-agent

仓库提供 `scripts/run_virtual_desktop_guest_provider.py`。它必须运行在单独的
macOS VM guest 内；它复用通用应用发现、Accessibility UI、点击、输入、快捷键和
验证工具，不包含 Apple Music、Finder 或其他应用白名单。宿主只通过 HTTP contract
发送工具请求，因此 guest 内的鼠标键盘不会抢占用户当前桌面。

在 VM guest 每次启动后生成与当前 boot session 绑定的 marker，再启动 Provider：

```bash
export OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID="oha-vm-session-1"
export OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN="<random-bearer-token>"

python scripts/run_virtual_desktop_guest_provider.py \
  --session-id "$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID" \
  --write-guest-marker "$HOME/Library/Application Support/Oha-Yachiyo/virtual-desktop-guest.json"

# 用 VM 的 secret provisioning 写入同一 token；文件必须属于 guest 用户且权限为 0600。
# 默认路径：$HOME/Library/Application Support/Oha-Yachiyo/desktop-provider.token

python scripts/run_virtual_desktop_guest_provider.py \
  --host 0.0.0.0 \
  --port 29097 \
  --session-id "$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID" \
  --guest-marker "$HOME/Library/Application Support/Oha-Yachiyo/virtual-desktop-guest.json" \
  --token-file "$HOME/Library/Application Support/Oha-Yachiyo/desktop-provider.token"
```

然后用 VM 工具或 SSH 把 guest 的 `29097` 转发到宿主 loopback，并在宿主配置
Provider URL 和相同 token。不要把 guest endpoint 直接暴露到公网。内置 guest-agent
只有在以下 attestation 全部成立时才执行工具或声明 release-ready：Darwin guest、
当前 boot session 和 `hw.model` 匹配、硬件模型包含虚拟化标识、marker 属于当前用户
且权限为 `0600`、独立 session id 匹配、
backend 非 loopback、`desktop_session_isolated=true`、
`foreground_takeover_required=false`。真实 VM 镜像和端口转发仍由发行环境提供。

可在 guest 内输出对应 manifest：

```bash
python scripts/run_virtual_desktop_guest_provider.py \
  --session-id "$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID" \
  --manifest
```

宿主侧可以直接使用内置 SSH lifecycle bridge，不需要另写端口转发脚本。它启动
guest Provider、建立仅监听 loopback 的 tunnel、重写启动 endpoint，并在 Studio 停止
session 时一并终止 SSH/guest 进程。Host token 不会转发到 SSH 子进程；guest 只读取
上面的 `0600` token file。

```bash
export OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET="yachiyo@<vm-address>"
export OHA_YACHIYO_VIRTUAL_DESKTOP_REMOTE_REPO="/Users/yachiyo/Hermes-Yachiyo"

python scripts/run_ssh_virtual_desktop_provider.py \
  --ssh-target "$OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET" \
  --remote-repo "$OHA_YACHIYO_VIRTUAL_DESKTOP_REMOTE_REPO" \
  --session-id "$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID" \
  --manifest > tmp/oha-virtual-desktop-provider.manifest.json

export OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST="$PWD/tmp/oha-virtual-desktop-provider.manifest.json"
```

Manifest 的 `entrypoint` 会让现有 `IsolatedDesktopProviderSessionManager` 托管 SSH
bridge。SSH 必须使用已配置的 key/agent，并启用 host key verification；可通过重复的
`--ssh-option` 传入现有 OpenSSH 配置项。Bridge 保留本地 `SSH_AUTH_SOCK` 用于认证，
但强制 `ForwardAgent=no`，不会把本地 SSH agent 转发进 VM。`--remote-repo` 必须是
guest 内的绝对路径。

### 外部 Provider

如果 provider 已经运行，可以直接配置：

```bash
export OHA_YACHIYO_DESKTOP_PROVIDER_URL="http://127.0.0.1:29093"
export OHA_YACHIYO_DESKTOP_PROVIDER_ID="real-virtual-desktop"
export OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS="desktop.list_apps,app.open,desktop.inspect_app,media.music_app_open_and_play,media.music_app_control,desktop.read_ui,desktop.click_ui_element,desktop.safe_type_text,desktop.safe_shortcut,desktop.verify"
```

如果希望 Oha-Yachiyo 托管启动 provider，配置 start command。该进程必须在 stdout 第一行输出启动 JSON：

```bash
export OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND="python /path/to/provider.py --host 127.0.0.1 --port 0"
python scripts/smoke_oha_desktop_agent_release.py \
  --run-isolated-provider-smoke \
  --use-configured-virtual-desktop-provider \
  --report-json tmp/oha-desktop-agent-release-smoke.json
```

Oha-Yachiyo 会把本次需要的工具列表传给子进程：

```text
OHA_YACHIYO_DESKTOP_PROVIDER_REQUESTED_TOOLS
```

也可以用 manifest 交接，避免在 Oha-Yachiyo 里写死某个 provider 的启动命令或 app 规则：

```bash
export OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST="/path/to/provider-manifest.json"
python scripts/smoke_oha_desktop_agent_release.py \
  --run-isolated-provider-smoke \
  --provider-manifest /path/to/provider-manifest.json \
  --report-json tmp/oha-desktop-agent-release-smoke.json
```

manifest 可以只描述已经运行的 endpoint，也可以带 `entrypoint` 让 Oha-Yachiyo 托管启动：

```json
{
  "provider_id": "real-virtual-desktop",
  "provider_kind": "sandbox_desktop",
  "endpoint_urls": {
    "status": "http://127.0.0.1:29093/status",
    "execute": "http://127.0.0.1:29093/tools/execute"
  },
  "supported_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
  "desktop_session_kind": "virtual_desktop",
  "desktop_session_isolated": true,
  "foreground_takeover_required": false,
  "authentication": {
    "token_env": "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN"
  },
  "entrypoint": {
    "script": "provider.py",
    "args": ["--host", "127.0.0.1", "--port", "0"]
  }
}
```

`authentication.token_env` 指向宿主环境中的 Bearer token 变量。托管启动时
Oha-Yachiyo 会把解析出的 token 以 `OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN`
传给 provider 子进程，并在调用 Status/Execute endpoint 时发送
`Authorization: Bearer <token>`。不要把 token 明文写进 manifest；session、
Studio 和 diagnostics 的公共 `env` 投影不会返回 token。

`entrypoint.command` / `entrypoint.argv` 也可直接提供完整启动命令。`entrypoint.script` 的相对路径默认按 manifest 所在目录解析；如果是仓库内置脚本，也会回退到仓库根目录解析。

## 启动 JSON

启动进程 stdout 第一行必须是 JSON object：

```json
{
  "ok": true,
  "provider_id": "real-virtual-desktop",
  "provider_kind": "sandbox_desktop",
  "url": "http://127.0.0.1:29093",
  "status_url": "http://127.0.0.1:29093/status",
  "execute_url": "http://127.0.0.1:29093/tools/execute",
  "supported_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
  "keyboard_mouse_capture_supported": true,
  "desktop_session_kind": "virtual_desktop",
  "desktop_session_isolated": true,
  "foreground_takeover_required": false
}
```

`url` 或 `execute_url` 必须指向 loopback，除非显式设置 `OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE=true`。默认不允许远程 provider，避免把桌面控制请求发到未知网络端点。

## Status Endpoint

`GET /status` 必须返回：

```json
{
  "ok": true,
  "status": "healthy",
  "version": "provider-version",
  "supported_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
  "capabilities": ["virtual_desktop", "keyboard_mouse_capture", "desktop_control", "idempotent_tool_requests"],
  "desktop_session_kind": "virtual_desktop",
  "desktop_session_isolated": true,
  "foreground_takeover_required": false,
  "keyboard_mouse_capture_supported": true,
  "desktop_backend_kind": "virtual_desktop_backend",
  "desktop_backend_is_loopback": false,
  "desktop_backend_ready_for_public_release": true,
  "requires_real_virtual_desktop_backend": false
}
```

发布级 provider 必须满足 `apps.shell.yachiyo_agent.desktop_provider_contract` 中的 `oha-yachiyo.desktop-provider.v1`：

- provider configured, available, adapter ready。
- provider 已配置 Bearer token，`authentication_configured=true`。
- provider 声明并实现 `idempotent_tool_requests`。
- session 是 `virtual_desktop` 或 isolated desktop。
- `foreground_takeover_required=false`。
- backend 不是 `loopback_session_harness`。
- `desktop_backend_ready_for_public_release=true`。
- `requires_real_virtual_desktop_backend=false`。
- 支持 release smoke 所需的通用工具序列。

## Execute Endpoint

`POST /tools/execute` 会收到：

```json
{
  "request_id": "oha-desktop-<stable-id>",
  "tool": "desktop.list_apps",
  "input": {"query": "Apple Music", "limit": 20},
  "approved": true,
  "route": {},
  "tool_request": {},
  "provider": {
    "provider_kind": "sandbox_desktop",
    "provider_id": "real-virtual-desktop"
  }
}
```

当 Runtime tool request 已有 `request_id`、`tool_call_id`、replan action id，或
`plan_id + step_id` 时，Oha-Yachiyo 会生成稳定的 provider `request_id`，同时发送
同值的 `Idempotency-Key` header。Provider 应在自己的 desktop session 内按该 id
缓存已完成结果；相同 id 的重试不得再次执行点击、输入、快捷键或提交动作。若同一
id 收到不一致 payload，Provider 应返回冲突错误而不是执行第二次。

返回值可以是 tool result object，或 `{ "result": { ... } }`。发布 smoke 会检查每个 result：

```json
{
  "ok": true,
  "tool": "desktop.list_apps",
  "action": "desktop.list_apps",
  "desktop_execution_provider_routed": true,
  "sandbox_provider": {
    "desktop_session_isolated": true
  },
  "data": {}
}
```

每个 tool result 必须是 ok、routed，并证明结果来自 isolated/virtual desktop session。

## 发布验证

本地先跑 provider contract smoke：

```bash
python scripts/smoke_isolated_desktop_provider.py \
  --use-configured-provider \
  --report-json tmp/isolated-provider-contract-smoke.json
```

再跑产品级 release smoke：

```bash
python scripts/smoke_oha_desktop_agent_release.py \
  --run-isolated-provider-smoke \
  --use-configured-virtual-desktop-provider \
  --report-json tmp/oha-desktop-agent-release-smoke.json
```

如果 provider 仍是 loopback harness，报告会保留基础工具链证据，但 `provider_contract.ok=false`，并在 release summary 中显示 `loopback_desktop_backend`、`desktop_backend_not_release_ready`、`real_virtual_desktop_backend_required`。
