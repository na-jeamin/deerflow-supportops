"""Read-only SupportOps order lookup extension for DeerFlow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import ModelTool, PluginContribution, PluginToolResult

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


@extension(api="0.2.9", name="supportops")
def install(registry: Any, config: Mapping[str, Any]) -> None:
    """Register the read-only SupportOps order tool."""
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Configure SupportOps enabled as a boolean")

    contribution = PluginContribution(
        namespace="supportops.order",
        title="SupportOps order lookup",
        description="Read-only demonstration order lookup for the SupportOps project.",
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
        ),
    )
    if registry.plugin(contribution) is not True:
        raise RuntimeError("SupportOps order tool requires the plugin host contract")


__all__ = ["install"]
