"""SupportOps Agent 15 项任务评估脚本（只写不跑；支持 --dry-run 离线预览请求）。

设计说明：
- 用例直接内置为 Python 列表 EVAL_CASES（与 EVAL-CASES.md 一一对应），
  避免解析 Markdown 表格的格式脆弱性，同时支持在 A05 成功后自动衔接 A07-A15 的 action_id 与版本号。
- 认证信息全部从环境变量读取，不在脚本内硬编码任何账号、密码、Cookie 或 Token。
  环境变量：
  - DEERFLOW_BASE_URL：Gateway 地址（如 http://127.0.0.1:8003）
  - DEERFLOW_TOKEN：Bearer Token 或会话凭证（若走会话接口，可配合 DEERFLOW_CSRF_TOKEN / DEERFLOW_COOKIE）
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
        body_template={"reason": "商品损坏", "revision": 1},
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
            "reason": "商品损坏",
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
    """从 runs/wait 返回 JSON 中尽量提取 prepare_after_sales 创建的 action_id。"""
    serialized = json.dumps(response_data, ensure_ascii=False)
    match = re.search(r'"action_id"\s*:\s*"([0-9a-fA-F]{32})"', serialized)
    if match:
        return match.group(1)
    match_text = re.search(r"申请编号[：:]\s*([0-9a-fA-F]{32})", serialized)
    return match_text.group(1) if match_text else None


def build_headers(token: str, csrf_token: str | None, cookie: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    if cookie:
        headers["Cookie"] = cookie
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
            ("DEERFLOW_TOKEN", token),
            ("DEERFLOW_THREAD_ID", thread_id),
        ]
        if not val
    ]
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
    print("说明：A07-A15 接口在服务端要求浏览器 session + X-CSRF-Token；实际运行需在环境中提供会话凭证。\n")

    for case in EVAL_CASES:
        if case.kind == "chat":
            url = f"{cfg['base_url']}/api/threads/{cfg['thread_id']}/runs/wait"
            payload = build_chat_payload(case.prompt or "")
        else:
            if case.requires_pre_approve_rev2:
                pre_url = f"{cfg['base_url']}/api/supportops/actions/{action_id_placeholder}/decision"
                pre_body = {
                    "order_id": "ORD-1001",
                    "reason": "商品损坏",
                    "decision": "approve",
                    "revision": 2,
                }
                print(f"[前置步骤 -> {case.case_id}] POST {pre_url}")
                print(f"  Body: {json.dumps(pre_body, ensure_ascii=False)}")
            url = f"{cfg['base_url']}/api/supportops/actions/{action_id_placeholder}{case.endpoint_suffix}"
            payload = case.body_template or {}

        print(f"[{case.case_id}] {case.scenario}")
        print(f"  POST {url}")
        print(f"  Body: {json.dumps(payload, ensure_ascii=False)}")
        print(f"  期望: {case.expected}")


def evaluate_live(cfg: dict[str, str], action_id: str | None) -> list[dict[str, Any]]:
    headers = build_headers(cfg["token"], cfg["csrf_token"] or None, cfg["cookie"] or None)
    results: list[dict[str, Any]] = []
    current_action_id = action_id
    ticket_id_a13: str | None = None

    for case in EVAL_CASES:
        started = perf_counter()
        if case.kind == "chat":
            url = f"{cfg['base_url']}/api/threads/{cfg['thread_id']}/runs/wait"
            payload = build_chat_payload(case.prompt or "")
            resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT_SECONDS)
            elapsed = perf_counter() - started
            preview = truncate_text(resp.text)
            conclusion = "TBD" if case.case_id == "A04" else ("pass" if resp.ok else "fail")
            if case.case_id == "A05" and resp.ok:
                try:
                    extracted = extract_action_id(resp.json())
                    if extracted:
                        current_action_id = extracted
                except ValueError:
                    pass
            results.append({
                "id": case.case_id,
                "scenario": case.scenario,
                "expected": case.expected,
                "http_status": resp.status_code,
                "actual_preview": preview,
                "elapsed_seconds": round(elapsed, 3),
                "conclusion": conclusion,
            })
            continue

        if not current_action_id:
            results.append({
                "id": case.case_id,
                "scenario": case.scenario,
                "expected": case.expected,
                "http_status": None,
                "actual_preview": "跳过：未从 A05 获取到 action_id，也未传入 --action-id",
                "elapsed_seconds": 0.0,
                "conclusion": "TBD",
            })
            continue

        if case.requires_pre_approve_rev2:
            pre_url = f"{cfg['base_url']}/api/supportops/actions/{current_action_id}/decision"
            pre_body = {
                "order_id": "ORD-1001",
                "reason": "商品损坏",
                "decision": "approve",
                "revision": 2,
            }
            requests.post(pre_url, headers=headers, json=pre_body, timeout=DEFAULT_TIMEOUT_SECONDS)

        url = f"{cfg['base_url']}/api/supportops/actions/{current_action_id}{case.endpoint_suffix}"
        resp = requests.post(
            url, headers=headers, json=case.body_template or {}, timeout=DEFAULT_TIMEOUT_SECONDS
        )
        elapsed = perf_counter() - started
        preview = truncate_text(resp.text)
        passed = resp.status_code == case.expected_status_code
        if case.case_id == "A13" and passed:
            try:
                ticket_id_a13 = resp.json().get("ticket_id")
            except ValueError:
                pass
        if case.case_id == "A14" and passed and ticket_id_a13:
            try:
                passed = resp.json().get("ticket_id") == ticket_id_a13
            except ValueError:
                passed = False
        results.append({
            "id": case.case_id,
            "scenario": case.scenario,
            "expected": case.expected,
            "http_status": resp.status_code,
            "actual_preview": preview,
            "elapsed_seconds": round(elapsed, 3),
            "conclusion": "pass" if passed else "fail",
        })
    return results


def save_outputs(results: list[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"EVAL-RESULTS-{stamp}.json"
    md_path = output_dir / f"EVAL-RESULTS-{stamp}.md"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
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
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的请求，不联网。")
    parser.add_argument("--action-id", help="可选：手动指定已有第 1 版 pending_approval 的 action_id。")
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR, help="结果报告输出目录。")
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
