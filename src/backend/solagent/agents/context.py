"""Agent 上下文管理模块。

提供两大核心功能：
1. 工具输出压缩（compress_tool_output）：当工具返回结果过长时，按工具类型保留头部和尾部关键信息，
   中间部分截断并提示省略字符数，避免超出 LLM 上下文窗口。
2. 智能消息裁剪（smart_trim_messages）：在对话历史超过 token 预算时，基于消息重要性评分
   保留系统消息、最近消息和被后续 tool_call 引用的 tool_result，优先从中间删除低重要性消息。

适用于需要长时间多轮交互、工具频繁调用的 Agent 场景。
"""

from __future__ import annotations

import logging
from collections.abc import Collection

from solagent.schema.messages import Message, MessageRole, ToolResultBlock

_logger = logging.getLogger(__name__)

# 工具输出截断的默认参数
TOOL_OUTPUT_MAX_CHARS = 2000
TOOL_OUTPUT_HEAD_RATIO = 0.35
TOOL_OUTPUT_TAIL_RATIO = 0.35

# 按工具名称模式匹配的压缩策略表。
# 模式为工具名子串（不区分大小写匹配），每个策略覆盖默认的 head_ratio / tail_ratio。
_TOOL_COMPRESSION_PROFILES: dict[str, dict[str, float]] = {
    "read": {"head_ratio": 0.60, "tail_ratio": 0.20},          # code: keep imports/defs
    "cat": {"head_ratio": 0.60, "tail_ratio": 0.20},            # same
    "search": {"head_ratio": 0.20, "tail_ratio": 0.60},         # web: keep results
    "grep": {"head_ratio": 0.30, "tail_ratio": 0.40},           # mixed
    "execute": {"head_ratio": 0.15, "tail_ratio": 0.65},        # shell: keep output
    "bash": {"head_ratio": 0.15, "tail_ratio": 0.65},           # same
    "run": {"head_ratio": 0.15, "tail_ratio": 0.65},            # same
}


def _get_compression_profile(tool_name: str) -> dict[str, float]:
    """根据工具名获取对应的压缩策略，未命中时回退到默认策略。"""
    lowered = tool_name.lower()
    for pattern, profile in _TOOL_COMPRESSION_PROFILES.items():
        if pattern in lowered:
            return profile
    return {"head_ratio": TOOL_OUTPUT_HEAD_RATIO, "tail_ratio": TOOL_OUTPUT_TAIL_RATIO}


def compress_tool_output(
    output: str,
    max_chars: int = TOOL_OUTPUT_MAX_CHARS,
    tool_name: str = "",
) -> str:
    """压缩过长的工具输出，保留头部和尾部并在中间插入截断标记。

    根据工具类型选择不同的压缩比例：
    - read / cat：保留更多头部（导入、定义等代码结构）。
    - search：保留更多尾部（搜索结果内容）。
    - execute / bash / run：保留更多尾部（命令执行输出）。
    - 其他：均衡保留头部和尾部（默认 35%/35%）。

    参数:
        output: 原始工具输出文本。
        max_chars: 输出长度上限，超过则触发截断。
        tool_name: 工具名称，用于匹配特定的压缩策略。

    返回:
        若未超过上限则返回原文；否则返回 head + 截断标记 + tail 的形式。
    """
    if len(output) <= max_chars:
        return output
    profile = _get_compression_profile(tool_name)
    head_ratio = profile["head_ratio"]
    tail_ratio = profile["tail_ratio"]
    head_len = int(max_chars * head_ratio)
    tail_len = int(max_chars * tail_ratio)
    omitted = len(output) - head_len - tail_len
    return (
        output[:head_len]
        + f"\n\n…[truncated {omitted} chars]…\n\n"
        + output[-tail_len:]
    )


