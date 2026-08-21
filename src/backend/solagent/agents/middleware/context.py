"""Dynamic context middleware. Injects current date and memory context."""
from datetime import datetime

from solagent.agents.middleware.base import NextFn


class DynamicContextMiddleware:
    async def __call__(self, context: dict, next_fn: NextFn) -> dict:
        system_reminder = f"<system-reminder>Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</system-reminder>"
        messages = context.get("messages", [])
        from solagent.schema.messages import Message, MessageRole, TextBlock
        reminder = Message(role=MessageRole.USER, content=[TextBlock(type="text", text=system_reminder)])
        context["messages"] = [reminder] + messages
        return await next_fn(context)