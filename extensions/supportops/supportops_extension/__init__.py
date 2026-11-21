"""SupportOps order lookup and after-sales drafts for DeerFlow."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import (
    ModelTool,
    PluginContribution,
    PluginToolResult,
    ToolContext,
)

from .action_store import save_pending_action

_ORDERS: dict[str, dict[str, str]] = {
    "ORD-1001": {
        "status": "配送中",
        "product": "演示测绘设备",
        "after_sales": "可申请物流查询",
    },
    "ORD-1002": {
        "status": "已签收",
        "product": "演示数据服务",
        "after_sales": "可申请售后咨询",
    },
}

_QUERY_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {
            "type": "string",
            "description": "订单号，格式为ORD-加4位数字，例如ORD-1001",
            "pattern": r"^ORD-[0-9]{4}$",
        }
    },
    "required": ["order_id"],
    "additionalProperties": False,
}

_PREPARE_AFTER_SALES_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": _QUERY_ORDER_SCHEMA["properties"]["order_id"],
        "reason": {
            "type": "string",
            "description": "用户提出的售后原因",
            "minLength": 1,
            "maxLength": 300,
        },
    },
    "required": ["order_id", "reason"],
    "additionalProperties": False,
}


async def _query_order(payload: Mapping[str, Any], _context: Any) -> PluginToolResult:
    """Return one fixed demo order without changing state."""
    order_id = str(payload["order_id"]).strip().upper()
    order = _ORDERS.get(order_id)
    if order is None:
        return PluginToolResult(
            content=f"演示数据中未找到订单{order_id}。当前可查询ORD-1001和ORD-1002。",
            artifact={
                "schema": "supportops.order_lookup.v1",
                "data_source": "synthetic_demo",
                "found": False,
                "order_id": order_id,
            },
        )

    content = (
        "以下是本地演示数据，不是真实订单。\n"
        f"订单号：{order_id}\n"
        f"状态：{order['status']}\n"
        f"商品：{order['product']}\n"
        f"售后提示：{order['after_sales']}"
    )
    return PluginToolResult(
        content=content,
        artifact={
            "schema": "supportops.order_lookup.v1",
            "data_source": "synthetic_demo",
            "found": True,
            "order_id": order_id,
            **order,
        },
    )


async def _prepare_after_sales(
    payload: Mapping[str, Any], context: ToolContext
) -> PluginToolResult:
    order_id = payload["order_id"]
    reason = payload["reason"].strip()
    # 发起人和会话编号由宿主提供，工具参数只描述售后申请。
    owner_user_id = context.principal.user_id
    thread_id = context.thread_id
    if owner_user_id in ("", "default") or not thread_id:
        return PluginToolResult(
            "请先登录并在会话中发起售后申请。", {"error": "missing_identity"}
        )
    if order_id not in _ORDERS:
        return PluginToolResult(
            f"演示数据中未找到订单 {order_id}。", {"error": "order_not_found"}
        )
    if not reason:
        return PluginToolResult("请提供售后原因。", {"error": "invalid_reason"})

    # 写入成功后才返回申请编号。SQLite 操作放到工作线程执行。
    action = await asyncio.to_thread(
        save_pending_action, order_id, reason, owner_user_id, thread_id
    )
    return PluginToolResult(
        content=f"已保存演示售后申请，待审批。申请编号：{action['action_id']}\n订单号：{order_id}\n原因：{reason}",
        artifact={
            "schema": "supportops.after_sales_draft.v1",
            "data_source": "synthetic_demo",
            **action,
        },
    )


@extension(api="0.2.9", name="supportops")
def install(registry: Any, config: Mapping[str, Any]) -> None:
    """Register the order lookup and draft preparation tools."""
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Configure SupportOps enabled as a boolean")

    contribution = PluginContribution(
        namespace="supportops.order",
        title="SupportOps order assistant",
        description="Demonstration order lookup and pending after-sales requests.",
        enabled=enabled,
        tools=(
            ModelTool(
                name="query_order",
                description=(
                    "查询固定演示订单的状态。只读，不创建工单，不修改订单。"
                    "必须提供格式为ORD-加4位数字的order_id。"
                ),
                input_schema=_QUERY_ORDER_SCHEMA,
                handler=_query_order,
                response_format="content_and_artifact",
            ),
            ModelTool(
                name="prepare_after_sales",
                description=(
                    "当用户明确要求为演示订单申请售后且提供了原因时，保存一条待审批记录。"
                    "只创建待审批记录，不批准申请或创建工单。订单状态查询请用订单查询工具。"
                ),
                input_schema=_PREPARE_AFTER_SALES_SCHEMA,
                handler=_prepare_after_sales,
                response_format="content_and_artifact",
            ),
        ),
    )
    if registry.plugin(contribution) is not True:
        raise RuntimeError("SupportOps order tool requires the plugin host contract")
    if enabled:
        from .approval_routes import build_router

        registry.routers((build_router(),))


__all__ = ["install"]
