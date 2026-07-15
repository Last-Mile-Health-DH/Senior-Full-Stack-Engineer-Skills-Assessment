"""Optional Chainlit step decorator.

The backend test suite does not install or run Chainlit. This wrapper keeps the
same call sites instrumentable in Chainlit while remaining a no-op elsewhere.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

T = TypeVar("T")


def chainlit_step(name: str, step_type: str = "tool") -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                import chainlit as cl  # type: ignore[import-not-found]
                from chainlit.context import context_var  # type: ignore[import-not-found]

                context_var.get()
            except Exception:
                return await fn(*args, **kwargs)

            stepped = cl.step(name=name, type=step_type)(fn)
            return await stepped(*args, **kwargs)

        return wrapper

    return decorator
