"""离线单元测试：验证 run_agent_eval 的聊天判定、多轮隔离、鉴权头构造与全流程串联。"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SUPPORT_OPS_DIR = Path(__file__).resolve().parents[0]
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for path in (SUPPORT_OPS_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_agent_eval import (  # noqa: E402
    EVAL_CASES,
    build_headers,
    evaluate_live,
    extract_action_id,
    judge_chat_case,
    load_runtime_config,
    save_outputs,
)


class TestJudgeChatCase(unittest.TestCase):
    def test_query_order_found_true_passes_a01_and_fails_a03(self) -> None:
        resp = {
            "messages": [
                {"type": "human", "content": "请查询演示订单 ORD-1001 的状态"},
                {
                    "type": "tool",
                    "name": "ext_supportops_order_query_order_822d9a950536",
                    "status": "success",
                    "content": "订单号：ORD-1001\n状态：配送中",
                    "artifact": {
                        "found": True,
                        "order_id": "ORD-1001",
                        "status": "配送中",
                    },
                },
            ]
        }
        ok_a01, summary_a01 = judge_chat_case("A01", resp)
        ok_a03, summary_a03 = judge_chat_case("A03", resp)
        self.assertTrue(ok_a01, summary_a01)
        self.assertIn("ORD-1001", summary_a01)
        self.assertFalse(ok_a03)
        self.assertIn("found=True", summary_a03)

    def test_http_200_without_tool_calls_fails_a01_and_a05(self) -> None:
        resp = {
            "messages": [
                {"type": "human", "content": "请查询演示订单 ORD-1001 的状态"},
                {"type": "ai", "content": "好的，订单正在配送中。", "tool_calls": []},
            ]
        }
        ok_a01, summary_a01 = judge_chat_case("A01", resp)
        ok_a05, summary_a05 = judge_chat_case("A05", resp)
        self.assertFalse(ok_a01)
        self.assertIn("query_order", summary_a01)
        self.assertFalse(ok_a05)
        self.assertIn("prepare_after_sales", summary_a05)

    def test_prepare_after_sales_order_not_found_passes_a06_and_fails_a05(self) -> None:
        resp = {
            "messages": [
                {"type": "human", "content": "请为 ORD-9999 申请售后，原因是测试"},
                {
                    "type": "tool",
                    "name": "ext_supportops_order_prepare_after_sales_00a95e091841",
                    "status": "success",
                    "content": "演示数据中未找到订单 ORD-9999。",
                    "artifact": {"error": "order_not_found"},
                },
            ]
        }
        ok_a06, summary_a06 = judge_chat_case("A06", resp)
        ok_a05, summary_a05 = judge_chat_case("A05", resp)
        self.assertTrue(ok_a06, summary_a06)
        self.assertIn("order_not_found", summary_a06)
        self.assertFalse(ok_a05)
        self.assertIn("action_id", summary_a05)

    def test_malformed_response_with_missing_fields_fails_with_field_name(self) -> None:
        ok_no_messages, summary_no_messages = judge_chat_case(
            "A01", {"status": "success"}
        )
        self.assertFalse(ok_no_messages)
        self.assertIn("messages", summary_no_messages)

        ok_no_artifact, summary_no_artifact = judge_chat_case(
            "A01",
            {
                "messages": [
                    {"type": "tool", "name": "query_order", "status": "success"},
                ]
            },
        )
        self.assertFalse(ok_no_artifact)
        self.assertIn("artifact", summary_no_artifact)

    def test_multi_turn_history_is_isolated_for_judge_and_extract_action_id(
        self,
    ) -> None:
        old_id = "11111111111111111111111111111111"
        new_id = "22222222222222222222222222222222"
        # 上一轮成功，但当前轮（最后一条 human 之后）没有调用任何工具。
        stale_turn_resp = {
            "messages": [
                {"type": "human", "content": "上一轮"},
                {
                    "type": "tool",
                    "name": "ext_supportops_order_query_order_822d9a950536",
                    "status": "success",
                    "artifact": {
                        "found": True,
                        "order_id": "ORD-1001",
                        "status": "配送中",
                    },
                },
                {
                    "type": "tool",
                    "name": "ext_supportops_order_prepare_after_sales_00a95e091841",
                    "status": "success",
                    "artifact": {
                        "action_id": old_id,
                        "status": "pending_approval",
                        "revision": 1,
                    },
                },
                {"type": "human", "content": "当前轮"},
                {"type": "ai", "content": "没有调用工具", "tool_calls": []},
            ]
        }
        ok_a01, _ = judge_chat_case("A01", stale_turn_resp)
        self.assertFalse(ok_a01)
        self.assertIsNone(extract_action_id(stale_turn_resp))

        # 当前轮新建了另一个 action_id，必须返回新编号而不是旧编号。
        updated_resp = {
            "messages": [
                *stale_turn_resp["messages"][:-1],
                {
                    "type": "tool",
                    "name": "ext_supportops_order_prepare_after_sales_00a95e091841",
                    "status": "success",
                    "artifact": {
                        "action_id": new_id,
                        "status": "pending_approval",
                        "revision": 1,
                    },
                },
            ]
        }
        ok_a05, _ = judge_chat_case("A05", updated_resp)
        self.assertTrue(ok_a05)
        self.assertEqual(extract_action_id(updated_resp), new_id)

    def test_a02_a03_a04_and_a06_query_only_paths(self) -> None:
        resp_a02 = {
            "messages": [
                {"type": "human", "content": "查 ORD-1002"},
                {
                    "type": "tool",
                    "name": "query_order",
                    "status": "success",
                    "artifact": {
                        "found": True,
                        "order_id": "ORD-1002",
                        "status": "已签收",
                    },
                },
            ]
        }
        self.assertTrue(judge_chat_case("A02", resp_a02)[0])

        resp_a03 = {
            "messages": [
                {"type": "human", "content": "查 ORD-9999"},
                {
                    "type": "tool",
                    "name": "query_order",
                    "status": "success",
                    "artifact": {"found": False, "order_id": "ORD-9999"},
                },
            ]
        }
        self.assertTrue(judge_chat_case("A03", resp_a03)[0])

        resp_a04 = {
            "messages": [
                {"type": "human", "content": "请查询订单 123"},
                {"type": "ai", "content": "请提供 ORD-加4位数字 格式的订单号。"},
            ]
        }
        ok_a04, summary_a04 = judge_chat_case("A04", resp_a04)
        self.assertTrue(ok_a04)
        self.assertIn("未调用工具", summary_a04)

        # A06 模型先查单发现 found=False 后直接停止，未写入 SQLite，也应判通过。
        self.assertTrue(judge_chat_case("A06", resp_a03)[0])

    def test_build_headers_avoids_bearer_conflict_and_passes_csrf_middleware(
        self,
    ) -> None:
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from app.gateway.csrf_middleware import CSRFMiddleware

        # 即使同时存在 cookie 和非 dfp_ 的 token，也绝不能发 Authorization: Bearer。
        headers = build_headers(
            "jwt.placeholder.value",
            "csrf-123",
            "access_token=jwt.placeholder.value; csrf_token=csrf-123",
        )
        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["X-CSRF-Token"], "csrf-123")
        self.assertIn("access_token=", headers["Cookie"])

        # 若未传 csrf_token 参数但 cookie 里含 csrf_token=，应自动补齐 X-CSRF-Token。
        headers_auto_csrf = build_headers(
            "", None, "access_token=jwt.placeholder; csrf_token=csrf-auto"
        )
        self.assertEqual(headers_auto_csrf["X-CSRF-Token"], "csrf-auto")

        # 只有真 PAT(dfp_) 且无 cookie 时才发 Authorization: Bearer。
        pat_headers = build_headers("dfp_example_pat", None, None)
        self.assertEqual(pat_headers["Authorization"], "Bearer dfp_example_pat")

        # 离线挂载真实 CSRFMiddleware，验证该 headers 能过双提交校验（不报 403）。
        app = FastAPI()
        app.add_middleware(CSRFMiddleware)

        @app.post("/api/supportops/actions/abc/decision")
        async def dummy_decision():
            return {"ok": True}

        with TestClient(app) as client:
            resp = client.post(
                "/api/supportops/actions/abc/decision", headers=headers, json={}
            )
            self.assertEqual(resp.status_code, 200)

        with patch.dict(
            "os.environ",
            {
                "DEERFLOW_BASE_URL": "http://127.0.0.1:8003",
                "DEERFLOW_THREAD_ID": "thread-1",
                "DEERFLOW_COOKIE": "access_token=jwt; csrf_token=csrf",
            },
            clear=True,
        ):
            cfg = load_runtime_config(dry_run=False)
            self.assertEqual(cfg["base_url"], "http://127.0.0.1:8003")

    def test_evaluate_live_15_cases_pipeline_with_mocked_http(self) -> None:
        action_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ticket_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        def make_resp(status_code: int, payload: dict) -> MagicMock:
            resp = MagicMock()
            resp.status_code = status_code
            resp.ok = 200 <= status_code < 300
            resp.json.return_value = payload
            resp.text = str(payload)
            return resp

        scripted = [
            # A01
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a01"},
                        {
                            "type": "tool",
                            "name": "query_order",
                            "status": "success",
                            "artifact": {
                                "found": True,
                                "order_id": "ORD-1001",
                                "status": "配送中",
                            },
                        },
                    ]
                },
            ),
            # A02
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a02"},
                        {
                            "type": "tool",
                            "name": "query_order",
                            "status": "success",
                            "artifact": {
                                "found": True,
                                "order_id": "ORD-1002",
                                "status": "已签收",
                            },
                        },
                    ]
                },
            ),
            # A03
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a03"},
                        {
                            "type": "tool",
                            "name": "query_order",
                            "status": "success",
                            "artifact": {"found": False, "order_id": "ORD-9999"},
                        },
                    ]
                },
            ),
            # A04
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a04"},
                        {"type": "ai", "content": "请提供 ORD-1001 格式"},
                    ]
                },
            ),
            # A05
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a05"},
                        {
                            "type": "tool",
                            "name": "prepare_after_sales",
                            "status": "success",
                            "artifact": {
                                "action_id": action_id,
                                "status": "pending_approval",
                                "revision": 1,
                            },
                        },
                    ]
                },
            ),
            # A06
            make_resp(
                200,
                {
                    "messages": [
                        {"type": "human", "content": "a06"},
                        {
                            "type": "tool",
                            "name": "prepare_after_sales",
                            "status": "success",
                            "artifact": {"error": "order_not_found"},
                        },
                    ]
                },
            ),
            # A07
            make_resp(
                200, {"action_id": action_id, "status": "approved", "revision": 1}
            ),
            # A08
            make_resp(409, {"detail": "conflict"}),
            # A09
            make_resp(409, {"detail": "content changed"}),
            # A10
            make_resp(
                200,
                {
                    "action_id": action_id,
                    "status": "pending_approval",
                    "revision": 2,
                    "reason": "商品损坏",
                },
            ),
            # A11
            make_resp(409, {"detail": "stale revision"}),
            # A12
            make_resp(409, {"detail": "not approved"}),
            # A13 前置批准 rev 2
            make_resp(
                200, {"action_id": action_id, "status": "approved", "revision": 2}
            ),
            # A13
            make_resp(
                200,
                {
                    "action_id": action_id,
                    "status": "succeeded",
                    "ticket_id": ticket_id,
                    "revision": 2,
                },
            ),
            # A14
            make_resp(
                200,
                {
                    "action_id": action_id,
                    "status": "succeeded",
                    "ticket_id": ticket_id,
                    "revision": 2,
                },
            ),
            # A15
            make_resp(409, {"detail": "stale revision"}),
        ]

        cfg = {
            "base_url": "http://127.0.0.1:8003",
            "token": "",
            "thread_id": "thread-1",
            "csrf_token": "csrf-123",
            "cookie": "access_token=jwt; csrf_token=csrf-123",
        }
        with patch("run_agent_eval.requests.post", side_effect=scripted) as mock_post:
            results = evaluate_live(cfg, action_id=None)

        self.assertEqual(mock_post.call_count, 16)
        self.assertEqual(len(results), 15)
        conclusions = {r["id"]: r["conclusion"] for r in results}
        self.assertEqual(conclusions["A04"], "TBD")
        for cid in [f"A{i:02d}" for i in range(1, 16) if i != 4]:
            self.assertEqual(conclusions[cid], "pass", msg=f"{cid} failed: {results}")

        with tempfile.TemporaryDirectory() as tmp:
            md_path, json_path = save_outputs(results, Path(tmp))
            self.assertTrue(md_path.is_file())
            self.assertTrue(json_path.is_file())

    def test_ticket_evaluation_requires_valid_approval_and_matching_tickets(
        self,
    ) -> None:
        action_id = "a" * 32
        ticket_id = "b" * 32
        approval = {"action_id": action_id, "status": "approved", "revision": 2}
        ticket = {
            "action_id": action_id,
            "status": "succeeded",
            "revision": 2,
            "ticket_id": ticket_id,
        }
        cases = [
            case for case in EVAL_CASES if case.case_id in {"A07", "A10", "A13", "A14"}
        ]
        cfg = {
            "base_url": "http://127.0.0.1:8003",
            "token": "",
            "csrf_token": "",
            "cookie": "",
        }
        setup_responses = [
            (200, {**approval, "revision": 1}),
            (200, {**approval, "status": "pending_approval", "reason": "商品损坏"}),
        ]
        scenarios = [
            ("审批冲突", [(409, {})], "fail", "TBD", "HTTP 409"),
            ("审批返回空对象", [(200, {})], "fail", "TBD", "审批验证失败"),
            ("首张工单为空", [(200, approval), (200, {})], "fail", "TBD", "action_id"),
            (
                "缺少工单编号",
                [(200, approval), (200, {**ticket, "ticket_id": ""})],
                "fail",
                "TBD",
                "缺少有效工单编号",
            ),
            (
                "重试返回另一张工单",
                [
                    (200, approval),
                    (200, ticket),
                    (200, {**ticket, "ticket_id": "c" * 32}),
                ],
                "pass",
                "fail",
                "ticket_id",
            ),
            (
                "重试缺少工单编号",
                [(200, approval), (200, ticket), (200, {**ticket, "ticket_id": None})],
                "pass",
                "fail",
                "ticket_id",
            ),
        ]
        for name, steps, first_result, retry_result, detail in scenarios:
            with self.subTest(name):
                responses = [
                    MagicMock(
                        status_code=code, text=str(body), **{"json.return_value": body}
                    )
                    for code, body in [*setup_responses, *steps]
                ]
                with (
                    patch("run_agent_eval.EVAL_CASES", cases),
                    patch(
                        "run_agent_eval.requests.post", side_effect=responses
                    ) as post,
                ):
                    first, retry = evaluate_live(cfg, action_id)[-2:]
                self.assertEqual(post.call_count, len(responses))
                self.assertEqual(first["conclusion"], first_result)
                self.assertEqual(retry["conclusion"], retry_result)
                failure = first if first_result == "fail" else retry
                self.assertIn(detail, failure["actual_preview"])


if __name__ == "__main__":
    unittest.main()
