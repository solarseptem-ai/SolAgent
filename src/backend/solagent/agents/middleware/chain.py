"""Middleware chain. Reference: deer-flow middleware chain with @Next/@Prev position decorators."""
from typing import Any

from solagent.agents.middleware.base import Middleware


class MiddlewareChain:
    def __init__(self):
        self._middlewares: list[Middleware] = []
    
    def use(self, middleware: Middleware, position: int | None = None) -> "MiddlewareChain":
        if position is not None:
            self._middlewares.insert(position, middleware)
        else:
            self._middlewares.append(middleware)
        return self
    
    def before(self, target_type: type, middleware: Middleware) -> "MiddlewareChain":
        for i, mw in enumerate(self._middlewares):
            if isinstance(mw, target_type):
                self._middlewares.insert(i, middleware)
                return self
        self._middlewares.append(middleware)
        return self
    
    def after(self, target_type: type, middleware: Middleware) -> "MiddlewareChain":
        for i, mw in enumerate(self._middlewares):
            if isinstance(mw, target_type):
                self._middlewares.insert(i + 1, middleware)
                return self
        self._middlewares.append(middleware)
        return self
    
    async def execute(self, context: Any) -> Any:
        if not self._middlewares:
            return context
        
        async def dispatch(index: int, ctx: Any) -> Any:
            if index >= len(self._middlewares):
                return ctx
            mw = self._middlewares[index]
            async def next_fn(c: Any) -> Any:
                return await dispatch(index + 1, c)
            return await mw(ctx, next_fn)
        
        return await dispatch(0, context)
    
    def inject_provider(self, provider) -> None:
        for mw in self._middlewares:
            if hasattr(mw, 'set_provider'):
                mw.set_provider(provider)
    
    def __len__(self) -> int:
        return len(self._middlewares)