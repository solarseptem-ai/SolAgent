"""Large result persistence. 对标 hermes-agent tool_result_storage 三层防御。"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from solagent.schema.tools import ToolResult


class ToolResultStorage:
    def __init__(self, max_output: int = 8000, max_turn_total: int = 32000):
        self._max_output = max_output
        self._max_turn = max_turn_total
        self._tmp = Path(tempfile.mkdtemp(prefix="solagent_result_"))

    def persist_if_large(self, result: ToolResult) -> ToolResult:
        if len(result.output) <= self._max_output:
            return result
        result_id = f"{result.name}_{hashlib.sha256(result.output.encode()).hexdigest()[:8]}"
        file_path = self._tmp / f"{result_id}.txt"
        file_path.write_text(result.output, encoding="utf-8")
        preview = result.output[:500]
        return result.model_copy(update={
            "output": f"[Large result: {len(result.output)} chars]\n{preview}...\n[Full result saved to: {file_path}]"
        })

    def enforce_turn_budget(self, results: list[ToolResult]) -> list[ToolResult]:
        total = sum(len(r.output) for r in results)
        if total <= self._max_turn:
            return results
        largest_idx = max(range(len(results)), key=lambda i: len(results[i].output))
        results[largest_idx] = self.persist_if_large(results[largest_idx])
        return results

    def cleanup(self):
        import shutil
        if self._tmp.exists():
            shutil.rmtree(self._tmp, ignore_errors=True)
