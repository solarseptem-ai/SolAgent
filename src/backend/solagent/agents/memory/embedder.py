"""Embedder protocol. Reference: crewAI embedding, hermes-agent MemoryProvider embedding."""
import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...
    @property
    def dimension(self) -> int: ...


class NGramEmbedder:
    """Simple n-gram character embedder. Zero dependencies."""

    def __init__(self, n: int = 3, dimension: int = 256):
        self.n = n
        self._dimension = dimension

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        text_lower = text.lower()
        for i in range(len(text_lower) - self.n + 1):
            ngram = text_lower[i:i + self.n]
            idx = int(hashlib.md5(ngram.encode()).hexdigest(), 16) % self._dimension
            vec[idx] += 1.0
        total = sum(vec) or 1.0
        return [v / total for v in vec]

    @property
    def dimension(self) -> int:
        return self._dimension