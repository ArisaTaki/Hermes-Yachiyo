"""Structured Browser/CDP tools for the Agent runtime."""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def open_url(url: str) -> dict[str, Any]:
    clean_url = _clean_url(url)
    cdp_url = _configured_browser_cdp_url()
    if cdp_url:
        try:
            page = _cdp_new_page(cdp_url, clean_url)
            return {
                "ok": True,
                "action": "browser.open_url",
                "summary": f"Opened browser page: {clean_url}",
                "data": _page_summary(page, fallback_url=clean_url),
                "permission_error": False,
                "fallback_used": False,
            }
        except Exception as exc:
            fallback = _open_url_fallback(clean_url)
            return {
                **fallback,
                "fallback_reason": str(exc),
            }
    return _open_url_fallback(clean_url)


def current_page() -> dict[str, Any]:
    try:
        page = _current_page()
    except Exception as exc:
        return _cdp_unavailable("browser.current_page", exc)
    data = _page_summary(page)
    return {
        "ok": True,
        "action": "browser.current_page",
        "summary": f"Current browser page: {data.get('title') or data.get('url') or 'Untitled'}",
        "data": data,
        "permission_error": False,
        "fallback_used": False,
    }


def click(selector: str) -> dict[str, Any]:
    clean_selector = _clean_required(selector, "selector")
    expression = f"""
    (() => {{
      const selector = {json.dumps(clean_selector)};
      const el = document.querySelector(selector);
      if (!el) return {{ ok: false, error: 'selector_not_found', selector }};
      el.scrollIntoView({{ block: 'center', inline: 'center' }});
      el.click();
      const label = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
      return {{ ok: true, selector, tag: el.tagName, label: label.slice(0, 200) }};
    }})()
    """
    try:
        value = _evaluate_current_page(expression)
    except Exception as exc:
        return _cdp_unavailable("browser.click", exc)
    if not value.get("ok"):
        return {
            "ok": False,
            "action": "browser.click",
            "summary": f"Browser selector not found: {clean_selector}",
            "data": value,
            "permission_error": False,
            "fallback_used": False,
        }
    return {
        "ok": True,
        "action": "browser.click",
        "summary": f"Clicked browser selector: {clean_selector}",
        "data": value,
        "permission_error": False,
        "fallback_used": False,
    }


def type_text(selector: str, text: str) -> dict[str, Any]:
    clean_selector = _clean_required(selector, "selector")
    clean_text = _clean_required(text, "text")
    expression = f"""
    (() => {{
      const selector = {json.dumps(clean_selector)};
      const text = {json.dumps(clean_text)};
      const el = document.querySelector(selector);
      if (!el) return {{ ok: false, error: 'selector_not_found', selector }};
      el.scrollIntoView({{ block: 'center', inline: 'center' }});
      el.focus();
      if ('value' in el) {{
        el.value = text;
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      }} else {{
        el.textContent = text;
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      }}
      return {{ ok: true, selector, tag: el.tagName, length: text.length }};
    }})()
    """
    try:
        value = _evaluate_current_page(expression)
    except Exception as exc:
        return _cdp_unavailable("browser.type_text", exc)
    if not value.get("ok"):
        return {
            "ok": False,
            "action": "browser.type_text",
            "summary": f"Browser selector not found: {clean_selector}",
            "data": value,
            "permission_error": False,
            "fallback_used": False,
        }
    return {
        "ok": True,
        "action": "browser.type_text",
        "summary": f"Typed text into browser selector: {clean_selector}",
        "data": value,
        "permission_error": False,
        "fallback_used": False,
    }


def extract_text(selector: str = "") -> dict[str, Any]:
    clean_selector = str(selector or "").strip()
    if clean_selector:
        selector_json = json.dumps(clean_selector)
        expression = f"""
        (() => {{
          const selector = {selector_json};
          const el = document.querySelector(selector);
          if (!el) return {{ ok: false, error: 'selector_not_found', selector }};
          return {{ ok: true, text: (el.innerText || el.textContent || '').trim() }};
        }})()
        """
    else:
        expression = """
        (() => ({ ok: true, text: (document.body ? document.body.innerText : '').trim() }))()
        """
    try:
        value = _evaluate_current_page(expression)
    except Exception as exc:
        return _cdp_unavailable("browser.extract_text", exc)
    if not value.get("ok"):
        return {
            "ok": False,
            "action": "browser.extract_text",
            "summary": "Browser text selector not found",
            "data": value,
            "permission_error": False,
            "fallback_used": False,
        }
    text_value = str(value.get("text") or "")
    truncated = len(text_value) > 20000
    if truncated:
        text_value = text_value[:20000]
    return {
        "ok": True,
        "action": "browser.extract_text",
        "summary": f"Extracted {len(text_value)} characters from browser page",
        "data": {"selector": clean_selector, "text": text_value, "truncated": truncated},
        "permission_error": False,
        "fallback_used": False,
    }


