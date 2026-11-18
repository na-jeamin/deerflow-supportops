# SupportOps for DeerFlow: read-only order lookup

This extension adds one read-only model tool named `query_order`. It reads a
small fixed demonstration dataset and returns an order status. It performs no
network request and no write operation.

The current fixed examples are `ORD-1001` (`配送中`) and `ORD-1002` (`已签收`).
Their sample values live in `supportops_extension/__init__.py`.

The extension is the first T4 step. The later SupportOps work will add approval,
an action ledger, and idempotent writes after this tool is verified through the
native DeerFlow execution chain.

Install from the DeerFlow repository root with the backend environment:

```powershell
.\backend\.venv\Scripts\deerflow.exe extensions install .\extensions\supportops --yes
```

Set both switches in the local `config.yaml` entry, then restart the Gateway.

```yaml
plugins:
  - name: supportops
    package: supportops-deerflow-extension
    use: supportops_extension:install
    enabled: true
    config:
      enabled: true
```

The host exposes the registered tool as
`ext_supportops_order_query_order_822d9a950536`. Ask the Agent to query
`ORD-1001` and inspect the tool result. Its text and artifact identify the data
as synthetic demonstration data shared by all users of this demo.

Local-directory installation creates a managed source snapshot under
`backend/extensions/sources/supportops-deerflow-extension`. The backend lock
file refers to this snapshot. Later source changes can be installed with
`deerflow.exe extensions upgrade .\extensions\supportops --yes` followed by a
Gateway restart.

Editing the managed snapshot alone does not update the already installed
package in `backend/.venv/Lib/site-packages`. After an upgrade, check the
imported module before restarting. If the installed copy is stale, force a
reinstall of this package from the managed snapshot using a writable uv cache:

```powershell
D:\tt\tools\uv\uv.exe pip install --no-deps --reinstall --python .\backend\.venv\Scripts\python.exe .\backend\extensions\sources\supportops-deerflow-extension
```

Offline checks from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_order_tool.py -q
```

The eight checks cover the declaration, input schema, known and unknown orders,
and dispatch through the host's real extension loader and ToolNode. The first
live known-order round trip succeeded on November 17, 2026. That run used an
older installed copy without the synthetic-data markers. The installed code
has since been refreshed and checked offline; a Gateway restart and live
verification of the markers remain pending. Full upstream offline suites have
not been run for this change.

## Sources and local changes

The packaging and ModelTool contribution follow the upstream synthetic retrieval
example at `examples/deerflow-extension-retrieval`, based on DeerFlow commit
`c6a39936954d103f24293bfc165cb40e68d44464`. Upstream MIT licensing and attribution
remain in the repository. This extension adds the demo order data, order ID
schema, query handler, registration and focused tests. The Agent loop and tool
dispatch are supplied by DeerFlow and LangChain.
