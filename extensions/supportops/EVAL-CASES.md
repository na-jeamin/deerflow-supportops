# SupportOps Agent 评估用例集（15 项）

本评估集覆盖两类路径：
1. **聊天工具调用（A01–A06）**：通过 Gateway `POST /api/threads/{thread_id}/runs/wait` 触发 `query_order` 与 `prepare_after_sales`。
2. **审批与建单状态机接口（A07–A15）**：通过 `POST /api/supportops/actions/{action_id}/...` 验证版本绑定、冲突拦截与幂等建单（A07–A15 需浏览器登录会话与 CSRF 校验；A12 后需先批准第 2 版再执行 A13–A15）。

> 注：本文件仅记录静态核对得到的期望行为与源码依据；实际运行与结果填充待用户在本地服务启动后执行 `run_agent_eval.py`。实际运行方法见 [RUN-EVAL.md](RUN-EVAL.md)。

脚本记录工具结果及接口响应。表中的最终回复、数据库写入和工单数量需结合聊天记录或 SQLite 核验。

| ID | 场景 | 输入 | 期望结果 | 期望依据（文件:行号） | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| A01 | 查询存在订单 | 聊天："请查询演示订单 ORD-1001 的状态" | 调用 `query_order`；返回 `found=True`、`order_id=ORD-1001`、`status=配送中`、`product=演示测绘设备`、`after_sales=可申请物流查询`，不创建工单 | `extensions/supportops/supportops_extension/__init__.py:19-30,61-92`；`backend/tests/test_supportops_order_tool.py:116-159` | 待运行 | TBD |
| A02 | 查询第二个存在订单 | 聊天："请查询 ORD-1002 的状态" | 调用 `query_order`；返回 `found=True`、`order_id=ORD-1002`、`status=已签收`、`product=演示数据服务`、`after_sales=可申请售后咨询` | `extensions/supportops/supportops_extension/__init__.py:25-29,61-92` | 待运行 | TBD |
| A03 | 查询不存在订单 | 聊天："请查询 ORD-9999 的状态" | 调用 `query_order`；返回 `found=False`、`order_id=ORD-9999`，正文提示“演示数据中未找到订单ORD-9999。当前可查询ORD-1001和ORD-1002。” | `extensions/supportops/supportops_extension/__init__.py:65-74`；`backend/tests/test_supportops_order_tool.py:133-143` | 待运行 | TBD |
| A04 | 非法订单号格式 | 聊天："请查询订单 123" | TBD — 必须靠实跑确定（工具 Schema `^ORD-[0-9]{4}$` 会拦截 `"123"`）：① 若模型尝试调用 `query_order({"order_id": "123"})`，ToolNode 参数校验会返回 `ToolMessage(status="error")` 后由模型提示合法格式；② 若模型不调用工具直接回复并要求按 `ORD-加4位数字` 补充，则属前端提示拦截。两种行为均在 `actual_preview` 记录实测表现，结论保持 TBD | `extensions/supportops/supportops_extension/__init__.py:32-43`；`backend/tests/test_supportops_order_tool.py:161-173` | 待运行 | TBD |
| A05 | 正常登记售后 | 聊天："请为 ORD-1001 申请售后，原因是物流停滞" | 调用 `prepare_after_sales`；写入 SQLite，返回 `action_id`、`status=pending_approval`、`revision=1`，不批准也不创建工单 | `extensions/supportops/supportops_extension/__init__.py:95-125`；`action_store.py:34-74`；`backend/tests/test_supportops_order_tool.py:175-199` | 待运行 | TBD |
| A06 | 对不存在订单登记 | 聊天："请为 ORD-9999 申请售后，原因是测试" | 不写入 SQLite；若调用 `prepare_after_sales`，返回 `artifact.error="order_not_found"` 与“演示数据中未找到订单 ORD-9999。” | `extensions/supportops/supportops_extension/__init__.py:107-110`；`backend/tests/test_supportops_order_tool.py:201-237` | 待运行 | TBD |
| A07 | 批准第 1 版 | `POST .../decision`，`decision=approve`，`revision=1`（需匹配 `order_id`、`reason`） | HTTP 200，返回 `status="approved"`、`revision=1` | `extensions/supportops/supportops_extension/approval_routes.py:84-105`；`action_store.py:127-168`；`backend/tests/test_supportops_approval.py:246-270` | 待运行 | TBD |
| A08 | 对已批准申请再拒绝 | 同上，`decision=reject`，`revision=1` | HTTP 409（`status` 已非 `pending_approval` 且非 `rejected`，触发已有其他决定冲突），数据库仍为 `approved` | `extensions/supportops/supportops_extension/action_store.py:160-161`；`approval_routes.py:101-104`；`backend/tests/test_supportops_approval.py:331-350` | 待运行 | TBD |
| A09 | 内容不一致的批准 | 同 `revision` 但 `reason` 与登记时不同 | HTTP 409（`row["reason"] != reason` 触发内容不一致错误），数据库记录不变 | `extensions/supportops/supportops_extension/action_store.py:158-159`；`approval_routes.py:101-104`；`backend/tests/test_supportops_approval.py:331-337` | 待运行 | TBD |
| A10 | 批准后修改原因 | `POST .../revision`，新 `reason`，`revision=1` | HTTP 200，返回新 `reason`、`revision=2`、`status="pending_approval"`（旧批准失效） | `extensions/supportops/supportops_extension/action_store.py:171-205`；`approval_routes.py:106-120`；`backend/tests/test_supportops_approval.py:388-406`；`ACCEPTANCE-2026-11-24.md:25` | 待运行 | TBD |
| A11 | 用旧版本批准 | `POST .../decision`，`revision=1`（当前为 2） | HTTP 409（`row["revision"] != revision`），状态仍为 `pending_approval` | `extensions/supportops/supportops_extension/action_store.py:156-157`；`approval_routes.py:101-104`；`backend/tests/test_supportops_approval.py:407-415` | 待运行 | TBD |
| A12 | 执行未批准申请 | `POST .../execute`，`revision=2`（当前处于 `pending_approval`） | HTTP 409（`action["status"] != "approved"`），不创建工单 | `extensions/supportops/supportops_extension/action_store.py:236-237`；`approval_routes.py:133-134`；`backend/tests/test_supportops_approval.py:77-79` | 待运行 | TBD |
| A13 | 执行已批准申请 | 前置批准第 2 版后，`POST .../execute`，`revision=2` | HTTP 200，返回 `status="succeeded"`、`ticket_id`、`revision=2`，`tickets` 表新增 1 条工单 | `extensions/supportops/supportops_extension/action_store.py:208-258`；`approval_routes.py:122-135`；`backend/tests/test_supportops_approval.py:113-119`；`ACCEPTANCE-2026-11-24.md:26` | 待运行 | TBD |
| A14 | 重复执行同一版本 | 同 A13 再发一次，`POST .../execute`，`revision=2` | HTTP 200，幂等返回同一 `ticket_id`，`tickets` 表不重复建单 | `extensions/supportops/supportops_extension/action_store.py:229-235`；`approval_routes.py:122-135`；`backend/tests/test_supportops_approval.py:120`；`ACCEPTANCE-2026-11-24.md:47,51` | 待运行 | TBD |
| A15 | 执行旧版本 | `POST .../execute`，`revision=1`（当前为 2） | HTTP 409（`action["revision"] != revision` 优先于状态检查触发） | `extensions/supportops/supportops_extension/action_store.py:227-228`；`approval_routes.py:133-134`；`backend/tests/test_supportops_approval.py:97-99`；`ACCEPTANCE-2026-11-24.md:48` | 待运行 | TBD |
