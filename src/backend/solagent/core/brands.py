"""品牌化 ID 类型定义，利用 NewType 在编译时实现类型层面的不可互换性。

本模块借鉴品牌化类型（Branded Types）模式，为不同语义场景下的字符串 ID
创建独立的类型别名。这样可以在静态类型检查阶段防止 ID 的误用
（例如将 SessionId 传入期望 CallId 的函数），而运行时仍保持普通 str 的零开销特性。

定义的 branded ID 包括：
    SessionId: 会话唯一标识。
    CallId: 单次调用唯一标识。
    AgentId: Agent 实例唯一标识。
    RetryId: 重试操作唯一标识。
"""

from typing import NewType

SessionId = NewType("SessionId", str)
CallId = NewType("CallId", str)
AgentId = NewType("AgentId", str)
RetryId = NewType("RetryId", str)