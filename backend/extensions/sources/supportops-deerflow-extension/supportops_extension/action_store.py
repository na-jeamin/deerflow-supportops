"""SQLite storage for pending SupportOps actions."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


def _database_path() -> Path:
    project_root = Path(os.environ.get("DEER_FLOW_PROJECT_ROOT") or Path.cwd())
    data_dir = Path(os.environ.get("DEER_FLOW_HOME") or project_root / ".deer-flow")
    return (data_dir / "supportops" / "actions.sqlite3").resolve()


def save_pending_action(
    order_id: str, reason: str, owner_user_id: str, thread_id: str
) -> dict[str, str]:
    """Insert one pending after-sales action and return its public fields."""
    db_path = _database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    action = {
        "action_id": uuid4().hex,
        "order_id": order_id,
        "reason": reason,
        "status": "pending_approval",
    }
    with closing(sqlite3.connect(db_path, timeout=5)) as db, db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY NOT NULL,
                order_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 订单和原因作为 SQL 参数传入。正常退出代码块后提交记录。
        db.execute(
            "INSERT INTO actions (action_id, order_id, reason, owner_user_id, thread_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (
                action["action_id"],
                order_id,
                reason,
                owner_user_id,
                thread_id,
                action["status"],
            ),
        )
    return action


def get_action(action_id: str, owner_user_id: str) -> dict[str, str]:
    """Read the caller's draft using an owner-scoped database query."""
    path = _database_path()
    if not path.is_file():
        raise LookupError("Application not found")
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT action_id, order_id, reason, status FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise LookupError("Application not found")
    return dict(row)


def decide_action(
    action_id: str, owner_user_id: str, order_id: str, reason: str, decision: str
) -> dict[str, str]:
    """Atomically bind one human decision to the exact saved draft."""
    if decision not in ("approve", "reject"):
        raise ValueError("Unknown decision")
    path = _database_path()
    if not path.is_file():
        raise LookupError("Application not found")
    status = "approved" if decision == "approve" else "rejected"
    with (
        closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)) as db,
        db,
    ):
        db.row_factory = sqlite3.Row
        # 核对内容和更新状态放在同一事务里，两个同时提交的决定依次处理。
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT action_id, order_id, reason, status FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise LookupError("Application not found")
        if row["order_id"] != order_id or row["reason"] != reason:
            raise ValueError("Application content changed; review it again")
        if row["status"] not in ("pending_approval", status):
            raise ValueError("Application already has another decision")
        db.execute(
            "UPDATE actions SET status=? WHERE action_id=? AND owner_user_id=?",
            (status, action_id, owner_user_id),
        )
        result = dict(row)
        result["status"] = status
    return result
