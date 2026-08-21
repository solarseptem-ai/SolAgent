"""Code-as-Action mode. Docker sandbox with LocalSandboxProvider fallback."""
from __future__ import annotations

from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent


class CodeAsActionMode(BaseAgent):
    CODE_PROMPT = "Write Python code to solve the task. Output ONLY in ```python block."

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        self._log_step_start(0)
        from solagent.schema.llm import LLMRequest
        from solagent.schema.messages import Message

        timeout = self.config.code_timeout
        code_messages = list(self._ctx.messages) + [Message.user(self.CODE_PROMPT)]
        code_request = LLMRequest(
            messages=code_messages, model=self.config.model,
            temperature=0.0, max_tokens=self.config.max_tokens,
        )

        code_parts: list[str] = []
        async for chunk in self._chat_stream_with_retry(code_request):
            if chunk.content:
                code_parts.append(chunk.content)
                yield AgentStep(iteration=0, content=chunk.content)

        code = "".join(code_parts)
        if "```" in code:
            code = code.split("```python")[1].split("```")[0] if "```python" in code else code.split("```")[1].split("```")[0]
        code = code.strip()

        yield AgentStep(iteration=0, content="\n[Executing code...]")

        output = await self._run_code(code, timeout)

        self._ctx.messages.append(Message.assistant(f"Code output:\n{output}"))
        self._add_step(0, content=output, is_final=True)
        self._log_step_end(0)
        yield AgentStep(iteration=0, content=output, is_final=True, finish_reason="stop")

    async def _run_code(self, code: str, timeout: int) -> str:
        try:
            from solagent.sandbox.backends.docker import DockerSandboxProvider
            from solagent.sandbox.manager import SandboxManager
            sandbox = SandboxManager()
            provider = DockerSandboxProvider()
            sandbox.register("code-as-action", provider)
            await provider.start()
            try:
                result = await sandbox.execute("code-as-action", code, language="python", timeout=timeout)
                return self._format_result(result, timeout)
            finally:
                await provider.stop()
        except (ImportError, ModuleNotFoundError):
            pass

        from solagent.sandbox.backends.local import LocalSandboxProvider
        provider = LocalSandboxProvider(memory_limit_mb=256, cpu_timeout=timeout)
        await provider.start()
        try:
            result = await provider.execute(code, language="python", timeout=timeout)
            return self._format_result(result, timeout)
        finally:
            await provider.stop()

    def _format_result(self, result, timeout: int) -> str:
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.exit_code != 0:
            output += f"\n[exit code: {result.exit_code}]"
        if result.is_timeout:
            output += f"\n[timeout after {timeout}s]"
        return output