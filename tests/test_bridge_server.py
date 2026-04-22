"""Bridge Server 测试。"""

from apps.bridge.server import app


def test_bridge_app_enables_local_webview_cors():
    middleware = getattr(app, "user_middleware", [])
    cors_entry = next(
        (item for item in middleware if getattr(getattr(item, "cls", None), "__name__", "") == "CORSMiddleware"),
        None,
    )

    assert cors_entry is not None
    assert cors_entry.options["allow_origins"] == ["null"]
    assert cors_entry.options["allow_origin_regex"] == r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
    assert cors_entry.options["allow_methods"] == ["*"]
    assert cors_entry.options["allow_headers"] == ["*"]