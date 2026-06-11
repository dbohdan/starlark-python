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
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .errors import EvalError
from .module import Module

Loader = Callable[[str], Module]


def _is_escaping_name(name: str) -> bool:
    """Return True if `name` is absolute or contains a `..` segment.

    Checks both POSIX and Windows absolute forms because the package is
    cross-platform: a name that looks relative on POSIX (``C:\\x``,
    ``\\\\host\\share``) can be absolute on Windows, and vice versa.
    """
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute():
        return True
    # `.parts` normalises separators per flavour; check both so a backslash
    # `..` on POSIX (or a forward-slash one on Windows) is still caught.
    return ".." in posix.parts or ".." in windows.parts


class FileLoader:
    """A simple file-based loader. Caches imported modules by requested name.

    Security properties:

    1. **Loads are contained to ``search_paths``.** The requested name is
       resolved against each base directory and accepted only when the
       resolved real path lies inside that base. Absolute names and names
       containing ``..`` segments are rejected up front (for both POSIX
       and Windows path forms). Because containment is checked on the
       *resolved* path, symlinks that point outside a search path are also
       rejected. ``search_paths`` is therefore a genuine trust boundary.
    2. **A loaded file's content is executed as Starlark.** Containment
       bounds *which* files can be loaded, not what they do — every file
       inside a search path is run as code. ``search_paths`` must contain
       only files the host trusts.
    3. **Modules are cached by requested name** and frozen on first load.

    On rejection the raised :class:`EvalError` deliberately does not echo
    the resolved absolute path or any file content, so a host that surfaces
    loader errors to untrusted callers does not leak filesystem layout.
    """

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

        # Defence in depth: reject absolute / `..` names before touching the
        # filesystem. Containment below would catch these too, but rejecting
        # early gives a clear message and avoids resolving attacker paths.
        if _is_escaping_name(name):
            raise EvalError(f"cannot load {name!r}: outside the loader's search paths")

        escaped = False
        for base in self._search_paths:
            base_real = Path(base).resolve()
            candidate = (base_real / name).resolve()
            # Accept only if the resolved candidate is the base itself or sits
            # underneath it. Resolving first means an in-tree symlink whose
            # target escapes the base fails this check.
            if candidate != base_real and not candidate.is_relative_to(base_real):
                # A file that exists but resolves outside the base (e.g. an
                # escaping symlink) is a containment violation, not a miss.
                # Remember it but keep scanning: another base may legitimately
                # contain the same name.
                if candidate.exists():
                    escaped = True
                continue
            if candidate.is_file():
                source = candidate.read_text(encoding="utf-8")
                module = self._exec_file(source, filename=name)
                module.freeze()
                self._cache[name] = module
                return module
        if escaped:
            raise EvalError(f"cannot load {name!r}: outside the loader's search paths")
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
