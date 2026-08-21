"""Manual memory form. Reference: nanobot MEMORY.md/USER.md/SOUL.md."""
from pathlib import Path


class ManualMemory:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def read(self, name: str) -> str:
        p = self.base_dir / f"{name}.md"
        return p.read_text() if p.exists() else ""

    def write(self, name: str, content: str) -> None:
        (self.base_dir / f"{name}.md").write_text(content)

    def list_files(self) -> list[str]:
        return [p.stem for p in self.base_dir.glob("*.md")]