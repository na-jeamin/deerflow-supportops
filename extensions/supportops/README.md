# SupportOps 订单查询与售后草稿扩展

中文 | [English](#english)

扩展通过 DeerFlow 的 `ModelTool` 接口注册 `query_order`。它只读本地演示数据，不发网络请求，也不会修改订单。输入为 `order_id`，格式是 `ORD-` 加四位数字。已存在的样例是 `ORD-1001`（配送中）和 `ORD-1002`（已签收）。

工具返回 `content`（供模型阅读的文字）和 `artifact`（供程序检查的结构化结果）。`artifact.data_source` 为 `synthetic_demo`，`artifact.found` 表示是否找到订单。

## 配置与运行

本仓库的 `backend/uv.lock` 已包含扩展安装快照。先按上游说明同步后端依赖，然后在项目根目录的本地 `config.yaml` 里启用扩展。若已存在 `plugins` 列表，在列表下添加这一项即可：

```yaml
plugins:
  - name: supportops
    package: supportops-deerflow-extension
    use: supportops_extension:install
    enabled: true
    config:
      enabled: true
```

重启 Gateway 后，在 `/docs` 登录并新建会话，打开 `POST /api/threads/{thread_id}/runs/wait`（**Wait Run**），填入会话编号和下面的请求体。`model_name` 应与本机配置中的模型名称一致。

```json
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "请查询演示订单 ORD-1001 的状态，并根据工具结果用中文回答。"
      }
    ]
  },
  "context": {"model_name": "default", "subagent_enabled": false}
}
```

看该轮的 `tool` 消息：`ORD-1001` 应显示“配送中”，`ORD-9999` 应显示未找到。工具在运行时的完整名称是 `ext_supportops_order_query_order_822d9a950536`。

沿用同一个 **Wait Run** 请求，把 `content` 改为「请为演示订单 ORD-1001 申请售后，原因是物流停滞。」预期出现 `prepare_after_sales` 对应的工具消息，其中 `artifact.action_id` 为申请编号，`artifact.status` 为 `pending_approval`。申请保存在 `DEER_FLOW_HOME` 下的 `supportops/actions.sqlite3`。默认使用项目根目录的 `.deer-flow`，建议在本地启动命令中显式设置 `DEER_FLOW_HOME`。

## 查看申请和确认决定

在 DeerFlow 工作区侧栏打开 **售后工单**，即可查看当前登录用户的申请，并执行后续操作。申请登记请在聊天中向 Agent 提出，例如“请为演示订单 ORD-1001 申请售后，原因是物流停滞”。工作台只显示当前登录用户自己的申请，修改、审批和建单请求都会由服务端再次核对身份、权限和版本。

也可以在 `/docs` 的 **SupportOps** 分组中使用 `GET /api/supportops/actions` 列出本人申请，或打开 `GET /api/supportops/actions/{action_id}` 查看单笔申请。

申请列表接口为只读，按当前登录用户过滤，并将申请与可选工单信息合并返回。旧数据库没有工单表时，仍会列出申请并将工单字段返回为空。

核对内容后，在 `POST /api/supportops/actions/{action_id}/decision` 填写同一个编号及以下请求体。订单号和原因应与查看结果一致。

```json
{
  "order_id": "ORD-1001",
  "reason": "物流一直没动",
  "decision": "approve",
  "revision": 1
}
```

`approve` 保存为已批准，`reject` 保存为已拒绝。请求使用当前浏览器的登录会话和宿主 CSRF 校验。接口核对记录归属和申请内容，并在事务中保存状态。同一个决定重发返回已有结果，冲突决定或内容不一致返回 409。

## 修改原因后重新确认

打开 `POST /api/supportops/actions/{action_id}/revision`，填写原申请编号，以及从查看接口取得的当前版本号。例如第 1 版改成新原因：

```json
{
  "reason": "商品损坏",
  "revision": 1
}
```

修改成功会返回新原因、`revision: 2` 和 `status: pending_approval`，供用户重新核对。然后在决定接口提交新原因和第 2 版编号，选择批准或拒绝。旧版本确认返回 409。原因实际改变时才增加版本，同样内容重复提交保留原状态。历史数据库记录按第 1 版读取，在后续写入时自动补版本字段。

在 `POST /api/supportops/actions/{action_id}/execute` 填入已批准的申请编号，请求体填写当前版本，例如 `{"revision": 3}`。订单号和原因从已批准的申请读取。成功后返回 `status: succeeded` 和工单编号 `ticket_id`。再次提交相同请求会返回同一张工单。旧版本、待审批和已拒绝的申请返回 409。

## 修改扩展和验证

测试导入隔离、全量前端结果和不重装环境的本地网页启动方法见
[验证记录与网页验收入口](VALIDATION.md)。

演示数据与查询函数在 `supportops_extension/__init__.py`。从仓库根目录执行下面的命令可以更新扩展，之后重启 Gateway。

```powershell
.\backend\.venv\Scripts\deerflow.exe extensions upgrade .\extensions\supportops --yes
```

若在上游 DeerFlow 的新检出目录里首次接入此扩展，使用 `extensions install`。本仓库已经配置扩展，使用 `upgrade`。受管快照位于 `backend/extensions/sources/supportops-deerflow-extension`；直接编辑快照不会自动更新 Python 环境中已经安装的包。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_order_tool.py -q
```

真实运行已验证订单查询、售后登记、批准、拒绝、冲突拦截、修改原因后重新确认、首次建单、重试、旧版执行拦截，以及 SQLite 锁期间写入失败和解锁后恢复。SQLite 核对确认重试不会多建工单，失败时未写入申请。35 项 SupportOps 后端定向测试、3 项工作台交互测试及前端类型/lint/格式检查通过；普通全量回归待完成。

扩展注册参考 DeerFlow `c6a399369` 的 `examples/deerflow-extension-retrieval` 示例，保留 MIT 许可证与上游归属。

## English

### Implementation rules

SupportOps persists pending after-sales drafts in the extension's SQLite store.
Record ownership from the host tool context and keep approval decisions out of
model tool parameters. Update the deployable extension snapshot with its source.
Approval routes live in the SupportOps extension. Require host plugin authorization,
a browser session, record ownership and matching order/reason before a decision.
Reason edits increment the draft revision and reset approval in one transaction.
Bind decisions to that revision. Treat legacy records as revision 1.

The extension registers two native DeerFlow model tools. `query_order` looks up fixed synthetic orders and returns text and structured data. `prepare_after_sales` accepts an order ID and a reason and saves a draft pending approval.

The managed snapshot is already included in the backend lockfile. Sync the backend environment, add the `plugins` entry shown above to local `config.yaml`, and start DeerFlow with its frontend and Gateway. Use the native chat UI to query orders and ask the Agent to create after-sales drafts.

To try a draft, replace the sample message with a request to start after-sales service for `ORD-1001` because the shipment stalled. The draft tool returns an `action_id` and `status: pending_approval` after saving it to SQLite. Use the upgrade command above after editing the extension, then restart. Focused offline tests cover both tools. Live runs verified the lookup tool. Packaging follows DeerFlow's retrieval extension example at `c6a399369` under the MIT license.

Open **Support requests** in the workspace sidebar to review your applications, edit a reason, approve or reject, and execute an approved request. The page is owner-scoped; the backend rechecks session, plugin permission and revision on every mutation. Editing a reason increments the revision and resets approval. `GET /api/supportops/actions` lists only the signed-in user's applications and optional ticket details; it also supports legacy databases without a tickets table. `/docs` remains available for API debugging. Older confirmations return HTTP 409, including when the reason changes back later. Legacy records start at revision 1. Live checks verified draft creation, approval, rejection, conflicting decisions, a content edit, rejection of the stale revision, current-revision approval, ticket execution, and SQLite lock failure/recovery.

Use `POST /api/supportops/actions/{action_id}/execute` with the current approved revision to create a local demo ticket. Retrying the same request returns the saved ticket. Creating the ticket and marking the application `succeeded` share one SQLite transaction.
