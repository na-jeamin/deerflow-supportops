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

from supportops_extension.action_store import (  # noqa: E402
    decide_action,
    execute_action,
    get_action,
    save_pending_action,
)


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


def test_execute_endpoint_requires_owner_and_current_approval(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    payload = {"revision": 2}
    assert (
        approval_client.post(url + "/execute", json={"revision": 1}).status_code == 409
    )
    assert (
        approval_client.post(
            url + "/revision", json={"reason": "商品无法正常使用", "revision": 1}
        ).status_code
        == 200
    )
    assert (
        approval_client.post(
            url + "/decision",
            json={
                **decision_payload(action),
                "reason": "商品无法正常使用",
                "revision": 2,
            },
        ).status_code
        == 200
    )
    assert (
        approval_client.post(url + "/execute", json={"revision": 1}).status_code == 409
    )
    assert (
        approval_client.post(
            url + "/execute", json=payload, headers={"x-test-user": "bob"}
        ).status_code
        == 404
    )
    assert (
        approval_client.post(
            url + "/execute", json=payload, headers={"x-test-source": "api_key"}
        ).status_code
        == 403
    )

    result = approval_client.post(url + "/execute", json=payload)
    assert result.status_code == 200
    ticket = result.json()
    assert ticket["status"] == "succeeded"
    assert ticket["action_id"] == action["action_id"]
    assert ticket["reason"] == "商品无法正常使用"
    assert ticket["revision"] == 2
    assert approval_client.post(url + "/execute", json=payload).json() == ticket
    assert approval_client.get(url).json()["status"] == "succeeded"
    assert (
        approval_client.post(
            url + "/revision", json={"reason": "又改了原因", "revision": 2}
        ).status_code
        == 409
    )


def test_parallel_executions_persist_one_ticket_per_action(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    action_id = draft()["action_id"]
    next_action_id = draft()["action_id"]
    for approved_id in (action_id, next_action_id):
        decide_action(approved_id, "alice", "ORD-1001", "物流一直没动", "approve")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(execute_action, action_id, "alice", 1)
        second = executor.submit(execute_action, action_id, "alice", 1)
        ticket = first.result()
        assert second.result() == ticket
    assert (
        execute_action(next_action_id, "alice", 1)["ticket_id"] != ticket["ticket_id"]
    )
    with closing(sqlite3.connect(tmp_path / "supportops" / "actions.sqlite3")) as db:
        assert db.execute(
            "SELECT ticket_id FROM tickets WHERE action_id=?", (action_id,)
        ).fetchall() == [(ticket["ticket_id"],)]


def test_execution_rolls_back_ticket_if_status_update_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    first_id = draft()["action_id"]
    action_id = draft()["action_id"]
    for approved_id in (first_id, action_id):
        decide_action(approved_id, "alice", "ORD-1001", "物流一直没动", "approve")
    execute_action(first_id, "alice", 1)
    with (
        closing(sqlite3.connect(tmp_path / "supportops" / "actions.sqlite3")) as db,
        db,
    ):
        db.execute("""
            CREATE TRIGGER fail_status_update BEFORE UPDATE ON actions
            WHEN NEW.status='succeeded'
            BEGIN SELECT RAISE(ABORT, 'simulated update failure'); END
        """)
        with pytest.raises(sqlite3.IntegrityError, match="simulated update failure"):
            execute_action(action_id, "alice", 1)
        assert (
            db.execute(
                "SELECT ticket_id FROM tickets WHERE action_id=?", (action_id,)
            ).fetchone()
            is None
        )
        assert get_action(action_id, "alice")["status"] == "approved"
        db.execute("DROP TRIGGER fail_status_update")
    assert execute_action(action_id, "alice", 1)["action_id"] == action_id


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


def test_revision_clears_approval_and_requires_review_of_new_version(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action)
        ).status_code
        == 200
    )
    response = approval_client.post(
        url + "/revision", json={"reason": "商品损坏", "revision": 1}
    )
    assert response.status_code == 200
    revised = response.json()
    assert revised["reason"] == "商品损坏"
    assert revised["revision"] == 2
    assert revised["status"] == "pending_approval"
    assert approval_client.get(url).json() == revised
    # 第1版内容和第1版确认均失效，只有核对第2版后才能批准。
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action)
        ).status_code
        == 409
    )
    payload = decision_payload(revised)
    assert approval_client.post(url + "/decision", json=payload).status_code == 409
    payload["revision"] = 2
    assert (
        approval_client.post(url + "/decision", json=payload).json()["status"]
        == "approved"
    )


