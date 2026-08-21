"""Multi-agent team orchestration. Reference: autogen GroupChat, crewAI Crew."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from solagent.agents.base import BaseAgent
from solagent.schema.agent import AgentConfig, AgentResult
from solagent.schema.messages import Message


@dataclass
class TeamAgent:
    name: str
    config: AgentConfig
    provider: Any
    description: str = ""


class TeamRunner:
    """Multi-agent team runner. Reference: autogen Team, crewAI Crew."""
    
    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._results: dict[str, AgentResult] = {}
    
    def add_agent(self, name: str, agent: BaseAgent) -> None:
        self._agents[name] = agent
    
    async def run_sequential(self, tasks: list[dict[str, str]]) -> dict[str, AgentResult]:
        """Run agents sequentially, each agent receives previous agent's output. Reference: crewAI sequential process."""
        results = {}
        prev_output = ""
        for task in tasks:
            agent_name = task.get("agent", "")
            if agent_name not in self._agents:
                continue
            agent = self._agents[agent_name]
            task_text = task.get("task", "")
            if prev_output:
                task_text = f"{task_text}\n\nPrevious result:\n{prev_output}"
            agent._ctx.messages = [Message.user(task_text)]
            result = await agent.run()
            results[agent_name] = result
            prev_output = result.content
        self._results.update(results)
        return results
    
    async def run_parallel(self, tasks: list[dict[str, str]]) -> dict[str, AgentResult]:
        """Run agents in parallel. Reference: autogen concurrent execution."""
        async def run_one(task):
            agent_name = task.get("agent", "")
            if agent_name in self._agents:
                agent = self._agents[agent_name]
                agent._ctx.messages = [Message.user(task.get("task", ""))]
                return agent_name, await agent.run()
            return agent_name, None
        
        results = await asyncio.gather(*[run_one(t) for t in tasks])
        result_dict = {name: result for name, result in results if result is not None}
        self._results.update(result_dict)
        return result_dict

    async def run_round_robin(self, task: str, rounds: int = 3) -> dict[str, AgentResult]:
        """所有 agent 轮流在同一对话上发言，N 轮后结束。Reference: autogen RoundRobinOrchestrator."""
        shared_messages: list[Message] = [Message.user(task)]
        results = {}
        for r in range(rounds):
            for name, agent in self._agents.items():
                agent._ctx.messages = list(shared_messages)
                result = await agent.run()
                results[f"{name}_r{r}"] = result
                shared_messages.append(Message.assistant(f"[{name}]: {result.content}"))
        return results

    async def run_hierarchical(self, task: str, manager_name: str) -> dict[str, AgentResult]:
        """Manager agent 拆解任务 → 分配 worker → worker 执行 → manager 汇总。
        Reference: crewAI Process.hierarchical + autogen MagenticOneOrchestrator 简化版。
        """
        if manager_name not in self._agents:
            raise ValueError(f"Manager '{manager_name}' not found")
        manager = self._agents[manager_name]
        workers = {n: a for n, a in self._agents.items() if n != manager_name}

        manager._ctx.messages = [Message.user(
            f"Task: {task}\nAvailable workers: {list(workers.keys())}\n"
            "Decide worker assignments. Output JSON array: "
            '[{"worker": "<name>", "subtask": "<desc>"}]'
        )]
        plan_result = await manager.run()
        assignments = self._parse_plan(plan_result.content, list(workers.keys()))

        results: dict[str, AgentResult] = {}
        for a in assignments:
            worker = workers.get(a["worker"])
            if worker:
                worker._ctx.messages = [Message.user(a["subtask"])]
                try:
                    results[a["worker"]] = await worker.run()
                except Exception as e:
                    _logger = logging.getLogger(__name__)
                    _logger.warning("Team agent step failed for %s", a["worker"], exc_info=True)
                    results[a["worker"]] = AgentResult(content=f"Error: {e}", messages=[])

        worker_outputs = "\n".join(f"[{n}]: {r.content}" for n, r in results.items())
        manager._ctx.messages = [Message.user(
            f"Original task: {task}\nWorker outputs:\n{worker_outputs}\nSynthesize final answer."
        )]
        results[f"{manager_name}_final"] = await manager.run()
        return results

    @staticmethod
    def _parse_plan(plan_content: str, worker_names: list[str]) -> list[dict]:
        """解析 manager 输出的 JSON 计划，失败时降级为全任务给第一个 worker。"""
        try:
            assignments = json.loads(plan_content)
            if isinstance(assignments, list) and all("worker" in a and "subtask" in a for a in assignments):
                return assignments
        except (json.JSONDecodeError, TypeError):
            pass
        if worker_names:
            return [{"worker": worker_names[0], "subtask": plan_content}]
        return []

    def get_result(self, agent_name: str) -> AgentResult | None:
        return self._results.get(agent_name)
