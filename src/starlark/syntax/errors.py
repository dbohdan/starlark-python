"""Syntax error types."""

from __future__ import annotations

from dataclasses import dataclass

from .location import Position


@dataclass(frozen=True, slots=True)
class SyntaxError:
    """A syntax error with the position it was reported at."""

    position: Position
    message: str

    def __str__(self) -> str:
        return f"{self.position}: {self.message}"
