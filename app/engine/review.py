"""Bounded, memory-only review history. No document or original value is persisted."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .types import Finding

MAX_HISTORY_BYTES = 4 * 1024**2
MAX_HISTORY_STEPS = 40


def encode(findings: list[Finding]) -> bytes:
    return json.dumps([asdict(item) for item in findings], ensure_ascii=False, separators=(",", ":")).encode()


def decode(snapshot: bytes) -> list[Finding]:
    return [Finding(**{**item, "rects": [tuple(rect) for rect in item["rects"]]}) for item in json.loads(snapshot)]


@dataclass
class ReviewHistory:
    undo: list[bytes] = field(default_factory=list)
    redo: list[bytes] = field(default_factory=list)

    def clear(self) -> None:
        self.undo.clear()
        self.redo.clear()

    def _trim(self) -> None:
        while len(self.undo) + len(self.redo) > MAX_HISTORY_STEPS or sum(map(len, self.undo + self.redo)) > MAX_HISTORY_BYTES:
            (self.undo if self.undo else self.redo).pop(0)

    def record(self, findings: list[Finding]) -> None:
        self.redo.clear()
        self.undo.append(encode(findings))
        self._trim()

    def restore(self, findings: list[Finding], *, redo: bool = False) -> list[Finding] | None:
        source, destination = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if not source:
            return None
        snapshot = source.pop()
        destination.append(encode(findings))
        self._trim()
        return decode(snapshot)
