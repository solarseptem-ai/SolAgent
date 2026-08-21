"""solagent - 生产级 AI Agent 框架。

本包是 SolAgent 框架的根入口，提供统一的版本标识。
SolAgent 是一个用于构建、编排和运行 AI Agent 的 Python 框架，
支持多种 Agent 模式（ReAct、DAG、Multi-Agent 等）、LLM  provider 路由、
工具调用、人机协同（HITL）、沙箱执行、知识检索等能力。

典型使用方式：
    import solagent
    from solagent.agents import ReActAgent
    from solagent.llms import LLMFactory

    # SDK 客户端（推荐）
    from solagent.client import SolAgentClient

    async with SolAgentClient(model="gpt-4o") as client:
        result = await client.run("Hello, world!")
"""

__version__ = "0.1.0"