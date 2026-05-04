"""The `Mutability` token shared by every mutable value in a Module.

Each Module owns one Mutability. Every list, dict, or set created in that
Module carries a reference to it. When the Module is frozen, all mutables
become read-only in O(1).
"""

from __future__ import annotations

from .errors import EvalError


class Mutability:
    """A boolean flag plus a friendly name for error messages."""

    __slots__ = ("frozen", "name")

    def __init__(self, name: str = "") -> None:
        self.frozen = False
        self.name = name

    def freeze(self) -> None:
        self.frozen = True

    def check(self, value_type: str) -> None:
        if self.frozen:
            raise EvalError(f"trying to mutate a frozen {value_type} value")


# Singleton Mutability used for values that are conceptually immutable from
# the start (no Module owns them, e.g. universal-scope predeclared lists).
IMMUTABLE = Mutability("<universe>")
IMMUTABLE.freeze()


__all__ = ["IMMUTABLE", "Mutability"]
