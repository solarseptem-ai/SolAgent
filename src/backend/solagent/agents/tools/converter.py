"""Tool format converter."""
from solagent.agents.tools.defs import ToolDef


class ToolConverter:
    @staticmethod
    def to_openai(tools: list[ToolDef]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.id,
                    "description": t.description,
                    "parameters": t.json_schema,
                },
            }
            for t in tools
        ]

    @staticmethod
    def to_anthropic(tools: list[ToolDef]) -> list[dict]:
        return [
            {
                "name": t.id,
                "description": t.description,
                "input_schema": t.json_schema,
            }
            for t in tools
        ]