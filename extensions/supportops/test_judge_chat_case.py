"""离线单元测试：验证 run_agent_eval.judge_chat_case 不会在无工具调用或字段缺失时假通过。"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SUPPORT_OPS_DIR = Path(__file__).resolve().parents[0]
if str(SUPPORT_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(SUPPORT_OPS_DIR))

from run_agent_eval import judge_chat_case  # noqa: E402


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
        ok_no_messages, summary_no_messages = judge_chat_case("A01", {"status": "success"})
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


if __name__ == "__main__":
    unittest.main()
