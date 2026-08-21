"""策略插件聚合模块。

提供各类增强型辅助插件，覆盖消息裁剪、错误建议、记忆检索、状态序列化、
压缩触发、学习策略、凭证解析、检查点、沙箱执行、提示模板注册、结果存储、
权限匹配、工具发现等功能。每个插件职责单一，可按需组合使用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Protocol

from solagent.plugins import Plugin, PluginEvent

_logger = logging.getLogger(__name__)


class TokenTrimmingPlugin(Plugin):
    """消息裁剪插件：在上下文窗口接近上限时智能截断历史消息。"""
    name = "token_trimming"
    inject = {}

    async def start(self):
        self.ctx.provide("token_trimming", self)

    def trim(self, messages: list, max_tokens: int = 100000, keep_last: int = 6, min_keep: int = 4) -> list:
        """裁剪消息列表以控制 token 总量，保留最近 keep_last 条。"""
        from solagent.agents.context import smart_trim_messages
        return smart_trim_messages(messages, max_tokens=max_tokens, keep_last=keep_last, min_keep=min_keep)


class ErrorSuggestionsPlugin(Plugin):
    """错误建议插件：根据错误文本关键词匹配，给出人类可读的建议。"""
    name = "error_suggestions"
    inject = {}

    _ERROR_SUGGESTIONS: dict[str, str] = {
        "not found": "The resource was not found. Verify the name/path and try again.",
        "permission denied": "You don't have permission. Consider using read_file instead.",
        "invalid": "The input was invalid. Check the parameter format.",
        "timeout": "The operation timed out. Try with smaller scope or add a timeout.",
        "syntax error": "The code has a syntax error. Check indentation, quotes, brackets.",
        "module not found": "The Python module is not installed. Try `uv pip install <module>`.",
        "connection refused": "The service is not running. Check the port and host.",
        "unknown": "The tool name is not recognized. Check available tools.",
    }

    async def start(self):
        self.ctx.provide("error_suggestions", self)

    def suggest(self, error_text: str) -> str | None:
        """按关键词匹配返回建议文本，无匹配时返回 None。"""
        error_lower = error_text.lower()
        for pattern, suggestion in self._ERROR_SUGGESTIONS.items():
            if pattern in error_lower:
                return suggestion
        return None

    def add_suggestion(self, pattern: str, suggestion: str) -> None:
        """动态添加新的错误关键词-建议映射。"""
        self._ERROR_SUGGESTIONS[pattern] = suggestion


class MemoryRetrievalPlugin(Plugin):
    """记忆检索插件：封装记忆搜索接口，支持自定义 Retriever 或默认 memory 搜索。"""
    name = "memory_retrieval"
    inject = {"memory": None}

    class Retriever(Protocol):
        """自定义检索器协议，需实现 search 方法。"""
        async def search(self, query: str, top_k: int = 5) -> list[dict]: ...

    async def start(self):
        self._retriever: MemoryRetrievalPlugin.Retriever | None = None
        self.ctx.provide("memory_retrieval", self)

    def set_retriever(self, retriever: MemoryRetrievalPlugin.Retriever) -> None:
        """设置自定义检索器，优先于默认 memory 搜索。"""
        self._retriever = retriever

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """执行记忆检索，返回 content 与 score 字典列表。"""
        if self._retriever:
            return await self._retriever.search(query, top_k)
        from solagent.schema.memory import MemoryQuery
        results = await self.ctx.memory.search(MemoryQuery(query=query, limit=top_k))
        return [{"content": r.record.content, "score": r.score} for r in results]


class StateSerializerPlugin(Plugin):
    """状态序列化插件：负责 Agent 会话状态（消息、用量、元数据）的保存与恢复。"""
    name = "state_serializer"
    inject = {}

    async def start(self):
        self.ctx.provide("state_serializer", self)

    def save(self, messages: list, usage: dict, steps: list, metadata: dict) -> dict:
        """将当前会话状态打包为可序列化的字典。"""
        return {
            "messages": [m.model_dump() if hasattr(m, 'model_dump') else m for m in messages],
            "total_usage": usage,
            "steps": len(steps),
            "metadata": metadata,
        }

    def load(self, state: dict) -> tuple[list, dict, dict]:
        """从字典恢复消息列表、TokenUsage 和元数据。"""
        from solagent.schema.messages import Message
        from solagent.schema.llm import TokenUsage
        messages = [Message.model_validate(m) for m in state.get("messages", [])]
        usage = TokenUsage.model_validate(state.get("total_usage", {}))
        metadata = state.get("metadata", {})
        return messages, usage, metadata


class CompressionTriggerPlugin(Plugin):
    """压缩触发插件：根据消息总量估算 token 并判断是否需要进行上下文压缩。"""
    name = "compression_trigger"
    inject = {}

    async def start(self):
        self.ctx.provide("compression_trigger", self)

    def should_compress(self, messages: list, token_ratio: float = 0.8, min_count: int = 20) -> bool:
        """基于字符数估算 token，超过阈值或消息数过多时建议压缩。"""
        total_chars = sum(
            len(str(m)) for m in messages
        )
        estimated_tokens = total_chars // 4
        return estimated_tokens > 100000 * token_ratio or len(messages) > min_count


class LearningStrategyPlugin(Plugin):
    """学习策略插件：聚合多个策略实现任务-结果的持续学习，默认回退到记忆存储。"""
    name = "learning_strategy"
    inject = {"memory": None}

    class Strategy(Protocol):
        """学习策略协议，需实现 learn 方法。"""
        async def learn(self, task: str, result: str, context: dict) -> None: ...

    async def start(self):
        self._strategies: list[LearningStrategyPlugin.Strategy] = []
        self._default = _MemoryLearningStrategy(self.ctx)
        self.ctx.provide("learning_strategy", self)

    def register(self, strategy: LearningStrategyPlugin.Strategy) -> None:
        """注册自定义学习策略。"""
        self._strategies.append(strategy)

    async def learn(self, task: str, result: str, context: dict | None = None) -> None:
        """依次调用所有已注册策略；若无注册策略则使用默认记忆策略。"""
        any_strategy = False
        for s in self._strategies:
            any_strategy = True
            try:
                await s.learn(task, result, context or {})
            except Exception:
                _logger.warning("Learning strategy failed", exc_info=True)
        if not any_strategy:
            await self._default.learn(task, result, context or {})


class _MemoryLearningStrategy:
    """默认学习策略：将任务与结果作为策略类记忆写入记忆系统。"""
    def __init__(self, ctx):
        self._ctx = ctx

    async def learn(self, task: str, result: str, context: dict) -> None:
        from solagent.schema.memory import MemoryCategory, MemoryRecord
        mem = self._ctx.memory
        if mem is None:
            return
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=f"Task: {task}\nResult: {result}",
            category=MemoryCategory.STRATEGY,
        )
        await mem.add(record)


class CredentialPlugin(Plugin):
    """凭证解析插件：支持多 Provider 链式解析密钥，最终回退到环境变量。"""
    name = "credential"
    inject = {}

    class Provider(Protocol):
        """凭证提供者协议，如 Vault、AWS Secrets Manager 等。"""
        async def resolve(self, key_ref: str) -> str | None: ...

    async def start(self):
        self._providers: list[CredentialPlugin.Provider] = []
        self.ctx.provide("credential", self)

    def register(self, provider: CredentialPlugin.Provider) -> None:
        """注册新的凭证提供者。"""
        self._providers.append(provider)

    async def resolve(self, key_ref: str) -> str | None:
        """按注册顺序解析 key_ref，失败则回退到 os.environ。"""
        for p in self._providers:
            value = await p.resolve(key_ref)
            if value:
                return value
        import os
        return os.environ.get(key_ref)


class CheckpointPlugin(Plugin):
    """检查点插件：支持内存/文件双模式保存 Agent 运行状态，支持自动保存最近一次。"""
    name = "checkpoint"
    inject = {}

    async def start(self):
        self._store: dict[str, dict] = {}
        self._base_path: Path | None = None
        self._auto_save = True
        self.ctx.provide("checkpoint", self)
        from solagent.cordis.events import AgentLifecycleEvent
        self.ctx.on(AgentLifecycleEvent, self._on_agent_event, mode="emit")

    async def _on_agent_event(self, event):
        """监听 Agent 生命周期事件，在 agent_end 时自动保存状态。"""
        from solagent.cordis.events import AgentLifecycleEvent
        if not isinstance(event, AgentLifecycleEvent):
            return
        if event.event_type == "agent_end" and self._auto_save:
            await self.save("_last_run", event.data)

    def set_base_path(self, path: Path) -> None:
        """设置持久化目录，并加载该目录下所有 .json 文件到内存缓存。"""
        self._base_path = path
        if path.exists():
            for f in path.glob("*.json"):
                try:
                    self._store[f.stem] = json.loads(f.read_text())
                except Exception:
                    pass

    async def save(self, key: str, data: dict) -> None:
        """保存检查点：先写内存，若配置了 base_path 则同步写入文件。"""
        self._store[key] = data
        if self._base_path:
            (self._base_path / f"{key}.json").write_text(json.dumps(data, indent=2))

    async def load(self, key: str) -> dict | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        """删除内存与文件中的指定检查点。"""
        self._store.pop(key, None)
        if self._base_path:
            p = self._base_path / f"{key}.json"
            if p.exists():
                p.unlink()

    async def list_keys(self) -> list[str]:
        return list(self._store.keys())

    async def restore_last(self) -> dict | None:
        """恢复最近一次自动保存的检查点。"""
        return await self.load("_last_run")


class SandboxProviderPlugin(Plugin):
    """沙箱提供者插件：管理多语言代码执行后端，默认使用本地子进程。"""
    name = "sandbox_provider"
    inject = {}

    class Provider(Protocol):
        """沙箱提供者协议，需实现 execute/start/stop。"""
        async def execute(self, code: str, language: str, timeout: int = 30) -> dict: ...
        async def start(self) -> None: ...
        async def stop(self) -> None: ...

    async def start(self):
        self._providers: dict[str, SandboxProviderPlugin.Provider] = {}
        self._default_provider = _SubprocessSandbox()
        await self._default_provider.start()
        self.ctx.provide("sandbox_provider", self)

    async def stop(self):
        await self._default_provider.stop()

    def register(self, name: str, provider: SandboxProviderPlugin.Provider) -> None:
        """注册命名沙箱提供者。"""
        self._providers[name] = provider

    async def execute(self, code: str, language: str = "python", provider_name: str = "default", timeout: int = 30) -> dict:
        """根据 provider_name 路由到对应沙箱执行代码，未命中则使用默认子进程沙箱。"""
        provider = self._providers.get(provider_name)
        if provider:
            return await provider.execute(code, language, timeout)
        return await self._default_provider.execute(code, language, timeout)


class _SubprocessSandbox:
    """默认子进程沙箱实现：通过 asyncio.create_subprocess_exec 执行代码。"""
    _LANG_MAP = {"python": "python", "python3": "python3", "bash": "bash", "sh": "sh"}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(self, code: str, language: str = "python", timeout: int = 30) -> dict:
        """在子进程中执行代码，捕获 stdout/stderr，支持超时控制。"""
        lang = self._LANG_MAP.get(language, language)
        try:
            proc = await asyncio.create_subprocess_exec(
                lang, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                # 超时后强制终止子进程
                proc.kill()
                await proc.wait()
                return {"output": "", "error": f"Execution timed out after {timeout}s", "exit_code": -1}
            return {
                "output": stdout.decode("utf-8", errors="replace"),
                "error": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        except FileNotFoundError:
            return {"output": "", "error": f"Interpreter '{lang}' not found", "exit_code": -1}


class PromptRegistryPlugin(Plugin):
    """提示模板注册表插件：管理可复用的系统提示模板，支持 format 参数渲染。"""
    name = "prompt_registry"
    inject = {}

    _DEFAULT_TEMPLATES: dict[str, str] = {
        "system.default": "You are {name}, a helpful AI assistant. {instructions}",
        "error.recovery": "An error occurred: {error}. Please try to recover by: {recovery_hint}",
        "tool.retry": "The tool '{tool_name}' failed with: {error}. Please try a different approach.",
        "clarify.ambiguous": "The request '{query}' is ambiguous. Please clarify what you mean.",
        "summarize.session": "Summarize the following conversation:\n{messages}",
        "reflect.plan": "Reflect on the plan execution:\nPlan: {plan}\nResult: {result}\nWhat could be improved?",
    }

    async def start(self):
        self._templates: dict[str, str] = dict(self._DEFAULT_TEMPLATES)
        self.ctx.provide("prompt_registry", self)

    def register(self, name: str, template: str) -> None:
        """注册或覆盖提示模板。"""
        self._templates[name] = template

    def render(self, template_name: str, **kwargs) -> str:
        """渲染指定模板，传入关键字参数替换占位符。"""
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Prompt template '{template_name}' not found")
        return template.format(**kwargs)

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())


class ResultStoragePlugin(Plugin):
    """结果存储插件：支持内存缓存和可插拔后端（如数据库、对象存储）。"""
    name = "result_storage"
    inject = {}

    class Backend(Protocol):
        """存储后端协议。"""
        async def store(self, key: str, data: dict) -> None: ...
        async def retrieve(self, key: str) -> dict | None: ...

    async def start(self):
        self._backend: ResultStoragePlugin.Backend | None = None
        self._store: dict[str, dict] = {}
        self.ctx.provide("result_storage", self)

    def set_backend(self, backend: ResultStoragePlugin.Backend) -> None:
        """设置外部持久化后端。"""
        self._backend = backend

    async def store(self, key: str, data: dict) -> None:
        """优先使用后端存储，无后端则写入内存缓存。"""
        if self._backend:
            await self._backend.store(key, data)
        else:
            self._store[key] = data

    async def retrieve(self, key: str) -> dict | None:
        if self._backend:
            return await self._backend.retrieve(key)
        return self._store.get(key)

    async def list_keys(self) -> list[str]:
        """未配置后端时返回内存缓存的键列表。"""
        if self._backend:
            return []
        return list(self._store.keys())


class PermissionMatcherPlugin(Plugin):
    """权限匹配插件：基于 fnmatch 提供通配符模式匹配能力，用于权限校验。"""
    name = "permission_matcher"
    inject = {}

    class Matcher(Protocol):
        """匹配器协议。"""
        def match(self, pattern: str, value: str) -> bool: ...

    async def start(self):
        import fnmatch

        class _FnmatchMatcher:
            @staticmethod
            def match(pattern: str, value: str) -> bool:
                return fnmatch.fnmatch(value, pattern)

        self._matcher = _FnmatchMatcher()
        self.ctx.provide("permission_matcher", self)

    def set_matcher(self, matcher: PermissionMatcherPlugin.Matcher) -> None:
        """替换默认的 fnmatch 匹配器。"""
        self._matcher = matcher

    def match(self, pattern: str, value: str) -> bool:
        return self._matcher.match(pattern, value)


class ToolDiscoveryPlugin(Plugin):
    """工具发现插件：聚合多个 Discoverer 扫描可用工具，默认扫描 builtins 模块。"""
    name = "tool_discovery"
    inject = {}

    class Discoverer(Protocol):
        """工具发现器协议。"""
        async def discover(self) -> list[dict]: ...

    async def start(self):
        self._discoverers: list[ToolDiscoveryPlugin.Discoverer] = []
        self.ctx.provide("tool_discovery", self)

    def register(self, discoverer: ToolDiscoveryPlugin.Discoverer) -> None:
        """注册自定义工具发现器。"""
        self._discoverers.append(discoverer)

    async def discover(self) -> list[dict]:
        """依次调用所有发现器，无结果时回退到默认 builtins 扫描。"""
        results = []
        for d in self._discoverers:
            try:
                results.extend(await d.discover())
            except Exception:
                _logger.warning("Tool discovery failed", exc_info=True)
        if not results:
            results.extend(await self._default_discover())
        return results

    async def _default_discover(self) -> list[dict]:
        """Scan builtin tool modules for registered ToolDef instances."""
        try:
            from solagent.agents.tools.registry import ToolRegistry
            registry = ToolRegistry()
            registry.auto_discover("solagent.agents.tools.builtins")
            return [
                {"name": name, "description": tool.description if hasattr(tool, "description") else ""}
                for name, tool in registry._tools.items()
            ]
        except Exception:
            return []