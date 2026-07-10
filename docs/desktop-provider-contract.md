# Desktop Provider Contract

Oha-Yachiyo 的桌面执行层通过一个本地 HTTP provider 接入真实隔离桌面或虚拟桌面后端。这个 contract 面向 Hermes/Hanako-style provider：Runtime 负责规划、审批、复盘；provider 负责发现应用、操作 UI、输入、验证，并且不能抢占用户当前前台鼠标键盘。

## 启动方式

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
  "capabilities": ["virtual_desktop", "keyboard_mouse_capture", "desktop_control"],
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
