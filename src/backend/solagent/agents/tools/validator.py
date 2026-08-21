"""Tool call argument validation and JSON repair pipeline."""
from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any

_logger = logging.getLogger(__name__)


class ToolArgumentError(Exception):
    """Raised when tool call arguments cannot be repaired."""


def _repair_json(raw: str) -> dict[str, Any]:
    try:
        from json_repair import repair_json
        repaired = repair_json(raw, return_objects=False)
        return json.loads(repaired)
    except ImportError:
        pass
    except Exception:
        _logger.warning("Tool argument JSON repair failed", exc_info=True)
    raise ToolArgumentError("Failed to repair JSON arguments")


def _extract_first_object(raw: str) -> dict[str, Any]:
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return json.loads(raw[start : i + 1])
    raise JSONDecodeError("No complete JSON object", raw, 0)


def parse_and_repair_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse tool call arguments with 4-tier fallback pipeline."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ToolArgumentError("Empty tool call arguments")

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except JSONDecodeError:
        pass

    try:
        return _repair_json(raw)
    except ToolArgumentError:
        pass

    try:
        return _extract_first_object(raw)
    except JSONDecodeError:
        pass

    raise ToolArgumentError(f"Failed to parse tool call arguments: {raw[:200]}")