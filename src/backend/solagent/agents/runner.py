"""Agent runner. Orchestrates builder to actually run the agent."""
from solagent.agents.builder import AgentBuilder
from solagent.schema.agent import AgentResult
from solagent.schema.messages import Message


class AgentRunner:
    def __init__(self, builder: AgentBuilder):
        self._builder = builder

    async def run(self, input_text: str) -> AgentResult:
        messages = [Message.user(input_text)]
        return await self._builder.run(messages)