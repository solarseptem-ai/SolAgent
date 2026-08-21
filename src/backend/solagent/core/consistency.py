"""会话一致性校验模块，确保模型可见消息与持久化日志严格对齐。

本模块提供一致性断言工具，用于调试和严格模式下验证 Agent 的内存状态
与事件日志派生状态的一致性，防止"先改内存后写日志"导致的数据丢失或错乱。
"""
import os

from solagent.core.session_log import SessionLog
from solagent.schema.messages import Message


class SessionConsistencyError(Exception):
    """当模型可见消息与 SessionLog 派生消息不一致时抛出的异常。

    该异常表明存在日志与内存状态不同步的 bug，需要排查事件写入顺序。
    """


def assert_model_visible_is_logged(
    messages: list[Message],
    session_log: SessionLog,
    *,
    debug_only: bool = True,
) -> None:
    """断言：模型看到的每条消息都能在事件日志中找到对应来源。

    校验逻辑：
        1. 比较消息数量是否一致。
        2. 逐条比较消息的序列化内容是否完全相同。

    仅在 debug 模式或 SOLAGENT_STRICT_MODE=1 环境变量下执行，
    避免在生产环境引入不必要的性能开销。

    Args:
        messages: 当前传入模型的消息列表（内存状态）。
        session_log: 持久化会话日志对象。
        debug_only: 为 True 时仅在严格模式下执行校验。

    Raises:
        SessionConsistencyError: 当发现数量不匹配或内容不一致时抛出。
    """
    if debug_only and not os.environ.get("SOLAGENT_STRICT_MODE"):
        return
    # 从事件日志派生出模型应看到的消息列表
    derived = session_log.derive_messages()
    if len(messages) != len(derived):
        raise SessionConsistencyError(
            f"message count mismatch: model-visible={len(messages)}, logged={len(derived)}"
        )
    # 逐条比对消息内容，定位第一次出现差异的位置
    for i, (m, d) in enumerate(zip(messages, derived)):
        if m.model_dump() != d.model_dump():
            raise SessionConsistencyError(
                f"message divergence at index {i}: model-visible={m.role.value}, logged={d.role.value}"
            )