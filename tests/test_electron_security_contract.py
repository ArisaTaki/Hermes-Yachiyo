"""Static release guards for the Electron renderer security boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "apps" / "frontend" / "index.html"
ATTACHMENTS_TS = ROOT / "apps" / "frontend" / "src" / "features" / "yachiyo-chat" / "attachments.ts"


def test_renderer_declares_a_content_security_policy_without_unsafe_eval() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")

    assert 'http-equiv="Content-Security-Policy"' in source
    assert "default-src 'self'" in source
    assert "object-src 'none'" in source
    assert "script-src 'self'" in source
    assert "unsafe-eval" not in source


def test_renderer_csp_limits_network_connections_to_local_runtime_origins() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    policy = source.split('http-equiv="Content-Security-Policy"', 1)[1].split(
        "/>\n",
        1,
    )[0]

    assert "connect-src 'self'" in policy
    assert "http://127.0.0.1:*" in policy
    assert "ws://127.0.0.1:*" in policy
    assert "connect-src 'self' https:" not in policy


def test_inline_image_data_urls_are_decoded_locally_without_relaxing_connect_src() -> None:
    source = ATTACHMENTS_TS.read_text(encoding="utf-8")
    policy = INDEX_HTML.read_text(encoding="utf-8").split(
        'http-equiv="Content-Security-Policy"',
        1,
    )[1].split("/>\n", 1)[0]
    connect_policy = policy.split("connect-src", 1)[1].split(";", 1)[0]

    assert "function fileFromImageDataUrl" in source
    assert "atob(payload)" in source
    assert "fetch(dataUrl)" not in source
    assert "data:" not in connect_policy
