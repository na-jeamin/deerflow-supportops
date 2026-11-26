# 运行 SupportOps 15 项评估

本文说明如何由用户本地启动服务并执行 [run_agent_eval.py](run_agent_eval.py)，依次跑完 [EVAL-CASES.md](EVAL-CASES.md) 中的 `A01`–`A15`。脚本从环境变量读取地址与凭证，**请用尖括号内描述替换为你自己的值，不要把任何真实凭证提交到仓库**。

## 前置条件

- 已按仓库说明准备好后端虚拟环境 `backend\.venv`、前端 `frontend\node_modules`、本地 `config.yaml`（启用 `supportops` 扩展）及 `.env` 模型配置。
- 业务数据库位于当前 `DEER_FLOW_HOME`（默认项目根目录 `.deer-flow`）下的 `supportops\actions.sqlite3`；建议与日常数据隔离或提前记录已有记录。
- 确认脚本可用参数（对应 `run_agent_eval.py --help`）：`--dry-run`、`--action-id`、`--output-dir`。

## 步骤 1：启动 Gateway

在仓库根目录 `D:\tt\agent\projects\deerflow-supportops` 执行（命令取自 [VALIDATION.md](VALIDATION.md#L57)，监听 `8003` 端口）：

```powershell
.\backend\.venv\Scripts\python.exe -c "import sys; sys.path[:0] = ['extensions/supportops', 'backend']; import uvicorn; uvicorn.run('app.gateway.app:app', host='127.0.0.1', port=8003)"
```

## 步骤 2：启动前端

另开一个 PowerShell 窗口，进入 `frontend` 目录执行（命令取自 [VALIDATION.md](VALIDATION.md#L66-L67)，监听 `3000` 端口并将 `/api/*` 转发至 `8003`）：

```powershell
$env:DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = 'http://127.0.0.1:8003'
node .\node_modules\next\dist\bin\next dev --webpack --hostname 127.0.0.1 --port 3000
```

## 步骤 3：在浏览器取得凭证

1. 在浏览器打开 `http://127.0.0.1:3000` 并完成登录（首次使用按页面引导完成管理员初始化）。
2. 按 `F12` 打开浏览器开发者工具，切到 **Application / 存储 → Cookies → `http://127.0.0.1:3000`**，记录两个 Cookie 值：
   - `access_token`（会话 JWT）
   - `csrf_token`（CSRF 防护令牌）
3. `A07`–`A15` 审批与建单接口强制要求浏览器会话（`auth_source == "session"`）与 `X-CSRF-Token` 请求头；同时 Gateway 的 `Authorization` 请求头只接收 `dfp_` 开头的 PAT，不能把浏览器 `access_token` 放进 `Authorization` 请求头。设置 `DEERFLOW_COOKIE` 与 `DEERFLOW_CSRF_TOKEN` 即可同时满足 `A01`–`A15`（若已设置 `DEERFLOW_COOKIE`，可不设 `DEERFLOW_TOKEN`）：

```powershell
$env:DEERFLOW_BASE_URL = "http://127.0.0.1:8003"
$env:DEERFLOW_CSRF_TOKEN = "<从浏览器复制的 csrf_token>"
$env:DEERFLOW_COOKIE = "access_token=<从浏览器复制的 access_token>; csrf_token=<从浏览器复制的 csrf_token>"
```

- **替代方案（若无法从浏览器读取 Cookie）**：打开 `http://127.0.0.1:8003/docs`，调用 `POST /api/v1/auth/login/local` 登录后，在浏览器开发者工具 **Network** 面板点击任意一条已登录的 `POST /api/supportops/...` 或 `/api/threads/...` 请求，从 **Request Headers** 中复制 `Cookie` 与 `X-CSRF-Token` 请求头填入上述环境变量。

## 步骤 4：建一个会话并拿到 thread_id

1. 在工作台页面点击「新对话」进入聊天页，发送一条测试消息创建会话（或新建空白对话）。
2. 从浏览器地址栏 `/workspace/chats/<thread_id>` 或开发者工具 **Network** 中 `/api/threads/<thread_id>/...` 请求路径复制 `thread_id`：

```powershell
$env:DEERFLOW_THREAD_ID = "<新建会话的 thread_id>"
```

## 步骤 5：先 dry-run 确认

在发送任何真实请求前，在仓库根目录执行 `--dry-run` 核对 15 条请求目标与请求体：

```powershell
.\backend\.venv\Scripts\python.exe -X utf8 .\extensions\supportops\run_agent_eval.py --dry-run
```

## 步骤 6：正式运行

确认 Gateway 8003 与上述环境变量均在当前 PowerShell 窗口生效后，执行：

```powershell
.\backend\.venv\Scripts\python.exe -X utf8 .\extensions\supportops\run_agent_eval.py
```

- 默认将 `A07`–`A15` 串联在 `A05` 生成的 `action_id` 上。如果 `A05` 未能提取到 `action_id`，可在手动登记一条第 1 版 `pending_approval` 申请后追加 `--action-id <第1版申请编号>` 重新运行；否则 `A07`–`A15` 会跳过并记为 `TBD`。
- 如果前置用例失败，依赖它的用例会跳过并记为 `TBD`。A13 会在第 2 版审批确认失败时记录原因并停止建单。A13 通过要求响应包含正确的申请编号、成功状态、第 2 版和有效工单编号。A14 还要核对返回的工单编号与 A13 相同。
- 可选 `--output-dir <输出目录>` 指定结果保存路径，默认保存在 `extensions\supportops\`。

## 步骤 7：看结果、填回 EVAL-CASES.md

1. 脚本运行结束后会在输出目录生成 `EVAL-RESULTS-<UTC时间戳>.md` 与 `EVAL-RESULTS-<UTC时间戳>.json`。
2. 逐行核对每条用例的 `http_status`、`actual_preview`（含聊天用例解析出的工具调用与 `artifact` 摘要）与 `conclusion`。
3. 仅根据本次实测输出，将 [EVAL-CASES.md](EVAL-CASES.md) 中对应行的「实际结果」与「结论」从 `待运行` / `TBD` 更新为实测事实。

脚本根据工具消息和接口响应判定。需要确认用户看到的回复、SQLite 中是否落库或是否只有一条工单时，应结合聊天记录或数据库查询。A04 记录模型如何处理非法订单号，留给人工查看。

## 常见失败

- **HTTP 401**：`access_token` 已过期或缺少有效会话，重新登录后更新 `DEERFLOW_COOKIE`。如果单独设置了 `DEERFLOW_CSRF_TOKEN`，也更新为同一会话的值。
- **HTTP 403**：缺少 `X-CSRF-Token` 请求头，或未通过浏览器 Cookie 发送会话（仅带请求头认证会被审批路由拦截），确认 `DEERFLOW_CSRF_TOKEN` 与 `DEERFLOW_COOKIE` 中的 `csrf_token` 一致且均已设置。
- **A07 审批返回 409，后续接口用例跳过**：核对 `--action-id` 对应申请是否为本人发起、内容匹配并仍处于第 1 版待审批状态。
- **`A07`–`A15` 全部显示 `TBD`（跳过）**：`A05` 未成功创建或提取出 `action_id`，且未传入 `--action-id`。
- **聊天用例返回 `fail` 且摘要提示未调用工具**：说明 Gateway 返回了 HTTP 200 但模型未调用 `query_order` / `prepare_after_sales` 或 `artifact` 字段不符合预期，按 `actual_preview` 中的缺失字段与 Gateway 日志排查。