def test_old_confirmation_stays_stale_when_content_changes_back(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    approval_client.post(url + "/revision", json={"reason": "商品损坏", "revision": 1})
    response = approval_client.post(
        url + "/revision", json={"reason": action["reason"], "revision": 2}
    )
    assert response.json()["revision"] == 3
    assert (
        approval_client.post(
            url + "/decision", json=decision_payload(action)
        ).status_code
        == 409
    )
    assert approval_client.get(url).json()["status"] == "pending_approval"


def test_same_content_revision_is_noop_and_stale_revision_is_rejected(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    approval_client.post(url + "/decision", json=decision_payload(action))
    result = approval_client.post(
        url + "/revision", json={"reason": action["reason"], "revision": 1}
    )
    assert result.json()["status"] == "approved"
    assert result.json()["revision"] == 1
    assert (
        approval_client.post(
            url + "/revision", json={"reason": "商品损坏", "revision": 1}
        ).status_code
        == 200
    )
    assert (
        approval_client.post(
            url + "/revision", json={"reason": "其他原因", "revision": 1}
        ).status_code
        == 409
    )
    assert approval_client.get(url).json()["reason"] == "商品损坏"


def test_revision_checks_identity_missing_records_and_empty_content(approval_client):
    action = draft()
    url = f"/api/supportops/actions/{action['action_id']}"
    payload = {"reason": "商品损坏", "revision": 1}
    assert (
        approval_client.post(
            url + "/revision", json=payload, headers={"x-test-user": "bob"}
        ).status_code
        == 404
    )
    assert (
        approval_client.post(
            url + "/revision", json=payload, headers={"x-test-source": "token"}
        ).status_code
        == 403
    )
    assert (
        approval_client.post(
            url + "/revision", json=payload, headers={"x-test-access": "denied"}
        ).status_code
        == 403
    )
    assert (
        approval_client.post(
            url + "/revision", json={"reason": "   ", "revision": 1}
        ).status_code
        == 422
    )
    assert (
        approval_client.post(
            "/api/supportops/actions/missing/revision", json=payload
        ).status_code
        == 404
    )
    assert approval_client.get(url).json()["reason"] == action["reason"]


def test_legacy_database_preserves_decision_and_adds_revision(
    approval_client, tmp_path
):
    # 使用旧版表结构，验证已经登记并批准的真实旧记录可以继续读取和修改。
    path = tmp_path / "supportops" / "actions.sqlite3"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE actions (
            action_id TEXT PRIMARY KEY, order_id TEXT, reason TEXT, owner_user_id TEXT,
            thread_id TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute(
            "INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("legacy", "ORD-1001", "物流一直没动", "alice", "thread-1", "approved"),
        )
    url = "/api/supportops/actions/legacy"
    assert approval_client.get(url).json()["revision"] == 1
    assert approval_client.get(url).json()["status"] == "approved"
    response = approval_client.post(
        url + "/revision", json={"reason": "商品损坏", "revision": 1}
    )
    assert response.json()["status"] == "pending_approval"
    assert response.json()["revision"] == 2


def test_competing_revisions_only_apply_one(tmp_path, monkeypatch):
    from supportops_extension.action_store import get_action, revise_action

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    action = draft()

    def submit(reason):
        try:
            return revise_action(action["action_id"], "alice", reason, 1)["reason"]
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["商品损坏", "无法登录服务"]))
    assert results.count("conflict") == 1
    saved = get_action(action["action_id"], "alice")
    assert saved["reason"] in results
    assert saved["revision"] == 2