def compress_tool_result_block(block: ToolResultBlock, tool_name: str = "") -> ToolResultBlock:
    """若工具结果块内容过长，则对其进行压缩并返回新的 ToolResultBlock。"""
    compressed = compress_tool_output(block.content, tool_name=tool_name)
    if compressed is block.content:
        return block
    return ToolResultBlock(
        type=block.type,
        tool_call_id=block.tool_call_id,
        content=compressed,
        is_error=block.is_error,
    )


def _collect_referenced_tool_ids(messages: Collection[Message]) -> set[str]:
    """收集所有被 Assistant 消息中 tool_calls 引用过的 tool_call_id。

    用于智能裁剪时判断哪些 tool_result 消息具有依赖关系，需要优先保留。
    """
    ids: set[str] = set()
    for m in messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            for tc in m.tool_calls:
                ids.add(tc.id)
    return ids


def _estimate_tokens(messages: list[Message]) -> int:
    """粗略估算消息列表的 token 数量，按 1 token ≈ 4 字符计算。

    该估算仅用于触发裁剪阈值判断，不追求精确值。
    """
    total = 0
    for m in messages:
        for block in m.content:
            if hasattr(block, "text"):
                total += len(getattr(block, "text", "") or "")
            elif hasattr(block, "content"):
                total += len(getattr(block, "content", "") or "")
    return total // 4


def _message_importance(
    msg: Message,
    index: int,
    total: int,
    referenced_ids: set[str],
) -> int:
    """计算单条消息的重要性得分，得分越高越优先保留。

    评分规则:
    - system 消息: 1000（始终保留）
    - 最后 2 条消息: 100（当前轮次上下文）
    - 最后 6 条消息: 50（近期历史）
    - 被后续 tool_call 引用的 tool_result: 40（依赖追踪）
    - 普通 tool 消息: 30
    - 带有 tool_calls 的 assistant 消息: 20
    - 其他: 10

    参数:
        msg: 待评分的消息。
        index: 消息在列表中的索引。
        total: 消息总数。
        referenced_ids: 被引用的 tool_call_id 集合。

    返回:
        重要性得分（整数，越高越重要）。
    """
    distance_from_end = total - index
    if msg.role == MessageRole.SYSTEM:
        return 1000
    if distance_from_end <= 2:
        return 100
    if distance_from_end <= 6:
        return 50
    if msg.role == MessageRole.TOOL:
        for block in msg.content:
            if isinstance(block, ToolResultBlock) and block.tool_call_id in referenced_ids:
                return 40
        return 30
    if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
        return 20
    return 10


def _structural_trim(messages: list[Message], keep_first: int, keep_last: int) -> list[Message]:
    """结构性裁剪：仅保留前 N 条和后 M 条非系统消息，系统消息全部保留。

    用于 token 预算极小、无法做复杂评分的极端场景。
    """
    non_system = [m for m in messages if m.role != MessageRole.SYSTEM]
    system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
    if len(non_system) <= keep_first + keep_last:
        return list(messages)
    return system_msgs + non_system[:keep_first] + non_system[-keep_last:]


def _blend_trim(
    messages: list[Message],
    structural: list[Message],
    smart: list[Message],
    max_tokens: int,
    blend_start: int = 200,
    blend_end: int = 2000,
) -> list[Message]:
    """在结构性裁剪和智能评分裁剪之间平滑过渡。

    策略:
    - max_tokens <= blend_start: 完全采用结构性裁剪（保守策略）。
    - max_tokens >= blend_end: 完全采用智能评分裁剪（保留更多上下文）。
    - 中间区间: 按权重混合两种裁剪结果，优先保留两者共同包含的消息，
      再按比例补充差异消息，直到接近目标长度。

    参数:
        messages: 原始完整消息列表。
        structural: 结构性裁剪后的消息列表。
        smart: 智能评分裁剪后的消息列表。
        max_tokens: 当前 token 预算上限。
        blend_start: 纯结构性裁剪的预算阈值下限。
        blend_end: 纯智能裁剪的预算阈值上限。

    返回:
        平滑混合后的消息列表。
    """
    if max_tokens <= blend_start:
        return structural
    if max_tokens >= blend_end:
        return smart

    ratio = (max_tokens - blend_start) / (blend_end - blend_start)

    # Start with intersection (messages in both)
    structural_set = {id(m) for m in structural}
    smart_set = {id(m) for m in smart}
    common = [m for m in smart if id(m) in structural_set]

    # Fill remaining budget proportionally
    smart_only = [m for m in smart if id(m) not in structural_set]
    structural_only = [m for m in structural if id(m) not in smart_set]

    target_len = max(len(common), int(len(structural) + ratio * (len(smart) - len(structural))))
    result = list(common)

    for m in smart_only + structural_only:
        if len(result) >= target_len:
            break
        if id(m) not in {id(r) for r in result}:
            result.append(m)

    # Sort by original position
    orig_pos = {id(m): i for i, m in enumerate(messages)}
    result.sort(key=lambda m: orig_pos.get(id(m), 0))

    return result


