"""Middleware protocol. Reference: deer-flow middleware chain @Next/@Prev decorators."""
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

NextFn = Callable[[Any], Awaitable[Any]]

class Middleware(Protocol):
    """Middleware protocol. Each middleware wraps the next handler."""
    
    async def __call__(self, context: Any, next_fn: NextFn) -> Any: ...