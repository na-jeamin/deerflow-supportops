"""Offline HTTP checks for owner-bound human decisions on saved drafts."""

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from deerflow_extension_api.auth import (
    EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY,
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "extensions" / "supportops")
)

from supportops_extension.action_store import save_pending_action  # noqa: E402


@pytest.fixture
def approval_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from supportops_extension import approval_routes

    async def authorize(request, namespace, scope):
        assert namespace == "supportops.order"
        return request.headers.get("x-test-access") != "denied"

    app = FastAPI()
    setattr(app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY, authorize)
    setattr(
        app.state,
        EXTENSION_PRINCIPAL_RESOLVER_KEY,
        lambda request: ExtensionPrincipal(
            request.headers.get("x-test-user", "alice"),
            is_internal=request.headers.get("x-test-internal") == "true",
        ),
    )

    @app.middleware("http")
    async def session(request, call_next):
        request.state.auth_source = request.headers.get("x-test-source", "session")
        return await call_next(request)

    app.include_router(approval_routes.build_router())
    with TestClient(app) as client:
        yield client


def draft():
    return save_pending_action("ORD-1001", "物流一直没动", "alice", "thread-1")


def decision_payload(action, decision="approve"):
    return {
        "order_id": action["order_id"],
        "reason": action["reason"],
        "decision": decision,
    }


@pytest.mark.parametrize(
    ("decision", "status"), [("approve", "approved"), ("reject", "rejected")]
)
def test_human_decision_updates_existing_draft(
    approval_client, tmp_path, decision, status
):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    assert approval_client.get(url).json()["reason"] == "物流一直没动"
    response = approval_client.post(
        url + "/decision", json=decision_payload(action, decision)
    )
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action, decision)
        ).json()["status"]
        == status
    )
    with closing(sqlite3.connect(tmp_path / "supportops" / "actions.sqlite3")) as db:
        assert db.execute(
            "SELECT status FROM actions WHERE action_id=?", (action["action_id"],)
        ).fetchone() == (status,)


def test_other_user_and_non_session_cannot_decide(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    assert approval_client.get(url, headers={"x-test-user": "bob"}).status_code == 404
    assert (
        approval_client.post(
            url + "/decision",
            json=decision_payload(action),
            headers={"x-test-user": "bob"},
        ).status_code
        == 404
    )
    assert (
        approval_client.post(
            url + "/decision",
            json=decision_payload(action),
            headers={"x-test-source": "token"},
        ).status_code
        == 403
    )
    assert approval_client.get(url).json()["status"] == "pending_approval"


@pytest.mark.parametrize(
    "headers",
    [
        {"x-test-user": "default"},
        {"x-test-access": "denied"},
        {"x-test-internal": "true"},
    ],
)
def test_host_identity_and_permissions_are_required(approval_client, headers):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    assert approval_client.get(url, headers=headers).status_code == 403
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action), headers=headers
        ).status_code
        == 403
    )


def test_router_mounts_from_native_extension_with_documented_body(monkeypatch):
    from deerflow.extensions.gateway import include_contributed_routers
    from deerflow.extensions.loader import ExtensionSpec, load_extensions

    loaded, diagnostics = load_extensions(
        [ExtensionSpec(use="supportops_extension:install", config={"enabled": True})]
    )
    assert not diagnostics
    app = FastAPI()
    assert not include_contributed_routers(app, loaded)
    operation = app.openapi()["paths"]["/api/supportops/actions/{action_id}/decision"][
        "post"
    ]
    assert "application/json" in operation["requestBody"]["content"]


def test_changed_content_and_conflicting_decision_are_rejected(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    payload = decision_payload(action)
    payload["reason"] = "换一个原因"
    assert approval_client.post(url + "/decision", json=payload).status_code == 409
    assert approval_client.get(url).json()["status"] == "pending_approval"
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action, "reject")
        ).status_code
        == 200
    )
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action)
        ).status_code
        == 409
    )


def test_missing_draft_and_unknown_fields(approval_client):
    assert approval_client.get("/api/supportops/actions/missing").status_code == 404
    action = draft()
    payload = {**decision_payload(action), "owner_user_id": "bob"}
    assert (
        approval_client.post(
            f"/api/supportops/actions/{action['action_id']}/decision", json=payload
        ).status_code
        == 422
    )


def test_competing_decisions_only_commit_one(tmp_path, monkeypatch):
    from supportops_extension.action_store import decide_action, get_action

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    action = draft()

    def submit(decision):
        try:
            return decide_action(
                action["action_id"],
                "alice",
                action["order_id"],
                action["reason"],
                decision,
            )["status"]
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["approve", "reject"]))
    assert results.count("conflict") == 1
    assert get_action(action["action_id"], "alice")["status"] in results
