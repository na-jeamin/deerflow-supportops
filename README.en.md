# DeerFlow SupportOps Order Assistant

[中文](README.md) | English

A DeerFlow-based order assistant that adds a read-only tool for looking up synthetic orders. The model requests a lookup, DeerFlow executes the tool, and the model answers using the returned result.

The demo uses fixed local order data. It saves after-sales drafts pending approval. The requester can review and approve or reject a draft through browser-session endpoints. Ticket creation is planned for the next stage.

## What this project adds

- A native DeerFlow order lookup extension that validates order IDs and returns both model-readable text and structured results.
- An after-sales draft tool that stores the request, requester, and thread in SQLite with an initial status of `pending_approval`.
- Browser-session endpoints for reviewing drafts and recording owner-bound approval or rejection.
- A Swagger UI fix that adds the CSRF header to same-origin mutation requests. Server-side validation stays enabled.
- Live checks for order lookup, after-sales drafts, approval, rejection and conflicting submissions. Focused and blocking-I/O checks passed 370 tests with 8 skipped. The full standard suite has not completed.

DeerFlow provides model integration, the agent loop, message history, and tool dispatch. This project adds the business tool and its tests.

## Try it

1. Prepare the backend environment and model configuration using the [upstream setup guide](https://github.com/bytedance/deer-flow/blob/c6a39936954d103f24293bfc165cb40e68d44464/README.md).
2. Enable the bundled extension using the [extension guide](extensions/supportops/README.md#english), then start the Gateway.
3. Sign in at `/docs` and use **Wait Run** to look up `ORD-1001` or `ORD-9999`. Check the `tool` message to see what the model based its answer on.

`ORD-1001` currently returns `配送中` (in transit). A live retest confirmed that the tool and model both reflected the change from `已发货` (shipped). `ORD-9999` returns `found: false`, and the model reported that the demo order was not found.

See the [tool implementation](extensions/supportops/supportops_extension/__init__.py) and [offline tests](backend/tests/test_supportops_order_tool.py). The upstream base is [DeerFlow `c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464); upstream attribution and the [MIT license](LICENSE) are retained.
