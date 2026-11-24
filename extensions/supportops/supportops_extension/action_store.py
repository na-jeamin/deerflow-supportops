"""SQLite storage for SupportOps actions and after-sales tickets."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

Action = dict[str, str | int | None]


def _database_path() -> Path:
    project_root = Path(os.environ.get("DEER_FLOW_PROJECT_ROOT") or Path.cwd())
    data_dir = Path(os.environ.get("DEER_FLOW_HOME") or project_root / ".deer-flow")
    return (data_dir / "supportops" / "actions.sqlite3").resolve()


def _ensure_revision(db: sqlite3.Connection) -> None:
    """Upgrade the existing draft table inside the caller's write transaction."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(actions)")}
    if "revision" not in columns:
        db.execute("ALTER TABLE actions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")


def _public_action(row: sqlite3.Row) -> Action:
    result = {key: row[key] for key in ("action_id", "order_id", "reason", "status")}
    # 旧记录沿用第1版，读取时保持只读。
    result["revision"] = row["revision"] if "revision" in row.keys() else 1
    return result


def save_pending_action(
    order_id: str, reason: str, owner_user_id: str, thread_id: str
) -> Action:
    """Insert one pending after-sales action and return its public fields."""
    db_path = _database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    action = {
        "action_id": uuid4().hex,
        "order_id": order_id,
        "reason": reason,
        "status": "pending_approval",
        "revision": 1,
    }
    with closing(sqlite3.connect(db_path, timeout=5)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY NOT NULL,
                order_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _ensure_revision(db)
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


def get_action(action_id: str, owner_user_id: str) -> Action:
    """Read the caller's draft using an owner-scoped database query."""
    path = _database_path()
    if not path.is_file():
        raise LookupError("Application not found")
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise LookupError("Application not found")
    return _public_action(row)


def list_actions(owner_user_id: str) -> list[Action]:
    """List the caller's applications and their optional saved tickets."""
    path = _database_path()
    if not path.is_file():
        return []
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("PRAGMA table_info(actions)")}
        revision_field = "a.revision" if "revision" in columns else "1 AS revision"
        tickets_exist = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tickets'"
        ).fetchone()
        ticket_fields = (
            "t.ticket_id, t.created_at AS ticket_created_at"
            if tickets_exist
            else "NULL AS ticket_id, NULL AS ticket_created_at"
        )
        ticket_join = (
            "LEFT JOIN tickets AS t ON t.action_id=a.action_id" if tickets_exist else ""
        )
        rows = db.execute(
            "SELECT a.action_id, a.order_id, a.reason, a.status, "
            f"{revision_field}, "
            f"a.created_at, {ticket_fields} FROM actions AS a {ticket_join} "
            "WHERE a.owner_user_id=? ORDER BY a.created_at DESC, a.action_id DESC",
            (owner_user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def decide_action(
    action_id: str,
    owner_user_id: str,
    order_id: str,
    reason: str,
    decision: str,
    revision: int = 1,
) -> Action:
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
        _ensure_revision(db)
        row = db.execute(
            "SELECT * FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise LookupError("Application not found")
        if row["revision"] != revision:
            raise ValueError("Application revision changed; review it again")
        if row["order_id"] != order_id or row["reason"] != reason:
            raise ValueError("Application content changed; review it again")
        if row["status"] not in ("pending_approval", status):
            raise ValueError("Application already has another decision")
        db.execute(
            "UPDATE actions SET status=? WHERE action_id=? AND owner_user_id=?",
            (status, action_id, owner_user_id),
        )
        result = _public_action(row)
        result["status"] = status
    return result


def revise_action(
    action_id: str, owner_user_id: str, reason: str, revision: int
) -> Action:
    """Save new content and require another decision on the new revision."""
    path = _database_path()
    if not path.is_file():
        raise LookupError("Application not found")
    with (
        closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)) as db,
        db,
    ):
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        _ensure_revision(db)
        row = db.execute(
            "SELECT * FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise LookupError("Application not found")
        if row["revision"] != revision:
            raise ValueError("Application revision changed; review it again")
        if row["status"] not in ("pending_approval", "approved", "rejected"):
            raise ValueError("Application can no longer be edited")
        result = _public_action(row)
        if row["reason"] == reason:
            return result
        # 原因和版本一起更新，旧批准同时失效。
        db.execute(
            "UPDATE actions SET reason=?, status='pending_approval', revision=revision+1 "
            "WHERE action_id=? AND owner_user_id=?",
            (reason, action_id, owner_user_id),
        )
        result.update(reason=reason, status="pending_approval", revision=revision + 1)
    return result


def execute_action(action_id: str, owner_user_id: str, revision: int) -> Action:
    """Create one ticket for the approved revision, or return its saved ticket."""
    path = _database_path()
    if not path.is_file():
        raise LookupError("Application not found")
    with (
        closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)) as db,
        db,
    ):
        db.row_factory = sqlite3.Row
        # 先拿到写权限，再读审批状态，避免两个执行请求同时读到 approved。
        db.execute("BEGIN IMMEDIATE")
        _ensure_revision(db)
        action = db.execute(
            "SELECT * FROM actions WHERE action_id=? AND owner_user_id=?",
            (action_id, owner_user_id),
        ).fetchone()
        if action is None:
            raise LookupError("Application not found")
        if action["revision"] != revision:
            raise ValueError("Application revision changed; review it again")
        if action["status"] == "succeeded":
            ticket = db.execute(
                "SELECT * FROM tickets WHERE action_id=?", (action_id,)
            ).fetchone()
            if ticket is None:
                raise sqlite3.DatabaseError("Completed application has no ticket")
            return dict(ticket)
        if action["status"] != "approved":
            raise ValueError("Application must be approved before execution")

        db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY NOT NULL,
                action_id TEXT NOT NULL UNIQUE,
                order_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 订单号和原因从已批准的记录取出，调用方只提供申请编号和版本。
        ticket = db.execute(
            "INSERT INTO tickets (ticket_id, action_id, order_id, reason, revision) VALUES (?, ?, ?, ?, ?) RETURNING *",
            (uuid4().hex, action_id, action["order_id"], action["reason"], revision),
        ).fetchone()
        # 工单和成功状态一起提交，任一步失败时一起回滚。
        db.execute(
            "UPDATE actions SET status='succeeded' WHERE action_id=?", (action_id,)
        )
    return dict(ticket)
