"""本地适配器：在同一进程内直接包装核心组件，实现各端口的本地版本。

适用于单机部署或测试场景，无需网络开销即可调用 Agent、LLM、Tool 和 EventBus。
"""
from solagent.adapters.local.agent import LocalAgentAdapter
from solagent.adapters.local.event import LocalEventAdapter
from solagent.adapters.local.llm import LocalLLMAdapter
from solagent.adapters.local.tool import LocalToolAdapter

__all__ = ["LocalAgentAdapter", "LocalEventAdapter", "LocalLLMAdapter", "LocalToolAdapter"]