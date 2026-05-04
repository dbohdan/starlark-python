"""A Starlark Module: the global environment of one .star file.

Each Module owns a `Mutability`. All mutable values (lists, dicts, sets)
created during execution carry a reference to that mutability. When the
module is frozen, every mutable becomes read-only in O(1).
"""

from __future__ import annotations

from typing import Any

from .mutability import Mutability


class Module:
    """A frozen-able container of module-global bindings."""

    __slots__ = ("globals", "mutability", "name", "predeclared")

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.mutability = Mutability(name)
        self.globals: dict[str, Any] = {}
        self.predeclared: dict[str, Any] = {}

    def freeze(self) -> None:
        """Freezes the module's mutability token, making all owned values read-only."""
        self.mutability.freeze()

    def set(self, name: str, value: Any) -> None:
        self.globals[name] = value

    def get(self, name: str) -> Any:
        return self.globals.get(name)

    def has(self, name: str) -> bool:
        return name in self.globals


__all__ = ["Module"]
