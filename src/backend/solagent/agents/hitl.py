"""人机协同（Human-in-the-Loop）模块。

在 Agent 执行关键操作（如调用敏感工具）前暂停，等待人工审批、修改或拒绝。
支持超时自动拒绝、批量拒绝、待审批队列查询等功能，适用于需要人类监督的高风险 Agent 场景。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC
from enum import Enum
from typing import Any


class HITLDecision(str, Enum):
    """人工审批的决策类型。"""
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


@dataclass
class HITLRequest:
    """人机协同审批请求。

    属性:
        id: 请求唯一标识。
        tool_name: 需要审批的工具名称。
        tool_args: 工具调用的参数。
        message: 向用户展示的审批提示信息。
        severity: 严重程度（normal / warning / critical）。
        created_at: 请求创建时间（ISO 格式）。
    """
    id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    severity: str = "normal"  # normal, warning, critical
    created_at: str = ""


@dataclass
class HITLResponse:
    """用户对审批请求的响应结果。

    属性:
        request_id: 对应请求的 ID。
        decision: 用户的决策（批准/拒绝/修改）。
        modified_args: 若用户修改了参数，此处为修改后的参数。
        reason: 用户给出的原因说明。
    """
    request_id: str
    decision: HITLDecision
    modified_args: dict[str, Any] | None = None
    reason: str = ""


class HITLManager:
    """人机协同管理器，负责暂停 Agent 执行并等待人工审批。

    当 Agent 遇到需要人类确认的操作时，通过 request_approval() 发起异步等待；
    用户（或上层 UI）通过 respond() 回复后，Agent 恢复执行。
    支持启用/禁用总开关，以及超时自动拒绝机制。
    """

    def __init__(self):
        self._pending: dict[str, HITLRequest] = {}
        self._responses: dict[str, asyncio.Future] = {}
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        """HITL 功能是否处于启用状态。"""
        return self._enabled

    def enable(self) -> None:
        """启用 HITL 功能。"""
        self._enabled = True

    def disable(self) -> None:
        """禁用 HITL 功能，禁用后 request_approval 将直接通过。"""
        self._enabled = False

    async def request_approval(self, tool_name: str, tool_args: dict[str, Any], message: str = "", severity: str = "normal", timeout: float | None = None) -> HITLResponse:
        """发起人工审批请求，暂停当前执行直到用户响应或超时。

        参数:
            tool_name: 需要审批的工具名。
            tool_args: 工具调用参数。
            message: 向用户展示的提示信息。
            severity: 严重程度级别。
            timeout: 等待超时秒数，None 表示无限等待。

        返回:
            HITLResponse，若超时则自动返回拒绝决策。
        """
        import uuid
        from datetime import datetime

        req_id = str(uuid.uuid4())
        request = HITLRequest(
            id=req_id, tool_name=tool_name, tool_args=tool_args,
            message=message, severity=severity,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._pending[req_id] = request

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._responses[req_id] = future

        try:
            if timeout is not None:
                return await asyncio.wait_for(future, timeout=timeout)
            return await future
        except TimeoutError:
            return HITLResponse(request_id=req_id, decision=HITLDecision.REJECTED, reason="timeout")
        finally:
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)

    def respond(self, request_id: str, decision: HITLDecision, modified_args: dict[str, Any] | None = None, reason: str = "") -> bool:
        """用户响应指定的待审批请求。

        参数:
            request_id: 请求 ID。
            decision: 用户的审批决策。
            modified_args: 修改后的参数（若决策为 MODIFIED）。
            reason: 拒绝或修改的原因。

        返回:
            True 表示请求存在并成功响应；False 表示请求已过期或不存在。
        """
        if request_id in self._responses:
            self._responses[request_id].set_result(HITLResponse(
                request_id=request_id, decision=decision, modified_args=modified_args, reason=reason,
            ))
            return True
        return False

    def reject_all(self, reason: str = "cancelled") -> int:
        """拒绝所有当前待审批的请求，常用于取消或中断 Agent 执行。

        参数:
            reason: 批量拒绝的原因。

        返回:
            实际被拒绝的请求数量。
        """
        count = 0
        for req_id in list(self._responses.keys()):
            if self.respond(req_id, HITLDecision.REJECTED, reason=reason):
                count += 1
        return count

    def get_pending(self) -> list[HITLRequest]:
        """获取当前所有待审批的请求列表。"""
        return list(self._pending.values())

    def has_pending(self) -> bool:
        """判断是否存在尚未处理的审批请求。"""
        return len(self._pending) > 0