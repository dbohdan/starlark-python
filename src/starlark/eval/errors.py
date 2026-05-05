"""Runtime error types for the evaluator.

`EvalError` is the root type. It carries a list of (location, name) call
frames so we can render Python-style tracebacks at the API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..syntax.location import Position


@dataclass(slots=True)
class CallFrame:
    """One frame in an EvalError stack trace."""

    name: str
    position: Position | None


class EvalError(Exception):
    """Raised by Starlark runtime errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.frames: list[CallFrame] = []

    def push_frame(self, name: str, position: Position | None) -> None:
        self.frames.append(CallFrame(name=name, position=position))

    def __str__(self) -> str:
        if not self.frames:
            return f"Error: {self.message}"
        lines = ["Traceback (most recent call last):"]
        for frame in reversed(self.frames):
            loc = f" at {frame.position}" if frame.position else ""
            lines.append(f"  in {frame.name}{loc}")
        lines.append(f"Error: {self.message}")
        return "\n".join(lines)


def errorf(template: str, *args: object) -> EvalError:
    """Convenience: format-and-raise. Mirrors Starlark.errorf in Java."""
    return EvalError(template % args if args else template)


class ResourceLimitExceeded(EvalError):
    """Base class for runtime resource-limit errors.

    Hosts can `except ResourceLimitExceeded` to distinguish DoS-style
    aborts from normal `EvalError`s while still catching either as
    `EvalError`.
    """


class StepLimitExceeded(ResourceLimitExceeded):
    """Raised when `Thread.steps` exceeds `Thread.max_steps`."""


class AllocLimitExceeded(ResourceLimitExceeded):
    """Raised when `Thread.allocs` exceeds `Thread.max_allocs`."""


__all__ = [
    "AllocLimitExceeded",
    "CallFrame",
    "EvalError",
    "ResourceLimitExceeded",
    "StepLimitExceeded",
    "errorf",
]
