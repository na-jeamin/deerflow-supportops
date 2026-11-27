# DeerFlow SupportOps 订单与售后审批助手

中文 | [English](README.en.md)

基于字节开源智能体底座 [DeerFlow](https://github.com/bytedance/deer-flow)（上游固定提交 [`c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464)）二次开发的订单查询与受控售后工单系统。

用户可以在原生聊天界面通过自然语言查询演示订单、登记售后草稿，再进入侧边栏 **售后工单（SupportOps）** 工作台核对内容、修改原因、人工审批并幂等创建本地 SQLite 工单。项目聚焦 **AI Agent 落地高风险写操作时的三类核心工程问题**：模型工具权限收窄、审批与执行之间的内容版本一致性，以及并发重试下的事务幂等与故障恢复。

## 为什么这样设计（上游能力与二开边界）

本项目保留 DeerFlow 原有底座能力与开源归属，通过其原生扩展契约做实质性业务增量开发，职责边界清晰可查：

| 层次 | 能力来源 | 具体内容 |
| --- | --- | --- |
| 运行底座 | 复用 DeerFlow 上游 | 模型接入、LangGraph Agent 循环、工具调度、对话检查点持久化、用户登录认证与 CSRF 中间件、原生聊天页面 |
| 业务与安全增量 | 本项目新增 / 改造 | 订单查询与售后草稿原生工具、SQLite 动作台账与乐观锁版本状态机、写锁事务幂等建单、浏览器会话审批路由、Swagger 同源 CSRF 调试修复、原生前端售后工单工作台、离线回归测试与 15 场景评估套件 |

> 界面说明：工作区与登录页已适配 SupportOps 标识并指向本仓库；“关于”页面完整保留 DeerFlow 的上游介绍、来源与致谢。

## 核心架构与状态机流转

为了防止大模型在提示词诱导或理解偏差下直接写入正式业务工单，系统把 **“自然语言意图收集”** 与 **“高风险写操作拍板”** 做了硬隔离：

```text
[原生聊天页]
  ├── 查询订单（如 ORD-1001 / ORD-9999）
  │     └── query_order（只读工具）──> 返回中文文本 content + 结构化 artifact（found / data_source）
  │
  └── 申请售后（如“为 ORD-1002 申请售后，原因是物流停滞”）
        └── prepare_after_sales（草稿工具，禁止模型传用户ID/状态）
              └── 服务端注入 owner_user_id + thread_id ──> SQLite 写入 pending_approval（revision=1）

[SupportOps 售后工作台（需浏览器登录会话 session + 同源 X-CSRF-Token）]
  pending_approval (v1)
    ├── 拒绝（reject）──────────────────────> rejected（终态）
    └── 批准（approve，核对订单/原因/版本）──> approved (v1)
          ├── 修改原因（revise）────────────> pending_approval (v2，旧版批准立即作废，持 v1 操作返 409)
          └── 执行建单（execute，仅接 revision）
                └── BEGIN IMMEDIATE 写锁事务 + tickets.action_id UNIQUE 唯一约束
                      └── succeeded（落地唯一工单；重复执行同版本幂等返回原工单，异常自动回滚）
```

## 核心工程设计与源码索引

| 模块 | 核心机制 | 源码与测试入口 |
| --- | --- | --- |
| 原生插件工具与权限收窄 | Schema 校验订单格式 `^ORD-[0-9]{4}$` 且 `additionalProperties: false`；仅向模型开放只读查单与待审批草稿，申请人与会话 ID 强制从宿主上下文注入，双通道返回 `content` 与 `artifact` | [工具实现](extensions/supportops/supportops_extension/__init__.py) · [工具测试](backend/tests/test_supportops_order_tool.py) |
| 版本化状态机与幂等事务 | 修改原因在同一写事务中递增 `revision` 并重置为 `pending_approval`；建单入口以 `BEGIN IMMEDIATE` 串行化并发写，同事务写入带 `UNIQUE(action_id)` 约束的工单表并更新申请状态；只读接口向下兼容旧表结构 | [存储与状态机](extensions/supportops/supportops_extension/action_store.py) · [状态机与并发测试](backend/tests/test_supportops_approval.py) |
| 浏览器会话鉴权与安全路由 | 审批、改因与建单路由叠加校验插件写权限、非匿名账号、`auth_source == "session"` 与双提交 CSRF，拦截脚本令牌绕过人工界面；单笔查询在 SQL 层绑定归属人防枚举 | [审批路由](extensions/supportops/supportops_extension/approval_routes.py) |
| Swagger 调试与前端工作台 | 修复 `/docs` 页面同源写请求自动携带 `X-CSRF-Token`（服务端校验不降级）；在原生前端新增「售后工单」页面，支持本人列表展示、改因重审、审批与建单闭环 | [Swagger 适配](backend/app/gateway/swagger_docs.py) · [前端工作台](frontend/src/components/workspace/supportops/supportops-page.tsx) |
| 防假通过评估套件 | 针对聊天网关无工具调用或工具内部报错仍返回 HTTP 200 的问题，按最新人类消息隔离多轮历史，逐项核验工具 `artifact`、前置依赖门控与重试工单号一致性 | [15 项用例](extensions/supportops/EVAL-CASES.md) · [评估脚本](extensions/supportops/run_agent_eval.py) · [判定器单测](extensions/supportops/test_judge_chat_case.py) |

## 验证情况与范围边界

- **离线自动化测试**：
  - SupportOps 专属测试：35 项后端 `pytest`（覆盖工具 Schema、越权拦截、改因升版、双线程并发审批/改因/建单及触发器模拟回滚）与 9 项评估判定器 `unittest` 全部通过。
  - 宿主关联回归：后端相关定向组合 179 项通过，前端 351 个文件共 3661 项单元/DOM 测试通过。
- **真实端到端与故障恢复验收**：
  - 真实网页闭环（2026-11-24）：完成聊天登记草稿 → 工作台批准 → 修改原因升至第 2 版并作废旧批准 → 重审建单 → 刷新与重启 Gateway 后完整恢复会话与工单，同步通过 11 项真实 HTTP/SQLite 检查（未登录 401、缺 CSRF 403、旧版 409、重复执行返回同一工单、数据库完整性 `ok`），详见 [网页验收报告](extensions/supportops/ACCEPTANCE-2026-11-24.md)。
  - 故障演练：实测本地查询数据热更新验证（`ORD-1001` 从“已发货”更新为“配送中”）、不存在订单 `ORD-9999` 如实返回 `found: false`，以及 SQLite 独占锁故障下的异常定位、零脏写保护与解锁后重试恢复，详见 [验证记录](extensions/supportops/VALIDATION.md)。
- **明确边界（未宣称已完成）**：
  - 演示订单使用固定本地仿真数据，未对接真实电商生产库；
  - 宿主后端全部 40178 项测试仅完成无冲突收集，未全量执行；
  - 15 项自动化评估脚本已完成 `--dry-run` 与离线单测，在线实跑结果待按 [评估运行手册](extensions/supportops/RUN-EVAL.md) 在本地隔离环境运行后回填。

## 快速开始与评估复现

1. 参考 [DeerFlow 上游启动说明](https://github.com/bytedance/deer-flow/blob/c6a39936954d103f24293bfc165cb40e68d44464/README_zh.md) 准备前后端环境与本机模型配置。
2. 按 [扩展配置与运行说明](extensions/supportops/README.md) 在本地 `config.yaml` 中启用 `supportops` 扩展，并启动 Gateway 与前端服务（不改动现有安装环境的本地源码置顶启动方式见 [VALIDATION.md](extensions/supportops/VALIDATION.md)）。
3. 打开原生聊天界面尝试查询订单（`ORD-1001` / `ORD-9999`）或登记售后申请，再切到侧栏 **售后工单** 体验审批、改因升版与幂等建单；`/docs` 保留作接口调试入口。
4. 如需复核离线测试或执行 15 项端到端评估，可直接运行：

```powershell
# 运行 SupportOps 35 项核心 pytest 与 9 项评估判定器单测
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_supportops_approval.py backend/tests/test_supportops_order_tool.py -q
.\backend\.venv\Scripts\python.exe -m unittest extensions.supportops.test_judge_chat_case -v
```

完整 15 场景评估步骤见 [评估运行手册](extensions/supportops/RUN-EVAL.md)。

## 上游归属与许可

本项目基于 [bytedance/deer-flow](https://github.com/bytedance/deer-flow) 提交 [`c6a399369`](https://github.com/bytedance/deer-flow/commit/c6a39936954d103f24293bfc165cb40e68d44464) 构建，扩展注册参考官方检索扩展范例，完整保留上游代码归属与 [MIT 许可证](LICENSE)。
