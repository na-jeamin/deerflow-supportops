# DeerFlow SupportOps Order & After-Sales Assistant

[中文](README.md) | English

An order lookup and human-in-the-loop after-sales ticket assistant built on top of [DeerFlow](https://github.com/bytedance/deer-flow) (upstream base commit [`c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464)).

Users query demo orders and draft after-sales requests in natural language through DeerFlow's native chat, then review details, revise reasons, approve or reject, and idempotently create local SQLite tickets in the **SupportOps** workspace. The extension focuses on three practical Agent engineering safeguards: least-privilege tool schemas, revision-bound approval consistency, and transactional idempotency under retries or concurrency.

## Upstream Base vs. Project Additions

| Layer | Source | Scope |
| --- | --- | --- |
| Agent Runtime | Reused from DeerFlow upstream | Model integration, LangGraph agent loop, tool dispatch, thread checkpoints, auth & CSRF middleware, native chat UI |
| Business & Safety Additions | Added / modified in this repo | Native order & draft tools, SQLite action ledger with optimistic `revision` locking, `BEGIN IMMEDIATE` idempotent ticket execution, session-only approval routes, Swagger same-origin CSRF header fix, SupportOps workspace UI, offline tests & 15-case eval suite |

> Branding note: the workspace and sign-in pages use SupportOps branding linking to this repository, while the About page preserves DeerFlow attribution and acknowledgments.

## Architecture & State Machine

To prevent prompt injection or model mistakes from writing production-like business records directly, natural-language intake is separated from human approval and ticket creation:

```text
[Native Chat]
  ├── Order lookup (e.g., ORD-1001 / ORD-9999)
  │     └── query_order (read-only) ──> readable content + structured artifact (found / data_source)
  │
  └── After-sales request (e.g., "open after-sales for ORD-1002 due to stalled shipping")
        └── prepare_after_sales (draft only; owner & status excluded from model schema)
              └── Host injects owner_user_id + thread_id ──> SQLite pending_approval (revision=1)

[SupportOps Workspace (requires browser session + same-origin X-CSRF-Token)]
  pending_approval (v1)
    ├── reject ──────────────────────────────────────> rejected (terminal)
    └── approve (verifies order_id + reason + rev) ──> approved (v1)
          ├── revise reason ─────────────────────────> pending_approval (v2; v1 approval invalidated, stale requests return 409)
          └── execute (accepts revision only)
                └── BEGIN IMMEDIATE write lock + UNIQUE(action_id) on tickets
                      └── succeeded (single ticket persisted; retries return the same ticket, errors roll back atomically)
```

## Key Modules & Source Index

| Area | Mechanism | Code & Tests |
| --- | --- | --- |
| Least-privilege native tools | Enforces `^ORD-[0-9]{4}$` with `additionalProperties: false`; injects requester identity from host context; separates model `content` from machine-checked `artifact` | [Tool extension](extensions/supportops/supportops_extension/__init__.py) · [Tool tests](backend/tests/test_supportops_order_tool.py) |
| Revision state machine & idempotency | Editing a reason increments `revision` and resets status to `pending_approval` in one write transaction; execution uses `BEGIN IMMEDIATE` + `UNIQUE(action_id)` for atomic, idempotent ticket creation; read paths remain backward-compatible with legacy schemas | [Action store](extensions/supportops/supportops_extension/action_store.py) · [Approval & concurrency tests](backend/tests/test_supportops_approval.py) |
| Session-only routes & CSRF | Requires plugin write permission, non-anonymous user, `auth_source == "session"`, and double-submit CSRF; scopes queries by `owner_user_id` to prevent existence enumeration | [Approval routes](extensions/supportops/supportops_extension/approval_routes.py) |
| Swagger & workspace UI | Automatically attaches `X-CSRF-Token` for same-origin mutations in `/docs` without weakening backend validation; adds a native **Support requests** workspace page | [Swagger docs](backend/app/gateway/swagger_docs.py) · [Workspace UI](frontend/src/components/workspace/supportops/supportops-page.tsx) |
| Artifact-level evaluation suite | Isolates current-turn messages after the latest user message and verifies tool `artifact` fields, dependency gating, and ticket-ID idempotency instead of trusting HTTP 200 alone | [15 eval cases](extensions/supportops/EVAL-CASES.md) · [Eval runner](extensions/supportops/run_agent_eval.py) · [Judge unit tests](extensions/supportops/test_judge_chat_case.py) |

## Verification & Scope Boundaries

- **Offline automated checks**:
  - SupportOps suite: 35 backend `pytest` cases (tool schema, access control, revision invalidation, two-thread concurrent approval/revision/execution, and trigger-induced rollback) + 9 eval-judge `unittest` cases pass.
  - Host regressions: 179 related backend checks and 3,661 frontend tests (across 351 files) pass.
- **End-to-end & fault recovery evidence**:
  - Real browser acceptance (2026-11-24): verified chat drafting → approval → reason edit (`revision=2` invalidating `v1`) → re-approval → ticket creation → browser refresh and Gateway restart recovery, plus 11 live HTTP/SQLite checks (`401` unauthenticated, `403` missing CSRF, `409` stale revision, idempotent retry returning the same `ticket_id`, SQLite `integrity_check = ok`). See [ACCEPTANCE-2026-11-24.md](extensions/supportops/ACCEPTANCE-2026-11-24.md).
  - Fault drills: verified live demo-data refresh (`ORD-1001` updated from shipped to in transit), missing order handling (`ORD-9999` returning `found: false`), and exclusive SQLite lock failure without partial writes followed by clean retry after unlock. See [VALIDATION.md](extensions/supportops/VALIDATION.md).
- **Explicit boundaries**:
  - Uses fixed synthetic local order data rather than a production e-commerce database;
  - The full upstream 40,178-test backend suite was collected cleanly without conflicts, not executed in full;
  - The 15-case automated evaluation runner passed offline unit tests and `--dry-run`; live execution results remain pending via [RUN-EVAL.md](extensions/supportops/RUN-EVAL.md).

## Quick Start & Tests

1. Prepare the frontend, backend, and model configuration using the [upstream setup guide](https://github.com/bytedance/deer-flow/blob/c6a39936954d103f24293bfc165cb40e68d44464/README.md).
2. Enable the bundled extension using the [extension guide](extensions/supportops/README.md#english), then start Gateway and the frontend (see [VALIDATION.md](extensions/supportops/VALIDATION.md) for running directly against repository sources).
3. Use native chat to query `ORD-1001`/`ORD-9999` or draft an after-sales request, then open **Support requests** in the workspace sidebar to approve, edit, and execute tickets. `/docs` remains available for API debugging.
4. Run SupportOps offline tests:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_approval.py backend/tests/test_supportops_order_tool.py -q
.\backend\.venv\Scripts\python.exe -m unittest extensions.supportops.test_judge_chat_case -v
```

## Attribution & License

Built on [bytedance/deer-flow](https://github.com/bytedance/deer-flow) commit [`c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464), following its official extension pattern. Upstream attribution and the [MIT License](LICENSE) are preserved.
