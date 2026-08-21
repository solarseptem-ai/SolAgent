"""File-based memory. Reference: deer-flow layered memory (user/history/facts)."""
import json
from datetime import UTC, datetime
from pathlib import Path


class FileMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = {"user": {}, "history": {}, "facts": []}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def add_fact(self, content: str, category: str = "general", confidence: float = 0.5) -> None:
        self._data["facts"].append({
            "content": content,
            "category": category,
            "confidence": confidence,
            "created_at": datetime.now(UTC).isoformat(),
        })
        self.save()