def screenshot(target_path: Path) -> dict[str, Any]:
    try:
        websocket_url = _page_websocket_url()
        result = _cdp_command(
            websocket_url,
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
    except Exception as exc:
        return _cdp_unavailable("browser.screenshot", exc)
    data = str(result.get("data") or "")
    if not data:
        return {
            "ok": False,
            "action": "browser.screenshot",
            "summary": "Browser screenshot did not return image data",
            "data": {},
            "permission_error": False,
            "fallback_used": False,
        }
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = base64.b64decode(data)
    target.write_bytes(image_bytes)
    return {
        "ok": True,
        "action": "browser.screenshot",
        "summary": "Captured current browser page",
        "data": {
            "path": str(target),
            "mime_type": "image/png",
            "format": "png",
            "size": len(image_bytes),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _evaluate_current_page(expression: str) -> dict[str, Any]:
    websocket_url = _page_websocket_url()
    result = _cdp_command(
        websocket_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    value = result.get("result", {}).get("value")
    return value if isinstance(value, dict) else {"ok": True, "value": value}


def _current_page() -> dict[str, Any]:
    cdp_url = _configured_browser_cdp_url()
    if not cdp_url:
        raise RuntimeError("browser.cdp_url is not configured")
    pages = _cdp_list_pages(cdp_url)
    page = _select_page(pages)
    if page is None:
        raise RuntimeError("No debuggable browser page found")
    return page


def _page_websocket_url() -> str:
    page = _current_page()
    websocket_url = str(page.get("webSocketDebuggerUrl") or "").strip()
    if not websocket_url:
        raise RuntimeError("Current browser page has no websocket debugger URL")
    return websocket_url


def _cdp_new_page(cdp_url: str, url: str) -> dict[str, Any]:
    endpoint = _cdp_endpoint(cdp_url, f"/json/new?{quote(url, safe='')}")
    try:
        return _http_json(endpoint, method="PUT")
    except Exception:
        return _http_json(endpoint, method="GET")


def _cdp_list_pages(cdp_url: str) -> list[dict[str, Any]]:
    payload = _http_json(_cdp_endpoint(cdp_url, "/json/list"))
    if not isinstance(payload, list):
        raise RuntimeError("CDP /json/list did not return a list")
    return [item for item in payload if isinstance(item, dict)]


def _http_json(url: str, *, method: str = "GET") -> Any:
    request = Request(url, method=method)
    with urlopen(request, timeout=2.0) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw or "{}")


def _cdp_command(
    websocket_url: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _CdpWebSocket(websocket_url) as websocket:
        websocket.send_json({"id": 1, "method": method, "params": params or {}})
        while True:
            message = websocket.recv_json()
            if message.get("id") != 1:
                continue
            if "error" in message:
                raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
            result = message.get("result")
            return result if isinstance(result, dict) else {}


def _configured_browser_cdp_url() -> str:
    for env_name in ("YACHIYO_BROWSER_CDP_URL", "BROWSER_CDP_URL"):
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    try:
        from apps.shell import config as shell_config

        path = Path(shell_config._CONFIG_DIR) / "native_tool_config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    config = data.get("config")
    if not isinstance(config, dict):
        return ""
    return str(config.get("browser.cdp_url") or "").strip()


def _open_url_fallback(url: str) -> dict[str, Any]:
    if sys.platform != "darwin":
        return _cdp_unavailable("browser.open_url")
    try:
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return _cdp_unavailable("browser.open_url", exc)
    if result.returncode != 0:
        return _cdp_unavailable("browser.open_url", result.stderr or result.stdout)
    return {
        "ok": True,
        "action": "browser.open_url",
        "summary": f"Opened URL in the system browser: {url}",
        "data": {"url": url},
        "permission_error": False,
        "fallback_used": True,
        "fallback": "system_browser",
    }


def _cdp_unavailable(action: str, detail: Any = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "action": action,
        "summary": "Chrome CDP is unavailable",
        "error": "chrome_cdp_unavailable",
        "permission_error": True,
        "fallback_used": False,
        "missing_permissions": ["chrome_cdp"],
        "permission_targets": ["chrome_cdp"],
    }
    if detail:
        payload["detail"] = str(detail)
    return payload


def _select_page(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for page in pages:
        is_page = str(page.get("type") or "") == "page"
        is_devtools = str(page.get("url") or "").startswith("devtools://")
        if is_page and not is_devtools:
            return page
    return pages[0] if pages else None


def _page_summary(page: dict[str, Any], *, fallback_url: str = "") -> dict[str, Any]:
    return {
        "target_id": str(page.get("id") or ""),
        "title": str(page.get("title") or ""),
        "url": str(page.get("url") or fallback_url),
        "type": str(page.get("type") or ""),
    }


def _cdp_endpoint(cdp_url: str, path: str) -> str:
    base = str(cdp_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("browser.cdp_url is not configured")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _clean_url(url: str) -> str:
    clean = str(url or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("browser.open_url only accepts absolute http(s) URLs")
    return clean


def _clean_required(value: str, field_name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} is required")
    return clean


class _CdpWebSocket:
    def __init__(self, websocket_url: str, *, timeout: float = 5.0) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self._socket: socket.socket | ssl.SSLSocket | None = None

    def __enter__(self) -> "_CdpWebSocket":
        self._connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def _connect(self) -> None:
        parsed = urlparse(self.websocket_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise RuntimeError("Invalid CDP websocket URL")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        sock: socket.socket | ssl.SSLSocket = socket.create_connection(
            (parsed.hostname, port),
            timeout=self.timeout,
        )
        if parsed.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        sock.settimeout(self.timeout)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(4096)
            if not chunk:
                break
            header += chunk
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("CDP websocket upgrade failed")
        self._socket = sock

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_text(json.dumps(payload, ensure_ascii=False))

    def recv_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 8:
                raise RuntimeError("CDP websocket closed")

    def _send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._require_socket().sendall(bytes(header) + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        sock = self._require_socket()
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self._recv_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._recv_exact(8), "big")
        mask = self._recv_exact(4) if second & 0x80 else b""
        payload = self._recv_exact(length) if length else b""
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, size: int) -> bytes:
        data = b""
        sock = self._require_socket()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("CDP websocket disconnected")
            data += chunk
        return data

    def _require_socket(self) -> socket.socket | ssl.SSLSocket:
        if self._socket is None:
            raise RuntimeError("CDP websocket is not connected")
        return self._socket