def smart_trim_messages(
    messages: list[Message],
    max_tokens: int = 100_000,
    keep_last: int = 6,
    min_keep: int = 4,
) -> list[Message]:
    """智能裁剪消息列表，使其控制在估算的 token 预算内。

    相比旧的暴力保留策略（前 2 + 后 4），本方法：
    - 始终保留所有 system 消息；
    - 追踪 tool_call 与 tool_result 的依赖关系，保留被引用的结果；
    - 使用基于消息角色的重要性评分；
    - 在极小预算和正常预算之间平滑过渡（结构性 vs 智能裁剪）；
    - 优先从中间删除旧消息，最大限度保留当前上下文。

    参数:
        messages: 原始完整消息列表。
        max_tokens: token 预算上限（估算值）。
        keep_last: 始终保留的最近消息数量。
        min_keep: 无论预算如何都至少保留的消息数量。

    返回:
        裁剪后的消息列表。
    """
    if len(messages) <= min_keep:
        return list(messages)

    estimated = _estimate_tokens(messages)
    if estimated <= max_tokens:
        return list(messages)

    # Always compute structural trim (for blending)
    structural = _structural_trim(messages, keep_first=2, keep_last=min(keep_last, max(4, min_keep)))

    system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
    non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

    if len(non_system) <= keep_last:
        return list(messages)

    # Collect dependency references: tool_results cited by later tool_calls
    referenced_ids = _collect_referenced_tool_ids(messages)

    keep_last_msgs = non_system[-keep_last:]
    first_msgs = non_system[:2]
    middle = non_system[2:-keep_last] if len(non_system) > keep_last + 2 else []

    scored = [
        (i, _message_importance(m, i, len(non_system), referenced_ids), m)
        for i, m in enumerate(middle)
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))

    result = list(system_msgs)
    kept_middle = []
    for _, _, msg in scored:
        kept_middle.append(msg)
        current = result + first_msgs + kept_middle + keep_last_msgs
        if _estimate_tokens(current) <= max_tokens and len(current) >= min_keep:
            break

    result.extend(first_msgs)
    result.extend(kept_middle)
    result.extend(keep_last_msgs)

    # Fallback: if budget still exceeded, trim from the middle (skip first_msgs and keep_last)
    while _estimate_tokens(result) > max_tokens and len(result) > min_keep:
        for i, m in enumerate(result):
            if m.role != MessageRole.SYSTEM and m not in first_msgs and m not in keep_last_msgs:
                result.pop(i)
                break
        else:
            for i, m in enumerate(result):
                if m.role != MessageRole.SYSTEM:
                    result.pop(i)
                    break
            else:
                break

    # Smooth blend: structural for tiny budgets, smart for normal
    smart_result = result
    result = _blend_trim(messages, structural, smart_result, max_tokens)

    if len(result) < len(messages):
        _logger.info(
            "Smart trim: %d → %d messages (%d → %d tokens)",
            len(messages), len(result),
            estimated, _estimate_tokens(result),
        )

    return result