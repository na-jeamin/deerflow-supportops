# SupportOps 验证记录与网页验收入口

日期：2026-11-24。以下测试均离线执行，没有启动项目服务或调用真实模型。

## 本次修复

- 后端测试在 `backend/tests/conftest.py` 中优先加入本仓库的扩展源码路径。
  这样 Gateway 被其他测试提前导入时，也不会缓存虚拟环境里较旧的扩展。
  不清空运行中的模块，不修改已安装的包。
- DOM 界面测试的超时上限设为 15 秒；Node 测试上限不变，所有断言保留。
  原先超时的定时任务组件文件单独运行 37 项通过，随后前端全量通过。
- 将根目录的 SupportOps 开发约束完整移至扩展 README，根目录保留链接，
  消除继承指令链超限；不修改预算检查或放宽上限。

本轮没有调用安装器、升级依赖、修改锁文件、pnpm 审批、`.env`、
虚拟环境或已有申请/工单数据。

## 已验证的范围

| 检查 | 结果 | 边界 |
| --- | --- | --- |
| 前端单元/DOM 全套 | 351 个文件，3661 项通过 | 模拟后端，不等于真实网页联调 |
| 后端 SupportOps、扩展加载、权限、CSRF、指令文档预算 | 179 项通过 | 定向组合，非后端全量运行 |
| 后端全量测试收集 | 40178 项成功收集 | 只验证能加载，没有执行全部用例 |
| 格式检查 | 修改的 Python/TypeScript 配置通过 Ruff/Prettier，diff 检查通过 | 无依赖版本变更 |
| 前端生产构建 | 本日此前的 Webpack 构建通过，包含工作台路由 | 未重复构建；本轮仅改测试配置与文档 |

本轮后端定向组合为以下九个文件：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_approval.py backend/tests/test_supportops_order_tool.py backend/tests/test_agent_guidance_check.py backend/tests/test_extension_app_loading.py backend/tests/test_extension_loader.py backend/tests/test_plugin_tools.py backend/tests/test_csrf_middleware.py backend/tests/test_gateway_swagger_csrf.py backend/tests/test_auth_me_permissions.py -q
```

在仓库根目录直接运行 SupportOps 测试：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_approval.py backend/tests/test_supportops_order_tool.py -q
```

前端从 `frontend` 目录直接运行已安装的测试程序，可避免本机 pnpm 自动触发安装检查：

```powershell
.\node_modules\.bin\rstest.cmd run
```

## 明天由用户进行的网页验收

本机虚拟环境中的扩展快照尚未升级，因此普通启动可能仍没有新的列表接口。
为了保持安装环境不变，可只让本次 Gateway 进程优先读取仓库源码。
在仓库根目录、沿用之前有效的配置和 `DEER_FLOW_HOME`，由用户执行：

```powershell
.\backend\.venv\Scripts\python.exe -c "import sys; sys.path[:0] = ['extensions/supportops', 'backend']; import uvicorn; uvicorn.run('app.gateway.app:app', host='127.0.0.1', port=8003)"
```

此命令不启用热更新。若 8003 已有旧 Gateway，先在原终端 Ctrl+C 正常停止，
不要另起一个端口不一致的实例。不要变更原运行数据目录，否则可能看不到原记录。

另开一个 PowerShell，在 `frontend` 目录运行已有的 Next.js 程序：

```powershell
$env:DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = 'http://127.0.0.1:8003'
node .\node_modules\next\dist\bin\next dev --webpack --hostname 127.0.0.1 --port 3000
```

这里的变量仅设置在本窗口中，未写入 `.env` 或系统设置；Next.js 将浏览器的
`/api/*` 请求转发给 8003，因此不需要安装 Nginx。两条启动命令尚待用户实跑，
不能把本说明当作服务已启动或登录已成功的证据。

随后打开 `http://127.0.0.1:3000/workspace/supportops`，完成：

1. 登录后查看已有申请；刷新仍能看到原记录。
2. 在聊天中说“请为演示订单 ORD-1002 申请售后，原因是网页验收测试”，
   观察工具结果和模型回复；返回工作台点击刷新，查看本次申请。
3. 修改原因，检查版本加一、状态回到待审批。
4. 核对新内容后批准，再执行建单，检查工单编号和创建时间。
5. 刷新页面后工单仍在；已完成申请不再出现编辑/建单按钮。

接口层的同版本重试、旧版本拒绝、无效订单和故障恢复已有独立证据；
网页实际点击、真实登录和与 Gateway 的联调仍待本次验收，不提前标为完成。
