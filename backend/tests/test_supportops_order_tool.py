"""Offline checks for the native SupportOps order lookup contribution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

EXTENSION_DIR = Path(__file__).resolve().parents[2] / "extensions" / "supportops"
sys.path.insert(0, str(EXTENSION_DIR))

from supportops_extension import _QUERY_ORDER_SCHEMA, _query_order, install  # noqa: E402


@pytest.fixture
def registered_order_tool(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_DIR))

    from deerflow.extensions.loader import ExtensionSpec, load_extensions
    from deerflow.extensions.plugin_tools import build_plugin_tools

    loaded, diagnostics = load_extensions(
        [ExtensionSpec(use="supportops_extension:install", config={"enabled": True})]
    )
    assert diagnostics == []
    (tool,) = build_plugin_tools(loaded)
    return tool


async def _dispatch(tool, payload):
    from deerflow.agents.thread_state import get_thread_state_schema

    graph = StateGraph(get_thread_state_schema("full"))
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    compiled = graph.compile()
    call_id = "supportops-test-call"
    result = await compiled.ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": call_id, "name": tool.name, "args": payload, "type": "tool_call"}],
                )
            ]
        },
        config={"configurable": {"thread_id": "supportops-test-thread"}},
        context={"user_id": "supportops-test-user", "thread_id": "supportops-test-thread"},
    )
    return result["messages"][-1]


class RecordingRegistry:
    def __init__(self) -> None:
        self.contributions = []

    def plugin(self, contribution) -> bool:
        self.contributions.append(contribution)
        return True


def test_extension_registers_one_read_only_order_tool() -> None:
    registry = RecordingRegistry()

    install(registry, {"enabled": True})

    (contribution,) = registry.contributions
    (tool,) = contribution.tools
    assert contribution.namespace == "supportops.order"
    assert tool.name == "query_order"
    assert tool.input_schema == _QUERY_ORDER_SCHEMA
    assert "只读" in tool.description
    assert "创建工单" in tool.description


def test_order_schema_requires_one_supported_order_id() -> None:
    validator = Draft202012Validator(_QUERY_ORDER_SCHEMA)

    assert validator.is_valid({"order_id": "ORD-1001"})
    assert not validator.is_valid({})
    assert not validator.is_valid({"order_id": "ORD-ABC"})
    assert not validator.is_valid({"order_id": "ORD-1001", "write": True})


def test_known_order_returns_readable_and_structured_result() -> None:
    result = asyncio.run(_query_order({"order_id": "ord-1001"}, None))

    assert result.artifact == {
        "schema": "supportops.order_lookup.v1",
        "data_source": "synthetic_demo",
        "found": True,
        "order_id": "ORD-1001",
        "status": "配送中",
        "product": "演示测绘设备",
        "after_sales": "可申请物流查询",
    }
    assert "本地演示数据" in result.content
    assert "状态：配送中" in result.content
    assert "创建工单" not in result.content


def test_unknown_order_returns_explicit_not_found_result() -> None:
    result = asyncio.run(_query_order({"order_id": "ORD-9999"}, None))

    assert result.artifact == {
        "schema": "supportops.order_lookup.v1",
        "data_source": "synthetic_demo",
        "found": False,
        "order_id": "ORD-9999",
    }
    assert "演示数据中未找到订单ORD-9999" in result.content


@pytest.mark.asyncio
async def test_registered_tool_dispatch_returns_order_to_agent(registered_order_tool) -> None:
    message = await _dispatch(registered_order_tool, {"order_id": "ORD-1001"})

    assert isinstance(message, ToolMessage)
    assert message.name == registered_order_tool.name
    assert message.tool_call_id == "supportops-test-call"
    assert message.status == "success"
    assert "状态：配送中" in message.content
    assert message.artifact["found"] is True
    assert message.artifact["order_id"] == "ORD-1001"
    assert message.artifact["status"] == "配送中"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"order_id": "bad-id"}, {"order_id": "ORD-1001", "write": True}])
async def test_registered_tool_dispatch_rejects_invalid_arguments(registered_order_tool, payload) -> None:
    message = await _dispatch(registered_order_tool, payload)

    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "supportops-test-call"
    assert message.status == "error"
