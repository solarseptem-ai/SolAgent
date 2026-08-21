"""多 Agent 编排策略插件模块。

提供多种预设的 Agent 协作模式（顺序、并行、轮询、层级、蜂群、委托），
每个模式对应一个 Plugin 实现，可按任务特征选择最合适的编排方式。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

from solagent.plugins import Plugin, PluginEvent
from solagent.schema.agent import AgentResult
from solagent.schema.messages import Message

_logger = logging.getLogger(__name__)


class OrchestrationEvent(PluginEvent):
    """编排事件，用于在编排过程中传递任务与结果。"""
    task: str = ""
    agent_name: str = ""
    result: AgentResult | None = None


class OrchestrationStrategy(Protocol):
    """编排策略协议，所有编排插件需实现 execute 方法。"""
    async def execute(
        self,
        agents: dict[str, Any],
        task: str,
        messages: list[Message] | None = None,
    ) -> dict[str, AgentResult]: ...


class SequentialPlugin(Plugin):
    """顺序编排插件：按字典序依次执行 Agent，前一个的输出作为后一个的上下文。"""
    name = "orchestration_sequential"
    inject = {}

    async def execute(self, agents, task, messages=None):
        """逐个执行 Agent，累积传递结果。

        Args:
            agents: 名称到 Agent 实例的映射。
            task: 初始任务文本。
            messages: 可选消息列表（当前未使用，预留扩展）。

        Returns:
            每个 Agent 的执行结果字典。
        """
        results = {}
        prev_output = ""
        for name, agent in agents.items():
            # 若已有前序输出，则追加到当前任务中
            task_text = f"{task}\n\nPrevious result:\n{prev_output}" if prev_output else task
            agent._ctx.messages = [Message.user(task_text)]
            try:
                result = await agent.run()
                results[name] = result
                prev_output = result.content
            except Exception as e:
                _logger.warning("Sequential agent %s failed: %s", name, e)
                results[name] = AgentResult(content=f"Error: {e}", messages=[])
        return results


class ParallelPlugin(Plugin):
    """并行编排插件：同时启动所有 Agent，独立执行互不阻塞。"""
    name = "orchestration_parallel"
    inject = {}

    async def execute(self, agents, task, messages=None):
        """使用 asyncio.gather 并发执行所有 Agent。"""
        async def run_one(name, agent):
            agent._ctx.messages = [Message.user(task)]
            try:
                return name, await agent.run()
            except Exception as e:
                return name, AgentResult(content=f"Error: {e}", messages=[])

        results = await asyncio.gather(*(run_one(n, a) for n, a in agents.items()))
        return {name: result for name, result in results}


class RoundRobinPlugin(Plugin):
    """轮询编排插件：多轮次循环，每轮每个 Agent 依次发言并共享上下文。"""
    name = "orchestration_round_robin"
    inject = {}

    async def execute(self, agents, task, messages=None, rounds=3):
        """执行指定轮数的轮询对话。

        Args:
            rounds: 轮询轮数，默认 3 轮。
        """
        shared = [Message.user(task)]
        results = {}
        for r in range(rounds):
            for name, agent in agents.items():
                agent._ctx.messages = list(shared)
                try:
                    result = await agent.run()
                    results[f"{name}_r{r}"] = result
                    # 将当前 Agent 的输出追加到共享上下文，供后续 Agent 参考
                    shared.append(Message.assistant(f"[{name}]: {result.content}"))
                except Exception as e:
                    _logger.warning("RoundRobin agent %s failed: %s", name, e)
        return results


class HierarchicalPlugin(Plugin):
    """层级编排插件：Manager-Worker 模式，由 Manager 分配子任务并汇总结果。"""
    name = "orchestration_hierarchical"
    inject = {}

    async def execute(self, agents, task, messages=None, manager_name="manager"):
        """Manager 制定分配计划，Worker 执行子任务，Manager 最终合成答案。

        Args:
            manager_name: Manager Agent 的名称，默认 "manager"。
        """
        manager = agents.get(manager_name)
        if not manager:
            raise ValueError(f"Manager '{manager_name}' not found")
        workers = {n: a for n, a in agents.items() if n != manager_name}

        # 第一步：Manager 根据任务和可用 Worker 制定 JSON 分配计划
        manager._ctx.messages = [Message.user(
            f"Task: {task}\nAvailable workers: {list(workers.keys())}\n"
            "Decide worker assignments. Output JSON array: "
            '[{"worker": "<name>", "subtask": "<desc>"}]'
        )]
        plan_result = await manager.run()
        assignments = self._parse_plan(plan_result.content, list(workers.keys()))

        # 第二步：按分配计划派发子任务给各 Worker
        results = {}
        for a in assignments:
            worker = workers.get(a["worker"])
            if worker:
                worker._ctx.messages = [Message.user(a["subtask"])]
                try:
                    results[a["worker"]] = await worker.run()
                except Exception as e:
                    results[a["worker"]] = AgentResult(content=f"Error: {e}", messages=[])

        # 第三步：将 Worker 输出汇总回 Manager，请求最终合成答案
        worker_outputs = "\n".join(f"[{n}]: {r.content}" for n, r in results.items())
        manager._ctx.messages = [Message.user(
            f"Original task: {task}\nWorker outputs:\n{worker_outputs}\nSynthesize final answer."
        )]
        results[f"{manager_name}_final"] = await manager.run()
        return results

    @staticmethod
    def _parse_plan(plan_content, worker_names):
        """解析 Manager 返回的 JSON 分配计划；若解析失败则回退到第一个 Worker。"""
        try:
            assignments = json.loads(plan_content)
            if isinstance(assignments, list) and all("worker" in a for a in assignments):
                return assignments
        except (json.JSONDecodeError, TypeError):
            pass
        if worker_names:
            return [{"worker": worker_names[0], "subtask": plan_content}]
        return []


class SwarmPlugin(Plugin):
    """蜂群编排插件：所有 Agent 独立并行执行，过滤掉异常结果。"""
    name = "orchestration_swarm"
    inject = {}

    async def execute(self, agents, task, messages=None):
        """并发执行，return_exceptions=True 避免单个失败导致整体失败。"""
        results = await asyncio.gather(
            *(self._run_one(n, a, task) for n, a in agents.items()),
            return_exceptions=True,
        )
        return {n: r for n, r in zip(agents.keys(), results) if not isinstance(r, Exception)}

    async def _run_one(self, name, agent, task):
        """单个 Agent 的执行包装。"""
        agent._ctx.messages = [Message.user(task)]
        return await agent.run()


class DelegatePlugin(Plugin):
    """委托编排插件：根据关键词匹配将任务委托给特定 Agent。"""
    name = "orchestration_delegate"
    inject = {}

    async def execute(self, agents, task, messages=None, keywords=None):
        """遍历关键词映射表，第一个匹配成功的关键词对应的 Agent 执行任务。

        Args:
            keywords: 关键词到 Agent 名称的映射字典。
        """
        if not keywords:
            return {}
        task_lower = task.lower()
        for keyword, agent_name in keywords.items():
            if keyword.lower() in task_lower and agent_name in agents:
                agent = agents[agent_name]
                agent._ctx.messages = [Message.user(task)]
                result = await agent.run()
                return {agent_name: result}
        return {}