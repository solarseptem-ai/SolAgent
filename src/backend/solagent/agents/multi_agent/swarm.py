"""Swarm pattern: 扇出单个 task 到所有 agent 并行执行，收集所有结果。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from solagent.schema.messages import Message


class SwarmPattern:
    """所有 agent 并行处理同一 task，互不串联，收集全部结果。

    与 TeamRunner.run_parallel 区别：swarm 输入单个 task 字符串，
    run_parallel 输入任务列表（每个 agent 不同任务）。
    """

    def __init__(self):
        self._agents: list[tuple[str, Any]] = []

    def add_agent(self, name: str, agent) -> SwarmPattern:
        self._agents.append((name, agent))
        return self

    async def execute(self, task: str) -> list[dict]:
        async def _run_one(name, agent):
            agent._ctx.messages = [Message.user(task)]
            try:
                result = await agent.run()
                if result.finish_reason == "error":
                    return {"agent": name, "status": "failed", "error": result.content}
                return {"agent": name, "status": "completed", "output": result.content}
            except Exception as e:
                _logger = logging.getLogger(__name__)
                _logger.warning("Swarm agent step failed for %s", name, exc_info=True)
                return {"agent": name, "status": "failed", "error": str(e)}

        return await asyncio.gather(*[_run_one(n, a) for n, a in self._agents])