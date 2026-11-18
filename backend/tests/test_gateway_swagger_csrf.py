"""Offline coverage for the Swagger UI's same-origin CSRF integration."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.swagger_docs import _CSRF_REQUEST_INTERCEPTOR, install_swagger_docs

_NODE = shutil.which("node")
_ORIGIN = "https://deerflow.example"


@pytest.fixture(autouse=True)
def _isolated_configuration(monkeypatch, tmp_path):
    from deerflow.config.app_config import reset_app_config

    config = tmp_path / "config.yaml"
    config.write_text("models: []\nplugins: []\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")
    extensions = tmp_path / "extensions_config.json"
    extensions.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    reset_app_config()
    yield
    reset_app_config()


def _intercept(request: dict, cookie: str, *, next_cookie: str | None = None) -> dict:
    if _NODE is None:
        pytest.skip("Node.js is optional; required to execute browser JavaScript tests")
    program = """
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const scope = {
  URL,
  window: {location: {origin: input.origin, href: input.origin + '/docs'}},
  document: {cookie: input.cookie}
};
const intercept = vm.runInNewContext('(' + input.source + ')', scope);
if (input.next_cookie !== null) {
  intercept({url: '/api/threads', method: 'POST', headers: {}});
  scope.document.cookie = input.next_cookie;
}
process.stdout.write(JSON.stringify(intercept(input.request)));
"""
    result = subprocess.run(
        [_NODE, "-e", program],
        input=json.dumps({"source": _CSRF_REQUEST_INTERCEPTOR, "origin": _ORIGIN, "request": request, "cookie": cookie, "next_cookie": next_cookie}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def _make_app() -> FastAPI:
    app = FastAPI(docs_url=None)
    app.add_middleware(CSRFMiddleware)
    install_swagger_docs(app)

    @app.post("/api/v1/auth/login/local")
    async def login():
        return {"ok": True}

    @app.post("/mutation")
    async def mutate():
        return {"ok": True}

    return app


def test_gateway_serves_csrf_aware_docs(monkeypatch):
    from app.gateway import config
    from app.gateway.app import create_app

    monkeypatch.setenv("GATEWAY_ENABLE_DOCS", "true")
    monkeypatch.setattr(config, "_gateway_config", None)
    response = TestClient(create_app()).get("/docs")
    assert response.status_code == 200
    assert f'"requestInterceptor": {_CSRF_REQUEST_INTERCEPTOR}' in response.text
    assert '"deepLinking": true' in response.text


def test_disabled_docs_also_hide_custom_swagger_and_oauth_redirect(monkeypatch):
    from app.gateway import config
    from app.gateway.app import create_app

    monkeypatch.setenv("GATEWAY_ENABLE_DOCS", "false")
    monkeypatch.setattr(config, "_gateway_config", None)
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 404
    assert client.get("/docs/oauth2-redirect").status_code == 404


def test_swagger_preserves_reverse_proxy_root_path_and_oauth_redirect():
    client = TestClient(_make_app(), root_path="/prefix")
    response = client.get("/prefix/docs")
    assert response.status_code == 200
    assert "url: '/prefix/openapi.json'" in response.text
    assert "window.location.origin + '/prefix/docs/oauth2-redirect'" in response.text
    assert client.get("/prefix/docs/oauth2-redirect").status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
def test_mutating_requests_receive_current_csrf_cookie(method):
    result = _intercept({"url": "/api/threads", "method": method, "headers": {"Accept": "application/json", "x-csrf-token": "stale"}}, "other=value; csrf_token=fresh%2Btoken")
    assert result["headers"] == {"Accept": "application/json", "X-CSRF-Token": "fresh+token"}
    assert result["credentials"] == "same-origin"


@pytest.mark.parametrize("url", ["https://other.example/api/threads", "//other.example/api/threads", "http://deerflow.example/api/threads"])
def test_interceptor_never_adds_cookie_to_cross_origin_requests(url):
    request = {"url": url, "method": "POST", "headers": {}}
    assert _intercept(request, "csrf_token=private-test-value") == request


@pytest.mark.parametrize("cookie", ["", "other=present", "csrf_token=%broken"])
def test_missing_or_malformed_cookie_does_not_invent_a_token(cookie):
    request = {"url": "/api/threads", "method": "POST", "headers": {}}
    assert _intercept(request, cookie) == request


def test_read_only_request_does_not_gain_csrf_header():
    request = {"url": "/openapi.json", "method": "GET", "headers": {}}
    assert _intercept(request, "csrf_token=test") == request


def test_interceptor_reads_new_cookie_after_login_in_same_page():
    result = _intercept({"url": "/api/threads", "method": "POST"}, "csrf_token=old", next_cookie="csrf_token=new")
    assert result["headers"]["X-CSRF-Token"] == "new"


def test_login_then_intercepted_button_request_passes_real_csrf_check():
    client = TestClient(_make_app(), base_url=_ORIGIN)
    assert client.post("/api/v1/auth/login/local").status_code == 200
    cookie = client.cookies.get("csrf_token")
    assert cookie
    assert client.post("/mutation").status_code == 403
    request = _intercept({"url": "/mutation", "method": "POST"}, f"csrf_token={cookie}")
    assert client.post("/mutation", headers=request["headers"]).status_code == 200
    assert client.post("/mutation", headers={"X-CSRF-Token": "wrong"}).status_code == 403
