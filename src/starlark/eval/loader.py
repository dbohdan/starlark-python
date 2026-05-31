"""The `load()` statement: loading symbols from another `.star` file.

The host application provides a `Loader`: a callable that maps a module
path (the first argument to `load(...)`) to a `Module` whose globals can
be imported. Modules are typically cached and frozen by the host.

Example:

    def my_loader(name: str) -> Module:
        if name in cache: return cache[name]
        source = open(name).read()
        m = exec_file(source, filename=name)
        m.freeze()
        cache[name] = m
        return m
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .errors import EvalError
from .module import Module

Loader = Callable[[str], Module]


class FileLoader:
    """A simple file-based loader. Caches imported modules by path."""

    __slots__ = ("_cache", "_exec_file", "_search_paths")

    def __init__(
        self, exec_file: Callable, search_paths: Sequence[str | Path] | None = None
    ) -> None:
        # `exec_file` is starlark.exec_file, passed in to avoid a circular import.
        self._cache: dict[str, Module] = {}
        self._search_paths = list(search_paths) if search_paths else ["."]
        self._exec_file = exec_file

    def __call__(self, name: str) -> Module:
        if name in self._cache:
            return self._cache[name]

        for base in self._search_paths:
            p = Path(base) / name
            if p.is_file():
                source = p.read_text(encoding="utf-8")
                module = self._exec_file(source, filename=name)
                module.freeze()
                self._cache[name] = module
                return module
        raise EvalError(f"cannot load {name!r}: file not found")


def perform_load(
    loader: Loader | None, module_name: str, bindings: Sequence[tuple[str, str]]
) -> dict[str, Any]:
    """Resolve a load() statement against `loader`.

    `bindings` is a list of (local_name, original_name) pairs. Returns the
    dict of bindings to install in the calling module's globals.
    """
    if loader is None:
        raise EvalError("load() not allowed: no loader provided to this thread")
    other = loader(module_name)
    out: dict[str, Any] = {}
    for local_name, original_name in bindings:
        if original_name not in other.globals:
            raise EvalError(f"load: name {original_name!r} not found in module {module_name!r}")
        out[local_name] = other.globals[original_name]
    return out


__all__ = ["FileLoader", "Loader", "perform_load"]
