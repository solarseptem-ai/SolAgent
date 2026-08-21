"""
端口（Port）聚合导出模块。

定义 SolAgent 与外部系统交互的抽象接口集合，采用端口-适配器模式。
包含：Agent 执行、服务发现、事件发布/订阅、LLM 推理、任务调度、工具调用等端口。
"""
from solagent.ports.agent_port import AgentPort
from solagent.ports.discovery_port import DiscoveryPort
from solagent.ports.event_port import EventPort
from solagent.ports.llm_port import LLMPort
from solagent.ports.task_port import TaskPort
from solagent.ports.tool_port import ToolPort

__all__ = ["AgentPort", "DiscoveryPort", "EventPort", "LLMPort", "TaskPort", "ToolPort"]