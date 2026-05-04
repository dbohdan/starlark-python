"""Syntax error types."""

from __future__ import annotations

from dataclasses import dataclass

from .location import Position


@dataclass(frozen=True, slots=True)
class SyntaxError:
    """A syntax error with the position it was reported at.

    This is intentionally a dataclass record, not an exception type — the
    parser and resolver collect errors into a list rather than raising. Use
    `StarlarkSyntaxException` to raise/aggregate at the API boundary.
    """

    position: Position
    message: str

    def __str__(self) -> str:
        return f"{self.position}: {self.message}"


class StarlarkSyntaxException(Exception):
    """Raised when one or more SyntaxErrors should propagate to the caller."""

    def __init__(self, errors: list[SyntaxError]) -> None:
        super().__init__("; ".join(str(e) for e in errors))
        self.errors = errors
