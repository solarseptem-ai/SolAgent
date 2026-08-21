"""Memory consolidator. Reference: nanobot Consolidator (LLM-driven summarization), crewAI consolidation."""
class Consolidator:
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold

    async def consolidate(self, records: list) -> list:
        if len(records) <= 1:
            return records
        merged = []
        used = set()
        for i, r1 in enumerate(records):
            if i in used:
                continue
            group = [r1]
            used.add(i)
            for j, r2 in enumerate(records):
                if j in used:
                    continue
                if r1.category == r2.category and self._similarity(r1.content, r2.content) >= self.similarity_threshold:
                    group.append(r2)
                    used.add(j)
            if len(group) > 1:
                best = max(group, key=lambda r: r.importance)
                best.metadata["merged_from"] = len(group)
                merged.append(best)
            else:
                merged.append(r1)
        return merged

    def _similarity(self, a: str, b: str) -> float:
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)