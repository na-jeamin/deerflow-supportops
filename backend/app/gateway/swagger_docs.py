"""Swagger UI integration with the Gateway's existing CSRF protection."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse

_INTERCEPTOR_PLACEHOLDER = "__DEERFLOW_SWAGGER_CSRF_INTERCEPTOR__"

# Swagger needs an actual JavaScript function, rather than a JSON string.
# Read the cookie on each request because login can rotate it in the same page.
_CSRF_REQUEST_INTERCEPTOR = """function(request) {
    const method = (request.method || "GET").toUpperCase();
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(method)) return request;

    let target;
    try {
        target = new URL(request.url, window.location.href);
    } catch (_) {
        return request;
    }
    if (target.origin !== window.location.origin) return request;

    const cookie = document.cookie.split(";")
        .map(item => item.trim())
        .find(item => item.startsWith("csrf_token="));
    if (!cookie) return request;

    let token;
    try {
        token = decodeURIComponent(cookie.slice("csrf_token=".length));
    } catch (_) {
        return request;
    }
    if (!token) return request;

    const headers = request.headers || {};
    for (const name of Object.keys(headers)) {
        if (name.toLowerCase() === "x-csrf-token") delete headers[name];
    }
    headers["X-CSRF-Token"] = token;
    request.headers = headers;
    request.credentials = "same-origin";
    return request;
}"""


def install_swagger_docs(app: FastAPI, *, docs_url: str = "/docs") -> None:
    """Register custom docs after disabling FastAPI's default Swagger route."""
    if app.openapi_url is None:
        return

    @app.get(docs_url, include_in_schema=False, response_class=HTMLResponse)
    async def swagger_ui_html(request: Request) -> HTMLResponse:
        root_path = request.scope.get("root_path", "").rstrip("/")
        oauth_redirect = app.swagger_ui_oauth2_redirect_url
        parameters = dict(app.swagger_ui_parameters or {})
        parameters["requestInterceptor"] = _INTERCEPTOR_PLACEHOLDER
        response = get_swagger_ui_html(
            openapi_url=f"{root_path}{app.openapi_url}",
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=f"{root_path}{oauth_redirect}" if oauth_redirect else None,
            init_oauth=app.swagger_ui_init_oauth,
            swagger_ui_parameters=parameters,
        )
        placeholder = f'"requestInterceptor": {json.dumps(_INTERCEPTOR_PLACEHOLDER)}'
        html = bytes(response.body).decode("utf-8")
        if placeholder not in html:
            raise RuntimeError("Swagger UI template no longer exposes the request interceptor option")
        return HTMLResponse(html.replace(placeholder, f'"requestInterceptor": {_CSRF_REQUEST_INTERCEPTOR}', 1))

    if app.swagger_ui_oauth2_redirect_url:

        @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False, response_class=HTMLResponse)
        async def swagger_ui_redirect() -> HTMLResponse:
            return get_swagger_ui_oauth2_redirect_html()
