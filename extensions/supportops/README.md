# SupportOps 只读订单查询扩展

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

## 修改扩展和验证

演示数据与查询函数在 `supportops_extension/__init__.py`。从仓库根目录执行下面的命令可以更新扩展，之后重启 Gateway。

```powershell
.\backend\.venv\Scripts\deerflow.exe extensions upgrade .\extensions\supportops --yes
```

若在上游 DeerFlow 的新检出目录里首次接入此扩展，使用 `extensions install`。本仓库已经配置扩展，使用 `upgrade`。受管快照位于 `backend/extensions/sources/supportops-deerflow-extension`；直接编辑快照不会自动更新 Python 环境中已经安装的包。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_order_tool.py -q
```

8 项订单离线测试覆盖注册、参数规则、已知/未知订单和工具执行结果。真实运行已验证正常查询、未知订单与状态修改后的返回；未完成上游普通全量回归。

扩展注册参考 DeerFlow `c6a399369` 的 `examples/deerflow-extension-retrieval` 示例，保留 MIT 许可证与上游归属。

## English

This read-only extension registers `query_order` through DeerFlow's native `ModelTool` API. It accepts an ID in the form `ORD-` followed by four digits and reads fixed synthetic data without network or write operations. The tool returns text in `content` and structured data in `artifact`, including `data_source: synthetic_demo` and `found`.

The managed snapshot is already included in the backend lockfile. Sync the backend environment, add the `plugins` entry shown above to local `config.yaml`, and restart the Gateway. Sign in at `/docs`, create a thread, and use **Wait Run** with the example payload. `ORD-1001` is in transit; `ORD-9999` is not found.

Use the upgrade command above after editing the extension, then restart. Eight focused offline tests cover registration, validation and dispatch. Live runs verified a known order, a missing order and a demo status change. The full standard upstream offline suite has not been completed. Packaging follows DeerFlow's retrieval extension example at `c6a399369` under the MIT license.
