"""TLS helper tests."""

from __future__ import annotations

import os
import ssl
from urllib.request import Request

from apps.core.tls import install_bundled_ca_env, urlopen_with_bundled_ca


def test_install_bundled_ca_env_sets_ssl_paths(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    ca_file = install_bundled_ca_env()

    assert ca_file
    assert ca_file == os.environ["SSL_CERT_FILE"]
    assert ca_file == os.environ["REQUESTS_CA_BUNDLE"]


def test_urlopen_with_bundled_ca_passes_context_for_https(monkeypatch):
    calls = {}

    def fake_urlopen(request, **kwargs):
        calls["request"] = request
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    request = Request("https://api.example.test/v1/models", method="GET")

    result = urlopen_with_bundled_ca(request, timeout=7)

    assert result is not None
    assert calls["request"] is request
    assert calls["kwargs"]["timeout"] == 7
    assert isinstance(calls["kwargs"]["context"], ssl.SSLContext)


def test_urlopen_with_bundled_ca_leaves_http_without_context(monkeypatch):
    calls = {}

    def fake_urlopen(request, **kwargs):
        calls["request"] = request
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("apps.core.tls.urlrequest.urlopen", fake_urlopen)
    request = Request("http://127.0.0.1:8420/health", method="GET")

    urlopen_with_bundled_ca(request, timeout=3)

    assert calls["request"] is request
    assert calls["kwargs"] == {"timeout": 3}
