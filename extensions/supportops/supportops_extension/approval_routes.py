"""Authenticated browser endpoints for reviewing and deciding SupportOps drafts."""

from __future__ import annotations

import asyncio
from typing import Literal

from deerflow_extension_api.auth import arequire_plugin_management
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .action_store import decide_action, get_action, revise_action


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^ORD-[0-9]{4}$")
    reason: str = Field(min_length=1, max_length=300)
    decision: Literal["approve", "reject"]
    revision: int = Field(default=1, ge=1, strict=True)


class ApplicationRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=300)
    revision: int = Field(ge=1, strict=True)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请填写新的售后原因。")
        return value


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/supportops", tags=["SupportOps"])

    async def owner(request: Request, scope: Literal["read", "write"]) -> str:
        try:
            principal = await arequire_plugin_management(
                request, "supportops.order", scope=scope
            )
        except PermissionError:
            raise HTTPException(403, "请先登录并确认具有 SupportOps 权限。") from None
        if (
            principal.is_internal
            or not principal.user_id
            or principal.user_id == "default"
        ):
            raise HTTPException(403, "需要已登录的用户。")
        if getattr(request.state, "auth_source", None) != "session":
            raise HTTPException(403, "请从浏览器登录后提交确认。")
        return principal.user_id

    @router.get("/actions/{action_id}", summary="查看售后申请")
    async def read_application(request: Request, action_id: str):
        user_id = await owner(request, "read")
        try:
            return await asyncio.to_thread(get_action, action_id, user_id)
        except LookupError:
            raise HTTPException(404, "未找到属于你的售后申请。") from None

    @router.post("/actions/{action_id}/decision", summary="批准或拒绝售后申请")
    async def submit_decision(
        request: Request, action_id: str, decision: ApprovalDecision
    ):
        user_id = await owner(request, "write")
        try:
            return await asyncio.to_thread(
                decide_action,
                action_id,
                user_id,
                decision.order_id,
                decision.reason,
                decision.decision,
                decision.revision,
            )
        except LookupError:
            raise HTTPException(404, "未找到属于你的售后申请。") from None
        except ValueError:
            raise HTTPException(
                409, "申请版本或内容与确认内容不一致，或已有其他决定。请重新查看。"
            ) from None

    @router.post("/actions/{action_id}/revision", summary="修改售后原因并重新等待确认")
    async def revise_application(
        request: Request, action_id: str, revision: ApplicationRevision
    ):
        user_id = await owner(request, "write")
        try:
            return await asyncio.to_thread(
                revise_action, action_id, user_id, revision.reason, revision.revision
            )
        except LookupError:
            raise HTTPException(404, "未找到属于你的售后申请。") from None
        except ValueError:
            raise HTTPException(
                409, "申请版本已变化或当前状态无法修改，请重新查看。"
            ) from None

    return router
