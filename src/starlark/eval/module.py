"""A Starlark Module: the global environment of one .star file.

Each Module owns a `Mutability`. All mutable values (lists, dicts, sets)
created during execution carry a reference to that mutability. When the
module is frozen, every mutable becomes read-only in O(1).
"""

from __future__ import annotations

from typing import Any

from .mutability import Mutability


class Module:
    """A frozen-able container of module-global bindings.

    `thread` is set by `starlark.exec_file` after evaluation finishes so
    hosts can inspect resource-counter state (`thread.steps`,
    `thread.allocs`) without having to drive the lower-level `eval_file`
    API themselves.
    """

    __slots__ = ("globals", "mutability", "name", "predeclared", "thread")

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.mutability = Mutability(name)
        self.globals: dict[str, Any] = {}
        self.predeclared: dict[str, Any] = {}
        # Filled in by exec_file after evaluation; None for modules built
        # outside the public API.
        self.thread: Any = None

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
