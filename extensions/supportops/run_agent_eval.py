"""SupportOps Agent 15 项任务评估脚本，支持 --dry-run 离线预览请求。

设计说明：
- 用例直接内置为 Python 列表 EVAL_CASES（与 EVAL-CASES.md 一一对应），
  避免解析 Markdown 表格的格式脆弱性，同时支持在 A05 成功后自动衔接 A07-A15 的 action_id 与版本号。
- 认证信息全部从环境变量读取，不在脚本内硬编码任何账号、密码、Cookie 或 Token。
  环境变量：
  - DEERFLOW_BASE_URL：Gateway 地址（如 http://127.0.0.1:8003）
  - DEERFLOW_COOKIE：浏览器会话 Cookie，跑完整套评估需带 CSRF 校验码
  - DEERFLOW_TOKEN：兼容单独传入会话令牌或 PAT，PAT 仅适用于接受 PAT 的接口
  - DEERFLOW_THREAD_ID：聊天评估使用的已有线程 ID
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TIMEOUT_SECONDS = 90
MAX_RESPONSE_PREVIEW_CHARS = 400
REVISED_REASON = "商品损坏"
REVISION_2_APPROVAL = {
    "order_id": "ORD-1001",
    "reason": REVISED_REASON,
    "decision": "approve",
    "revision": 2,
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    scenario: str
    kind: str  # "chat" 或 "api"
    expected: str
    prompt: str | None = None
    endpoint_suffix: str | None = None
    body_template: dict[str, Any] | None = None
    expected_status_code: int | None = None
    requires_pre_approve_rev2: bool = False


# 与 extensions/supportops/EVAL-CASES.md 保持 1-to-1 对齐。
EVAL_CASES: list[EvalCase] = [
    EvalCase(
        case_id="A01",
        scenario="查询存在订单",
        kind="chat",
        prompt="请查询演示订单 ORD-1001 的状态",
        expected="调用 query_order，返回 ORD-1001 状态为配送中（演示测绘设备），不建工单",
    ),
    EvalCase(
        case_id="A02",
        scenario="查询第二个存在订单",
        kind="chat",
        prompt="请查询 ORD-1002 的状态",
        expected="调用 query_order，返回 ORD-1002 状态为已签收（演示数据服务）",
    ),
    EvalCase(
        case_id="A03",
        scenario="查询不存在订单",
        kind="chat",
        prompt="请查询 ORD-9999 的状态",
        expected="调用 query_order，artifact.found=False 并明确提示未找到 ORD-9999",
    ),
    EvalCase(
        case_id="A04",
        scenario="非法订单号格式",
        kind="chat",
        prompt="请查询订单 123",
        expected="TBD（Schema 拒绝非 ORD-4位数字格式；实测模型直接拒绝或报错后提示需用户确认）",
    ),
    EvalCase(
        case_id="A05",
        scenario="正常登记售后",
        kind="chat",
        prompt="请为 ORD-1001 申请售后，原因是物流停滞",
        expected="调用 prepare_after_sales，生成 action_id，status=pending_approval，revision=1",
    ),
    EvalCase(
        case_id="A06",
        scenario="对不存在订单登记",
        kind="chat",
        prompt="请为 ORD-9999 申请售后，原因是测试",
        expected="不写入 SQLite；工具返回 error=order_not_found",
    ),
    EvalCase(
        case_id="A07",
        scenario="批准第 1 版",
        kind="api",
        endpoint_suffix="/decision",
        body_template={
            "order_id": "ORD-1001",
            "reason": "物流停滞",
            "decision": "approve",
            "revision": 1,
        },
        expected_status_code=200,
        expected="HTTP 200，status=approved，revision=1",
    ),
    EvalCase(
        case_id="A08",
        scenario="对已批准申请再拒绝",
        kind="api",
        endpoint_suffix="/decision",
        body_template={
            "order_id": "ORD-1001",
            "reason": "物流停滞",
            "decision": "reject",
            "revision": 1,
        },
        expected_status_code=409,
        expected="HTTP 409，冲突拒绝，状态保持 approved",
    ),
    EvalCase(
        case_id="A09",
        scenario="内容不一致的批准",
        kind="api",
        endpoint_suffix="/decision",
        body_template={
            "order_id": "ORD-1001",
            "reason": "与登记不一致的原因",
            "decision": "approve",
            "revision": 1,
        },
        expected_status_code=409,
        expected="HTTP 409，reason 不一致被拒绝",
    ),
    EvalCase(
        case_id="A10",
        scenario="批准后修改原因",
        kind="api",
        endpoint_suffix="/revision",
        body_template={"reason": REVISED_REASON, "revision": 1},
        expected_status_code=200,
        expected="HTTP 200，revision 升至 2，status 重置为 pending_approval",
    ),
    EvalCase(
        case_id="A11",
        scenario="用旧版本批准",
        kind="api",
        endpoint_suffix="/decision",
        body_template={
            "order_id": "ORD-1001",
            "reason": REVISED_REASON,
            "decision": "approve",
            "revision": 1,
        },
        expected_status_code=409,
        expected="HTTP 409，旧 revision=1 被拒绝",
    ),
    EvalCase(
        case_id="A12",
        scenario="执行未批准申请",
        kind="api",
        endpoint_suffix="/execute",
        body_template={"revision": 2},
        expected_status_code=409,
        expected="HTTP 409，revision=2 尚未批准不可建单",
    ),
    EvalCase(
        case_id="A13",
        scenario="执行已批准申请",
        kind="api",
        endpoint_suffix="/execute",
        body_template={"revision": 2},
        expected_status_code=200,
        requires_pre_approve_rev2=True,
        expected="前置批准 revision=2 后执行，HTTP 200，status=succeeded 并返回 ticket_id",
    ),
    EvalCase(
        case_id="A14",
        scenario="重复执行同一版本",
        kind="api",
        endpoint_suffix="/execute",
        body_template={"revision": 2},
        expected_status_code=200,
        expected="HTTP 200，幂等返回与 A13 相同的 ticket_id",
    ),
    EvalCase(
        case_id="A15",
        scenario="执行旧版本",
        kind="api",
        endpoint_suffix="/execute",
        body_template={"revision": 1},
        expected_status_code=409,
        expected="HTTP 409，旧 revision=1 被版本检查拦截",
    ),
]

API_PREREQUISITES = {
    "A08": "A07",
    "A09": "A07",
    "A10": "A07",
    "A11": "A10",
    "A12": "A10",
    "A13": "A10",
    "A14": "A13",
    "A15": "A13",
}


def truncate_text(text: str, limit: int = MAX_RESPONSE_PREVIEW_CHARS) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def build_chat_payload(prompt: str) -> dict[str, Any]:
    return {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "context": {"model_name": "default", "subagent_enabled": False},
    }


def extract_action_id(response_data: Any) -> str | None:
    """提取**本轮** prepare_after_sales 创建的 action_id。

    只扫描最后一条 human 消息之后的 tool 消息，避免同一会话的历史轮次里
    存在旧申请时取到过期的 action_id（否则 A07-A15 会全部打在旧记录上）。
    """
    turn_messages, error = _latest_turn_messages(response_data)
    if error is not None or turn_messages is None:
        return None
    for msg in reversed(_find_tool_messages(turn_messages, "prepare_after_sales")):
        artifact = msg.get("artifact")
        if isinstance(artifact, dict):
            action_id = artifact.get("action_id")
            if isinstance(action_id, str) and re.fullmatch(
                r"[0-9a-fA-F]{32}", action_id
            ):
                return action_id
    return None


def _matches_tool(msg_name: Any, short_name: str) -> bool:
    if not isinstance(msg_name, str):
        return False
    return msg_name == short_name or msg_name.startswith(
        f"ext_supportops_order_{short_name}_"
    )


def _latest_turn_messages(
    response_data: Any,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(response_data, dict):
        return None, "响应体不是 JSON 对象"
    messages = response_data.get("messages")
    if not isinstance(messages, list):
        return None, "响应体缺少字段 messages 或格式不是列表"
    last_human_idx = -1
    for idx, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("type") == "human":
            last_human_idx = idx
    turn_messages = [m for m in messages[last_human_idx + 1 :] if isinstance(m, dict)]
    return turn_messages, None


def _find_tool_messages(
    turn_messages: list[dict[str, Any]], short_name: str
) -> list[dict[str, Any]]:
    return [
        msg
        for msg in turn_messages
        if msg.get("type") == "tool" and _matches_tool(msg.get("name"), short_name)
    ]


def _judge_query_order(
    turn_messages: list[dict[str, Any]],
    *,
    expected_found: bool,
    expected_order_id: str | None = None,
    expected_status: str | None = None,
) -> tuple[bool, str]:
    tool_msgs = _find_tool_messages(turn_messages, "query_order")
    if not tool_msgs:
        return False, "未调用 query_order 工具（未找到对应 tool 消息）"
    msg = tool_msgs[-1]
    if msg.get("status") == "error":
        return (
            False,
            f"query_order 工具执行报错：status=error, content={truncate_text(str(msg.get('content', '')), 120)}",
        )
    artifact = msg.get("artifact")
    if not isinstance(artifact, dict):
        return False, "query_order 消息缺少字段 artifact"
    if "found" not in artifact:
        return False, "query_order 的 artifact 缺少字段 found"
    found = artifact.get("found")
    if found is not expected_found:
        return False, f"query_order artifact.found={found!r}（期望 {expected_found!r}）"
    if expected_order_id is not None and artifact.get("order_id") != expected_order_id:
        return (
            False,
            f"query_order artifact.order_id={artifact.get('order_id')!r}（期望 {expected_order_id!r}）",
        )
    if expected_status is not None and artifact.get("status") != expected_status:
        return (
            False,
            f"query_order artifact.status={artifact.get('status')!r}（期望 {expected_status!r}）",
        )
    return True, (
        f"已调用 query_order；artifact: found={found}, "
        f"order_id={artifact.get('order_id')}, status={artifact.get('status')}"
    )


def _judge_a04(turn_messages: list[dict[str, Any]]) -> tuple[bool, str]:
    tool_msgs = [m for m in turn_messages if m.get("type") == "tool"]
    ai_msgs = [m for m in turn_messages if m.get("type") == "ai"]
    ai_text = truncate_text(str(ai_msgs[-1].get("content", "")), 200) if ai_msgs else ""
    if tool_msgs:
        last_tool = tool_msgs[-1]
        tool_summary = (
            f"工具={last_tool.get('name')} status={last_tool.get('status')} "
            f"content={truncate_text(str(last_tool.get('content', '')), 120)}"
        )
    else:
        tool_summary = "未调用工具"
    return True, f"A04 观察（结论保持 TBD）：{tool_summary}；回复={ai_text or '（空）'}"


def _judge_a05(turn_messages: list[dict[str, Any]]) -> tuple[bool, str]:
    tool_msgs = _find_tool_messages(turn_messages, "prepare_after_sales")
    if not tool_msgs:
        return False, "未调用 prepare_after_sales 工具（未找到对应 tool 消息）"
    msg = tool_msgs[-1]
    if msg.get("status") == "error":
        return (
            False,
            f"prepare_after_sales 工具执行报错：status=error, content={truncate_text(str(msg.get('content', '')), 120)}",
        )
    artifact = msg.get("artifact")
    if not isinstance(artifact, dict):
        return False, "prepare_after_sales 消息缺少字段 artifact"
    missing = [k for k in ("action_id", "status", "revision") if k not in artifact]
    if missing:
        return False, f"prepare_after_sales 的 artifact 缺少字段 {', '.join(missing)}"
    action_id = artifact.get("action_id")
    status = artifact.get("status")
    revision = artifact.get("revision")
    if (
        not isinstance(action_id, str)
        or not re.fullmatch(r"[0-9a-fA-F]{32}", action_id)
        or status != "pending_approval"
        or type(revision) is not int
        or revision != 1
    ):
        return False, (
            f"prepare_after_sales artifact 不符合预期："
            f"action_id={action_id!r}, status={status!r}, revision={revision!r}"
        )
    return (
        True,
        f"已调用 prepare_after_sales；action_id={action_id}, status={status}, revision={revision}",
    )


def _judge_a06(turn_messages: list[dict[str, Any]]) -> tuple[bool, str]:
    prep_msgs = _find_tool_messages(turn_messages, "prepare_after_sales")
    if prep_msgs:
        msg = prep_msgs[-1]
        if msg.get("status") == "error":
            return False, "prepare_after_sales 工具执行报错，未获得业务拒绝结果"
        artifact = msg.get("artifact")
        if not isinstance(artifact, dict):
            return False, "prepare_after_sales 消息缺少字段 artifact"
        if artifact.get("action_id") or artifact.get("status") == "pending_approval":
            return (
                False,
                f"工具意外返回申请记录：action_id={artifact.get('action_id')!r}",
            )
        if "error" not in artifact:
            return False, "prepare_after_sales 的 artifact 缺少字段 error"
        if artifact.get("error") != "order_not_found":
            return (
                False,
                f"prepare_after_sales artifact.error={artifact.get('error')!r}（期望 'order_not_found'）",
            )
        return True, "售后工具返回 order_not_found，响应中无申请编号"

    query_msgs = _find_tool_messages(turn_messages, "query_order")
    if query_msgs:
        passed, preview = _judge_query_order(
            turn_messages, expected_found=False, expected_order_id="ORD-9999"
        )
        return passed, f"未调用 prepare_after_sales。{preview}"
    return False, "未调用 prepare_after_sales 或 query_order 工具"


_CHAT_JUDGES = {
    "A01": lambda msgs: _judge_query_order(
        msgs,
        expected_found=True,
        expected_order_id="ORD-1001",
        expected_status="配送中",
    ),
    "A02": lambda msgs: _judge_query_order(
        msgs,
        expected_found=True,
        expected_order_id="ORD-1002",
        expected_status="已签收",
    ),
    "A03": lambda msgs: _judge_query_order(
        msgs, expected_found=False, expected_order_id="ORD-9999"
    ),
    "A04": _judge_a04,
    "A05": _judge_a05,
    "A06": _judge_a06,
}


def judge_chat_case(case_id: str, response_data: Any) -> tuple[bool, str]:
    """根据聊天响应中的工具调用与 artifact 判定是否通过，返回 (passed, 证据摘要)。"""
    turn_messages, error = _latest_turn_messages(response_data)
    if error is not None or turn_messages is None:
        return False, error or "缺少字段 messages"
    judge_fn = _CHAT_JUDGES.get(case_id)
    if judge_fn is None:
        return False, f"未定义聊天判定规则的用例：{case_id}"
    return judge_fn(turn_messages)


def _extract_cookie_value(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.strip() == name and value.strip():
            return value.strip()
    return None


def build_headers(
    token: str, csrf_token: str | None, cookie: str | None
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if cookie:
        # AuthMiddleware 对 Authorization 头执行严格的 PAT(dfp_) 优先校验，
        # 带会话 Cookie 时绝不能同时发送 Authorization，否则会 401 或导致 A07-A15 403。
        headers["Cookie"] = cookie
        resolved_csrf = csrf_token or _extract_cookie_value(cookie, "csrf_token")
        if resolved_csrf:
            headers["X-CSRF-Token"] = resolved_csrf
    elif token:
        if token.startswith("dfp_"):
            headers["Authorization"] = f"Bearer {token}"
        else:
            # 兼容仅把浏览器 access_token JWT 填入 DEERFLOW_TOKEN 的写法，按会话 Cookie 发送。
            cookie_parts = [f"access_token={token}"]
            if csrf_token:
                cookie_parts.append(f"csrf_token={csrf_token}")
                headers["X-CSRF-Token"] = csrf_token
            headers["Cookie"] = "; ".join(cookie_parts)
    return headers


def load_runtime_config(dry_run: bool) -> dict[str, str]:
    base_url = os.environ.get("DEERFLOW_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("DEERFLOW_TOKEN", "").strip()
    thread_id = os.environ.get("DEERFLOW_THREAD_ID", "").strip()
    csrf_token = os.environ.get("DEERFLOW_CSRF_TOKEN", "").strip()
    cookie = os.environ.get("DEERFLOW_COOKIE", "").strip()

    if dry_run:
        return {
            "base_url": base_url or "<DEERFLOW_BASE_URL>",
            "token": "***" if token else "<DEERFLOW_TOKEN>",
            "thread_id": thread_id or "<DEERFLOW_THREAD_ID>",
            "csrf_token": "***" if csrf_token else "",
            "cookie": "***" if cookie else "",
        }

    missing = [
        name
        for name, val in [
            ("DEERFLOW_BASE_URL", base_url),
            ("DEERFLOW_THREAD_ID", thread_id),
        ]
        if not val
    ]
    if not cookie and not token:
        missing.append("DEERFLOW_COOKIE（或 DEERFLOW_TOKEN）")
    if missing:
        raise SystemExit(
            f"缺少必需环境变量：{', '.join(missing)}。请先在当前 shell 设置后运行，或使用 --dry-run 预览。"
        )
    return {
        "base_url": base_url,
        "token": token,
        "thread_id": thread_id,
        "csrf_token": csrf_token,
        "cookie": cookie,
    }


def run_dry_run(cfg: dict[str, str], action_id_placeholder: str) -> None:
    print("=== SupportOps Eval Dry-Run（不会发送任何网络请求）===")
    print(f"Base URL : {cfg['base_url']}")
    print(f"Thread ID: {cfg['thread_id']}")
    print(
        "说明：A07-A15 接口在服务端要求浏览器 session + X-CSRF-Token；实际运行需在环境中提供会话凭证。\n"
    )

    for case in EVAL_CASES:
        if case.kind == "chat":
            url = f"{cfg['base_url']}/api/threads/{cfg['thread_id']}/runs/wait"
            payload = build_chat_payload(case.prompt or "")
        else:
            if case.requires_pre_approve_rev2:
                pre_url = f"{cfg['base_url']}/api/supportops/actions/{action_id_placeholder}/decision"
                print(f"[前置步骤 -> {case.case_id}] POST {pre_url}")
                print(f"  Body: {json.dumps(REVISION_2_APPROVAL, ensure_ascii=False)}")
            url = f"{cfg['base_url']}/api/supportops/actions/{action_id_placeholder}{case.endpoint_suffix}"
            payload = case.body_template or {}

        print(f"[{case.case_id}] {case.scenario}")
        print(f"  POST {url}")
        print(f"  Body: {json.dumps(payload, ensure_ascii=False)}")
        print(f"  期望: {case.expected}")


def _check_response_fields(
    response: requests.Response, expected: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    try:
        body = response.json()
    except ValueError:
        return None, "响应不是合法 JSON"
    if not isinstance(body, dict):
        return None, "响应体不是 JSON 对象"
    for field, value in expected.items():
        actual = body.get(field)
        if type(actual) is not type(value) or actual != value:
            return None, f"{field}={actual!r}（期望 {value!r}）"
    return body, ""


def evaluate_live(cfg: dict[str, str], action_id: str | None) -> list[dict[str, Any]]:
    headers = build_headers(
        cfg["token"], cfg["csrf_token"] or None, cfg["cookie"] or None
    )
    results: list[dict[str, Any]] = []
    current_action_id = action_id
    ticket_id_a13: str | None = None
    passed_api_cases: set[str] = set()

    for case in EVAL_CASES:
        started = perf_counter()
        if case.kind == "chat":
            url = f"{cfg['base_url']}/api/threads/{cfg['thread_id']}/runs/wait"
            payload = build_chat_payload(case.prompt or "")
            resp = requests.post(
                url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT_SECONDS
            )
            elapsed = perf_counter() - started
            if not resp.ok:
                preview = f"HTTP {resp.status_code}: {truncate_text(resp.text)}"
                conclusion = "fail"
            else:
                try:
                    response_data = resp.json()
                except ValueError:
                    passed, preview = (
                        False,
                        f"响应不是合法 JSON：{truncate_text(resp.text)}",
                    )
                else:
                    passed, preview = judge_chat_case(case.case_id, response_data)
                    if case.case_id == "A05" and passed:
                        extracted = extract_action_id(response_data)
                        if extracted:
                            current_action_id = extracted
                conclusion = (
                    ("TBD" if case.case_id == "A04" else "pass") if passed else "fail"
                )
            results.append(
                {
                    "id": case.case_id,
                    "scenario": case.scenario,
                    "expected": case.expected,
                    "http_status": resp.status_code,
                    "actual_preview": truncate_text(preview),
                    "elapsed_seconds": round(elapsed, 3),
                    "conclusion": conclusion,
                }
            )
            continue

        prerequisite = API_PREREQUISITES.get(case.case_id)
        skip_reason = None
        if not current_action_id:
            skip_reason = "未从 A05 获取到 action_id，也未传入 --action-id"
        elif prerequisite and prerequisite not in passed_api_cases:
            skip_reason = f"前置用例 {prerequisite} 未通过"
        if skip_reason:
            results.append(
                {
                    "id": case.case_id,
                    "scenario": case.scenario,
                    "expected": case.expected,
                    "http_status": None,
                    "actual_preview": f"跳过：{skip_reason}",
                    "elapsed_seconds": 0.0,
                    "conclusion": "TBD",
                }
            )
            continue

        if case.requires_pre_approve_rev2:
            pre_url = (
                f"{cfg['base_url']}/api/supportops/actions/{current_action_id}/decision"
            )
            approval = requests.post(
                pre_url,
                headers=headers,
                json=REVISION_2_APPROVAL,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            if approval.status_code == 200:
                _, approval_error = _check_response_fields(
                    approval,
                    {
                        "action_id": current_action_id,
                        "status": "approved",
                        "revision": 2,
                    },
                )
            else:
                approval_error = truncate_text(approval.text)
            if approval.status_code != 200 or approval_error:
                results.append(
                    {
                        "id": case.case_id,
                        "scenario": case.scenario,
                        "expected": case.expected,
                        "http_status": None,
                        "actual_preview": f"第 2 版审批验证失败（HTTP {approval.status_code}）：{approval_error}",
                        "elapsed_seconds": round(perf_counter() - started, 3),
                        "conclusion": "fail",
                    }
                )
                continue

        url = f"{cfg['base_url']}/api/supportops/actions/{current_action_id}{case.endpoint_suffix}"
        resp = requests.post(
            url,
            headers=headers,
            json=case.body_template or {},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        elapsed = perf_counter() - started
        preview = truncate_text(resp.text)
        passed = resp.status_code == case.expected_status_code
        expected_fields = {
            "A07": {"status": "approved", "revision": 1},
            "A10": {
                "status": "pending_approval",
                "revision": 2,
                "reason": REVISED_REASON,
            },
            "A13": {"status": "succeeded", "revision": 2},
            "A14": {"status": "succeeded", "revision": 2, "ticket_id": ticket_id_a13},
        }.get(case.case_id)
        if passed and expected_fields is not None:
            body, error = _check_response_fields(
                resp, {"action_id": current_action_id, **expected_fields}
            )
            if body is not None and case.case_id == "A13":
                ticket_id = body.get("ticket_id")
                if isinstance(ticket_id, str) and re.fullmatch(
                    r"[0-9a-fA-F]{32}", ticket_id
                ):
                    ticket_id_a13 = ticket_id
                else:
                    error = "首次建单响应缺少有效工单编号"
            if error:
                passed = False
                preview = truncate_text(f"{error}。响应：{preview}")
        if passed:
            passed_api_cases.add(case.case_id)
        results.append(
            {
                "id": case.case_id,
                "scenario": case.scenario,
                "expected": case.expected,
                "http_status": resp.status_code,
                "actual_preview": preview,
                "elapsed_seconds": round(elapsed, 3),
                "conclusion": "pass" if passed else "fail",
            }
        )
    return results


def save_outputs(results: list[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"EVAL-RESULTS-{stamp}.json"
    md_path = output_dir / f"EVAL-RESULTS-{stamp}.md"

    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# SupportOps Agent 评估结果（{stamp}）",
        "",
        "| ID | 场景 | 期望 | HTTP 状态 | 实际响应摘要 | 耗时(s) | 结论 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        preview = str(row["actual_preview"]).replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {row['scenario']} | {row['expected']} | "
            f"{row['http_status']} | {preview} | {row['elapsed_seconds']} | {row['conclusion']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="SupportOps Agent 15 项任务评估脚本。")
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将要发送的请求，不联网。"
    )
    parser.add_argument(
        "--action-id", help="可选：手动指定已有第 1 版 pending_approval 的 action_id。"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=SCRIPT_DIR, help="结果报告输出目录。"
    )
    args = parser.parse_args()

    cfg = load_runtime_config(args.dry_run)
    if args.dry_run:
        run_dry_run(cfg, args.action_id or "<ACTION_ID_FROM_A05>")
        return

    results = evaluate_live(cfg, args.action_id)
    md_path, json_path = save_outputs(results, args.output_dir)
    print(f"评估完成，已写入：\n- {md_path}\n- {json_path}")


if __name__ == "__main__":
    main()
