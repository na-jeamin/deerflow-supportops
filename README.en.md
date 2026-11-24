# DeerFlow SupportOps Order Assistant

[中文](README.md) | English

A DeerFlow-based order assistant. Users can look up demo orders and create after-sales requests through the native chat, then review requests and create tickets in the SupportOps workspace.

The demo uses fixed local order data. It saves after-sales drafts pending approval. The requester can review and approve or reject a draft through browser-session endpoints, then execute the approved request to create a local SQLite ticket.

## What this project adds

- A native DeerFlow order lookup extension that validates order IDs and returns both model-readable text and structured results.
- An after-sales draft tool that stores the request, requester, and thread in SQLite with an initial status of `pending_approval`.
- Browser-session endpoints for reviewing drafts and recording owner-bound approval or rejection.
- Draft edits increment a revision and reset approval. Live verification confirmed that an old revision is rejected and the updated revision can be approved.
- Execution checks ownership, revision, and approval. Ticket creation and the application status update share one SQLite transaction. Retrying the same request returns the saved ticket.
- A SupportOps workspace page lists the signed-in user's requests and supports editing, approval/rejection, and ticket execution. New requests are still created through the native DeerFlow chat and Agent tools.
- A Swagger UI fix that adds the CSRF header to same-origin mutation requests. Server-side validation stays enabled.
- Live checks cover order lookup, after-sales drafts, approval, rejection, revision changes, ticket creation, same-revision retry, stale-revision rejection, and SQLite-lock failure/recovery. All 35 focused SupportOps backend tests and 3 workspace UI interaction tests pass; TypeScript, ESLint, and formatting checks pass. Full regression coverage is pending.

DeerFlow provides model integration, the agent loop, message history, and tool dispatch. This project adds the business tools, approval and ticket workflows, a SupportOps workspace page, and their tests.

## Try it

1. Prepare the frontend, backend and model configuration using the [upstream setup guide](https://github.com/bytedance/deer-flow/blob/c6a39936954d103f24293bfc165cb40e68d44464/README.md).
2. Enable the bundled extension using the [extension guide](extensions/supportops/README.md#english), then start DeerFlow.
3. Use the native chat UI to query orders or create after-sales requests. Open **Support requests** in the workspace sidebar to review, edit, approve/reject and execute them. `/docs` remains available for API debugging.

`ORD-1001` currently returns `配送中` (in transit). A live retest confirmed that the tool and model both reflected the change from `已发货` (shipped). `ORD-9999` returns `found: false`, and the model reported that the demo order was not found.

See the [tool implementation](extensions/supportops/supportops_extension/__init__.py) and [offline tests](backend/tests/test_supportops_order_tool.py). The upstream base is [DeerFlow `c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464); upstream attribution and the [MIT license](LICENSE) are retained.
