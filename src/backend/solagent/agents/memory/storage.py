"""Memory storage. In-memory with optional file persistence. Reference: deer-flow layered memory (user/history/facts), nanobot MemoryStore."""
import json
import logging
from pathlib import Path

from solagent.agents.memory.embedder import Embedder, NGramEmbedder
from solagent.schema.memory import MemoryQuery, MemoryRecord, MemorySearchResult


class MemoryStorage:
    def __init__(self, embedder: Embedder | None = None, file_path: Path | None = None):
        self._records: dict[str, MemoryRecord] = {}
        self._embedder = embedder or NGramEmbedder()
        self._file_path = file_path
        if file_path and file_path.exists():
            self._load()

    async def add(self, record: MemoryRecord) -> None:
        if not record.embedding:
            record.embedding = self._embedder.embed(record.content)
        self._records[record.id] = record
        self._save()

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        query_vec = self._embedder.embed(query.query)
        results = []
        for record in self._records.values():
            if query.categories and record.category not in query.categories:
                continue
            if record.importance < query.min_importance:
                continue
            if not query.include_private and record.private:
                continue
            score = self._cosine_similarity(query_vec, record.embedding)
            results.append(MemorySearchResult(record=record, score=score, match_reason=f"cosine={score:.3f}"))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:query.limit]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = (sum(x * x for x in a)) ** 0.5
        norm_b = (sum(y * y for y in b)) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    async def delete(self, memory_id: str) -> bool:
        if memory_id in self._records:
            del self._records[memory_id]
            self._save()
            return True
        return False

    async def clear(self) -> None:
        self._records.clear()
        self._save()

    async def system_prompt_block(self) -> str:
        return ""

    def _save(self) -> None:
        if self._file_path:
            data = {k: v.model_dump() for k, v in self._records.items()}
            tmp = self._file_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(self._file_path)

    def _load(self) -> None:
        if self._file_path and self._file_path.exists():
            try:
                data = json.loads(self._file_path.read_text())
                for k, v in data.items():
                    self._records[k] = MemoryRecord.model_validate(v)
            except Exception:
                _logger = logging.getLogger(__name__)
                _logger.warning("Memory storage load failed for %s", self._file_path, exc_info=True)