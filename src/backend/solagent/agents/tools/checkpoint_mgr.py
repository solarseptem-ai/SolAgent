"""Checkpoint manager. 对标 hermes-agent checkpoint_manager per-turn 快照能力。"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileSnapshot:
    files: dict[str, str] = field(default_factory=dict)


@dataclass
class CheckpointEntry:
    id: str
    turn_number: int
    snapshot: FileSnapshot
    reason: str
    timestamp: float


class CheckpointManager:
    def __init__(self, max_checkpoints: int = 20):
        self._checkpoints: list[CheckpointEntry] = []
        self._max = max_checkpoints
        self._last_turn = -1
        self._last_cp: CheckpointEntry | None = None

    async def ensure_checkpoint(self, turn_number: int, reason: str, workspace: str | None = None) -> CheckpointEntry | None:
        if self._last_turn == turn_number:
            return self._last_cp
        self._last_turn = turn_number
        if workspace:
            snapshot = self._snapshot_dir(Path(workspace))
            cp = CheckpointEntry(
                id=f"ckpt_{turn_number}_{int(time.monotonic()*1000)}",
                turn_number=turn_number, snapshot=snapshot,
                reason=reason, timestamp=time.monotonic(),
            )
            self._checkpoints.append(cp)
            self._last_cp = cp
            self._prune()
            return cp
        return None

    async def restore(self, checkpoint_id: str, workspace: str) -> bool:
        cp = next((c for c in self._checkpoints if c.id == checkpoint_id), None)
        if not cp:
            return False
        await self.ensure_checkpoint(self._last_turn + 1, "pre-rollback", workspace)
        self._restore_snapshot(cp.snapshot, Path(workspace))
        return True

    def list_checkpoints(self) -> list[CheckpointEntry]:
        return list(self._checkpoints)

    def _snapshot_dir(self, root: Path) -> FileSnapshot:
        files = {}
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file() and f.stat().st_size < 1024 * 1024:
                    files[str(f.relative_to(root))] = hashlib.sha256(f.read_bytes()).hexdigest()
        return FileSnapshot(files=files)

    def _restore_snapshot(self, snapshot: FileSnapshot, root: Path):
        for rel_path, expected_hash in snapshot.files.items():
            actual = root / rel_path
            if actual.exists():
                actual_hash = hashlib.sha256(actual.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    pass

    def _prune(self):
        while len(self._checkpoints) > self._max:
            self._checkpoints.pop(0)