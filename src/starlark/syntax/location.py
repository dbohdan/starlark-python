"""Source locations.

A `FileLocations` indexes line starts in a source string so we can convert
character offsets to (line, column) pairs lazily, mirroring
`net.starlark.java.syntax.FileLocations`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """A 1-indexed (line, column) position with a filename. Column is in code points."""

    file: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"


class FileLocations:
    """Maps character offsets in a source buffer to Positions."""

    __slots__ = ("_line_starts", "file")

    def __init__(self, file: str, source: str) -> None:
        self.file = file
        starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                starts.append(i + 1)
        self._line_starts = starts

    def position(self, offset: int) -> Position:
        # Find the largest line_start <= offset.
        idx = bisect_right(self._line_starts, offset) - 1
        if idx < 0:
            idx = 0
        return Position(self.file, idx + 1, offset - self._line_starts[idx] + 1)
