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

在 `/docs` 的 **SupportOps** 分组中打开 `GET /api/supportops/actions/{action_id}`，填写刚登记的申请编号，查看订单号、原因和当前状态。

核对内容后，在 `POST /api/supportops/actions/{action_id}/decision` 填写同一个编号及以下请求体。订单号和原因应与查看结果一致。

```json
{
  "order_id": "ORD-1001",
  "reason": "物流一直没动",
  "decision": "approve",
  "revision": 1
}
```

`approve` 保存为已批准，`reject` 保存为已拒绝。请求使用当前浏览器的登录会话和宿主 CSRF 校验。接口核对记录归属和申请内容，并在事务中保存状态。同一个决定重发返回已有结果，冲突决定或内容不一致返回 409。工单创建安排在下一阶段。

## 修改原因后重新确认

打开 `POST /api/supportops/actions/{action_id}/revision`，填写原申请编号，以及从查看接口取得的当前版本号。例如第 1 版改成新原因：

```json
{
  "reason": "商品损坏",
  "revision": 1
}
```

修改成功会返回新原因、`revision: 2` 和 `status: pending_approval`，供用户重新核对。然后在决定接口提交新原因和第 2 版编号，选择批准或拒绝。旧版本确认返回 409。原因实际改变时才增加版本，同样内容重复提交保留原状态。历史数据库记录按第 1 版读取，在后续写入时自动补版本字段。

## 修改扩展和验证

演示数据与查询函数在 `supportops_extension/__init__.py`。从仓库根目录执行下面的命令可以更新扩展，之后重启 Gateway。

```powershell
.\backend\.venv\Scripts\deerflow.exe extensions upgrade .\extensions\supportops --yes
```

若在上游 DeerFlow 的新检出目录里首次接入此扩展，使用 `extensions install`。本仓库已经配置扩展，使用 `upgrade`。受管快照位于 `backend/extensions/sources/supportops-deerflow-extension`；直接编辑快照不会自动更新 Python 环境中已经安装的包。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_order_tool.py -q
```

订单及审批聚焦测试覆盖36个用例。真实运行已验证订单查询、售后登记、批准、拒绝、相反决定冲突、内容不一致拦截、修改原因后重置审批、第1版确认失效及第3版重新批准。聚焦测试与阻塞 I/O 套件共 376 项通过、8 项跳过。普通全量回归尚未取得完整结论。

扩展注册参考 DeerFlow `c6a399369` 的 `examples/deerflow-extension-retrieval` 示例，保留 MIT 许可证与上游归属。

## English

The extension registers two native DeerFlow model tools. `query_order` looks up fixed synthetic orders and returns text and structured data. `prepare_after_sales` accepts an order ID and a reason and saves a draft pending approval.

The managed snapshot is already included in the backend lockfile. Sync the backend environment, add the `plugins` entry shown above to local `config.yaml`, and restart the Gateway. Sign in at `/docs`, create a thread, and use **Wait Run** with the example payload. `ORD-1001` is in transit; `ORD-9999` is not found.

To try a draft, replace the sample message with a request to start after-sales service for `ORD-1001` because the shipment stalled. The draft tool returns an `action_id` and `status: pending_approval` after saving it to SQLite. Use the upgrade command above after editing the extension, then restart. Focused offline tests cover both tools. Live runs verified the lookup tool. Packaging follows DeerFlow's retrieval extension example at `c6a399369` under the MIT license.

The **SupportOps** section in `/docs` provides owner-scoped GET, revision and decision endpoints. Review the saved draft, then submit its exact order ID, reason and revision with `decision: approve` or `decision: reject`. Browser-session authentication, host plugin authorization and CSRF checks apply. Editing a reason increments the revision and resets the status to pending approval. Older confirmations return HTTP 409, including when the reason changes back later. Legacy records start at revision 1. Live checks verified draft creation, approval, rejection, conflicting decisions, a content edit, rejection of the stale revision, and approval of the current revision. Focused and blocking-I/O checks passed 376 tests with 8 skipped. Ticket creation belongs to the next stage.
