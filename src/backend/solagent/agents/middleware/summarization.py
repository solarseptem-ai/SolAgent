"""Summarization middleware with structured summaries, token budget, and iterative updates.

Reference: Hermes ContextCompressor, AgentScope ReplyBudgetControlMiddleware.
"""
import logging
from solagent.agents.middleware.base import NextFn
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message
from solagent.schema.structured import ConversationSummary

_logger = logging.getLogger(__name__)


class SummarizationMiddleware:
    def __init__(self, provider=None, max_tokens: int = 100_000, trigger_ratio: float = 0.8,
                 reserve_ratio: float = 0.15, keep_first: int = 2,
                 keep_last: int = 4, summary_model: str = "",
                 max_summary_tokens: int = 1024, max_messages: int = 50):
        self._provider = provider
        self.max_tokens = max_tokens
        self.trigger_ratio = trigger_ratio
        self.reserve_ratio = reserve_ratio
        self.keep_first = keep_first
        self.keep_last = keep_last
        self._summary_model = summary_model
        self._max_summary_tokens = max_summary_tokens
        self.max_messages = max_messages
        self._previous_summary: str | None = None

    def set_provider(self, provider) -> None:
        self._provider = provider

    @staticmethod
    def _estimate_tokens(messages: list) -> int:
        total = 0
        for m in messages:
            for block in getattr(m, "content", []):
                if hasattr(block, "text"):
                    total += len(getattr(block, "text", "") or "")
                elif hasattr(block, "content"):
                    total += len(getattr(block, "content", "") or "")
        return total // 4

    def _should_trigger(self, messages: list) -> bool:
        estimated = self._estimate_tokens(messages)
        return estimated > self.trigger_ratio * self.max_tokens

    def _truncate(self, messages: list) -> list:
        kept = list(messages[:self.keep_first])
        if self.keep_last > 0:
            kept.extend(messages[-self.keep_last:])
        return kept

    @staticmethod
    def _format_messages_for_summary(messages: list) -> str:
        lines = []
        for msg in messages:
            role = getattr(msg, "role", "unknown")
            parts = []
            for block in getattr(msg, "content", []):
                bt = getattr(block, "type", "")
                if bt == "text":
                    parts.append(getattr(block, "text", ""))
                elif bt == "tool_call":
                    parts.append(f"[Tool: {getattr(block, 'name', '')}]")
                elif bt == "tool_result":
                    c = getattr(block, "content", "")
                    parts.append(f"[Result: {str(c)[:200]}]")
            text = " ".join(parts)[:500]
            if text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines)

    def _build_summary_prompt(self, previous_summary: str | None = None) -> str:
        base = (
            "Summarize the conversation for context compression. "
            "Output as JSON with these fields:\n"
            '  "task_overview": what is the current task\n'
            '  "current_state": what step are we on\n'
            '  "key_facts": list of important facts discovered\n'
            '  "decisions": list of decisions made\n'
            '  "action_items": list of pending actions\n'
            '  "context_to_preserve": any context that must not be lost\n'
        )
        if previous_summary:
            base += (
                f"\n\n<previous-summary>\n{previous_summary}\n</previous-summary>\n"
                "Summarize the conversation, incorporating the previous summary. "
                "Update fields rather than replacing them entirely."
            )
        return base

    async def _summarize(self, messages: list) -> str | None:
        formatted = self._format_messages_for_summary(messages)
        request = LLMRequest(
            messages=[
                Message.system(self._build_summary_prompt(self._previous_summary)),
                Message.user(f"<conversation>\n{formatted}\n</conversation>"),
            ],
            model=self._summary_model or "",
            temperature=0.0,
            max_tokens=self._max_summary_tokens,
        )
        response = await self._provider.chat(request)
        if not response.content:
            return None
        try:
            summary = ConversationSummary.model_validate_json(response.content)
            return summary.model_dump_json(ensure_ascii=False)
        except Exception:
            return response.content

    async def __call__(self, context: dict, next_fn: NextFn) -> dict:
        messages = context.get("messages", [])
        triggered = False

        if len(messages) > self.max_messages:
            triggered = True
        elif self._should_trigger(messages):
            triggered = True

        if not triggered:
            return await next_fn(context)

        middle = messages[self.keep_first:-self.keep_last] if self.keep_last > 0 else messages[self.keep_first:]
        if not middle:
            return await next_fn(context)

        if self._provider is not None:
            try:
                summary = await self._summarize(middle)
                if summary:
                    kept = list(messages[:self.keep_first])
                    kept.append(Message.system(f"<conversation-summary>\n{summary}\n</conversation-summary>"))
                    if self.keep_last > 0:
                        kept.extend(messages[-self.keep_last:])
                    context["messages"] = kept
                    context["summarized"] = len(middle)
                    self._previous_summary = summary
                    _logger.info("Summarized %d messages (previous summary: %s)",
                                 len(middle), "yes" if self._previous_summary else "no")
                    return await next_fn(context)
            except Exception as e:
                _logger.warning("Summarization failed, falling back to truncation: %s", e)
                context["summarization_error"] = str(e)

        context["messages"] = self._truncate(messages)
        context["summarized"] = len(middle)
        _logger.warning("Truncated %d messages (summarization unavailable)", len(middle))
        return await next_fn(context)