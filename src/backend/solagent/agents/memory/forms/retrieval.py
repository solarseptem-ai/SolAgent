"""Retrieval-based memory. Reference: crewAI vector memory, ragflow ES retrieval."""
class RetrievalMemory:
    def __init__(self, storage=None):
        self._storage = storage

    async def retrieve(self, query: str, top_k: int = 5) -> list:
        if self._storage is None:
            return []
        from solagent.schema.memory import MemoryQuery
        results = await self._storage.search(MemoryQuery(query=query, limit=top_k))
        return [r.record for r in results]