"""FastAPI 应用主模块：创建并配置 SolarSeptem Agent HTTP API 服务。

提供以下核心能力：
- Agent 运行（同步 / SSE 流式）
- 健康检查与系统指标
- 配置查询
- 学习系统（经验、策略、评分）管理
- 静态文件服务

启动时会自动加载配置、注册 LLM 提供商并初始化记忆系统。
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from solagent.agents.builder import AgentBuilder
from solagent.config import ConfigLoader, register_providers_from_config
from solagent.config.config_model import AgentConfigBlock
from solagent.core.logging import get_trace_id, set_trace_id
from solagent.llms.factory import LLMFactory
from solagent.llms.providers.registry import get_registry
from solagent.prompts.registry import get_prompt_registry
from solagent.schema.agent import AgentConfig, AgentMode
from solagent.schema.messages import Message
from solagent.server.models import (
    AgentRunRequest,
    AgentRunResponse,
    ConfigResponse,
    HealthResponse,
    LearningExperienceResponse,
    LearningScoreResponse,
    LearningStrategyResponse,
    MetricsResponse,
)

_logger = logging.getLogger(__name__)

# 全局运行时状态：请求计数、token 累计、启动时间等
_metrics: dict[str, Any] = {"total_requests": 0, "total_tokens": {"input": 0, "output": 0}, "start_time": time.time()}
_config_path: str | None = None
_config: Any = None
_factory: Any = None
_memory: Any = None


def _get_memory() -> Any:
    """获取全局 MemoryManager 实例。"""
    return _memory


def _parse_messages(raw: list[dict]) -> list[Message]:
    """将前端传入的原始消息字典列表解析为内部 Message 模型列表。

    参数:
        raw: 每条消息包含 role 和 content 字段的字典列表。

    返回:
        解析后的 Message 对象列表。
    """
    messages = []
    for m in raw:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            messages.append(Message.system(content))
        elif role == "assistant":
            messages.append(Message.assistant(content))
        else:
            messages.append(Message.user(content))
    return messages


def _find_agent_config(agent_name: str) -> AgentConfigBlock | None:
    """在已加载的配置中查找指定名称的 Agent 配置块。

    参数:
        agent_name: Agent 名称。

    返回:
        对应的 AgentConfigBlock；若未找到则返回 None。
    """
    if not _config:
        return None
    for a in _config.agents:
        if a.name == agent_name:
            return a
    return None


def _build_agent_config(req: AgentRunRequest) -> AgentConfig:
    """根据请求参数和配置文件构建最终的 AgentConfig。

    优先级：请求参数 > 配置文件中的 Agent 块 > 全局默认配置。

    参数:
        req: 客户端传入的 AgentRunRequest。

    返回:
        合并后的 AgentConfig 实例。
    """
    agent_block = _find_agent_config(req.agent_name) if req.agent_name else None

    target_model = req.model or (agent_block.model if agent_block else "") or (_config.default_model if _config else "")
    target_mode = req.mode or (agent_block.mode if agent_block else "") or (_config.default_mode if _config else "react")
    mode = AgentMode(target_mode)

    if agent_block:
        return AgentConfig(
            name=agent_block.name,
            description=agent_block.description,
            system_prompt=req.system_prompt or agent_block.system_prompt,
            model=target_model,
            mode=mode,
            max_iterations=req.max_iterations if req.max_iterations > 0 else agent_block.max_iterations,
            max_tokens=req.max_tokens if req.max_tokens > 0 else agent_block.max_tokens,
            temperature=req.temperature if req.temperature >= 0 else agent_block.temperature,
            tools=list(req.tools) if req.tools else list(agent_block.tools),
            skills=list(agent_block.skills),
            middleware=list(agent_block.middleware),
            guardrails=list(agent_block.guardrails),
        )
    return AgentConfig(
        name=req.agent_name or "api-agent",
        system_prompt=req.system_prompt,
        model=target_model,
        mode=mode,
        max_iterations=req.max_iterations if req.max_iterations > 0 else 10,
        max_tokens=req.max_tokens if req.max_tokens > 0 else 4096,
        temperature=req.temperature if req.temperature >= 0 else 0.7,
        tools=list(req.tools),
    )


async def _resolve_system_prompt(req: AgentRunRequest, config: AgentConfig) -> str:
    """解析最终使用的 system prompt。

    优先级：提示模板渲染结果 > Agent 配置中的 system_prompt > 默认文案。

    参数:
        req: 客户端请求。
        config: 已构建的 AgentConfig。

    返回:
        最终使用的 system prompt 字符串。
    """
    if req.prompt_template:
        registry = get_prompt_registry()
        template = registry.get(req.prompt_template)
        if template:
            return template.render({
                "agent_name": config.name,
                "model": config.model,
                "tools": config.tools,
            })
    if config.system_prompt:
        return config.system_prompt
    if req.prompt_template:
        return ""
    return "You are a helpful AI assistant."


async def _stream_agent(builder: AgentBuilder, messages: list[Message]) -> AsyncIterator[str]:
    """以 SSE 格式流式输出 Agent 的运行步骤。

    参数:
        builder: 已配置好的 AgentBuilder 实例。
        messages: 输入消息列表。

    返回:
        SSE 数据行异步迭代器。
    """
    async for step in builder.run_stream(messages):
        payload = {
            "type": "content",
            "iteration": step.iteration,
            "content": step.content,
            "thinking": step.thinking,
            "tool_calls": step.tool_calls,
            "tool_results": step.tool_results,
            "is_final": step.is_final,
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def create_app(config_path: str | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    参数:
        config_path: 配置文件路径，None 则使用默认配置。

    返回:
        配置完成的 FastAPI 应用实例。
    """
    global _config_path, _config, _factory
    _config_path = config_path

    app = FastAPI(title="SolarSeptem Agent API", version="0.1.0")

    # 配置跨域中间件，允许所有来源（开发环境便利设置，生产环境应收紧）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        """HTTP 中间件：从请求头读取或生成 trace_id，并在响应头中回传，便于全链路追踪。"""
        tid = request.headers.get("X-Trace-ID", "")
        set_trace_id(tid)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = get_trace_id()
        return response

    @app.on_event("startup")
    async def _startup():
        """应用启动事件：加载配置、注册 LLM 提供商、初始化记忆系统。"""
        global _config, _factory, _memory
        loader = ConfigLoader(_config_path)
        _config = loader.load()
        registry = get_registry()
        register_providers_from_config(_config, registry)
        registry.auto_register_discovered()
        _factory = LLMFactory()
        from solagent.agents.memory.manager import MemoryManager
        from solagent.agents.memory.storage import MemoryStorage
        storage = MemoryStorage()
        _memory = MemoryManager()
        _memory.register(storage)

    @app.get("/api/health")
    async def health():
        """健康检查端点：返回当前已注册的提供商和 Agent 列表。"""
        providers = [p.name for p in (_config.providers or [])]
        agents = [a.name for a in (_config.agents or [])]
        return HealthResponse(providers=providers, agents=agents)

    @app.get("/api/metrics")
    async def metrics():
        """系统指标端点：返回请求总量、token 消耗、活跃服务商数等运行时指标。"""
        return MetricsResponse(
            total_requests=_metrics["total_requests"],
            total_tokens=_metrics["total_tokens"],
            active_providers=len(_config.providers) if _config else 0,
            agent_modes=[m.value for m in AgentMode],
        )

    @app.get("/api/config")
    async def config_info():
        """配置信息端点：返回当前加载的默认模型、服务商、Agent 和提示模板列表。"""
        registry = get_prompt_registry()
        return ConfigResponse(
            default_model=_config.default_model if _config else "",
            default_mode=_config.default_mode if _config else "",
            providers=[p.model_dump() for p in (_config.providers or [])],
            agents=[a.model_dump() for a in (_config.agents or [])],
            prompt_templates=registry.list_names(),
        )

    @app.post("/api/agents/run")
    async def run_agent(req: AgentRunRequest):
        """Agent 运行端点：根据请求构建 Agent 配置并执行对话。

        支持同步返回完整结果，或通过 SSE 流式输出中间步骤。
        """
        _metrics["total_requests"] += 1
        try:
            agent_config = _build_agent_config(req)
            system_prompt = await _resolve_system_prompt(req, agent_config)
            provider = _factory.create(agent_config.model)

            messages = [Message.system(system_prompt)] + _parse_messages(req.messages)

            builder = AgentBuilder()
            builder.with_config(agent_config).with_provider(provider)

            if req.stream:
                # 流式模式：返回 SSE 响应，逐行输出 Agent 运行步骤
                return StreamingResponse(
                    _stream_agent(builder, messages),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )

            result = await builder.run(messages)
            if result.token_usage:
                _metrics["total_tokens"]["input"] += result.token_usage.input_tokens
                _metrics["total_tokens"]["output"] += result.token_usage.output_tokens

            return AgentRunResponse(
                content=result.content,
                finish_reason=result.finish_reason,
                token_usage=result.token_usage.model_dump() if result.token_usage else {},
                tool_calls=[tc.model_dump() for tc in result.tool_results] if result.tool_results else [],
                duration_ms=result.duration_ms,
                steps=result.steps,
            )
        except Exception as e:
            _logger.exception("Agent run error")
            return AgentRunResponse(error=str(e))

    @app.get("/api/agents/stream")
    async def stream_agent_get(
        message: str = "",
        agent_name: str = "",
        model: str = "",
        mode: str = "",
        prompt_template: str = "",
    ):
        """Agent 流式运行端点（GET 版本）：通过查询参数触发 SSE 流式输出。"""
        req = AgentRunRequest(
            messages=[{"role": "user", "content": message}],
            agent_name=agent_name,
            model=model,
            mode=mode,
            stream=True,
            prompt_template=prompt_template,
        )
        return await run_agent(req)

    @app.get("/")
    async def index():
        """根路径：返回 web/static/index.html 若存在，否则返回默认提示页。"""
        web_dir = Path(__file__).parent.parent / "web" / "static"
        index_path = web_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(index_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>SolarSeptem Agent API</h1><p>Web UI not found. API available at /api/health</p>")

    @app.get("/{filename:path}")
    async def static_files(filename: str):
        """静态文件服务：从 web/static 目录提供 CSS/JS/HTML 等资源。"""
        web_dir = Path(__file__).parent.parent / "web" / "static"
        file_path = web_dir / filename
        if file_path.exists() and file_path.is_file():
            if filename.endswith(".css"):
                return FileResponse(str(file_path), media_type="text/css")
            if filename.endswith(".js"):
                return FileResponse(str(file_path), media_type="application/javascript")
            return FileResponse(str(file_path))
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/learning/experiences")
    async def get_experiences(
        limit: int = 20,
        tag: str = "",
        min_score: float = 0.0,
    ):
        """学习经验查询端点：从记忆系统检索 EXPERIENCE 类别的记录，支持标签过滤。"""
        from solagent.agents.learning.models import ExperienceRecord
        from solagent.schema.memory import MemoryCategory, MemoryQuery

        memory = _get_memory()
        if not memory:
            return LearningExperienceResponse()

        query = MemoryQuery(
            query="",
            categories=[MemoryCategory.EXPERIENCE],
            limit=limit,
            min_importance=min_score,
        )
        results = await memory.search(query)

        experiences = []
        tags_dist: dict[str, int] = {}
        for r in results:
            record = ExperienceRecord.from_memory(r.record)
            if tag and record.tag.value != tag:
                continue
            t = record.tag.value
            tags_dist[t] = tags_dist.get(t, 0) + 1
            experiences.append({
                "id": r.record.id,
                "task_signature": record.task_signature,
                "tag": record.tag.value,
                "outcome": record.outcome,
                "score": record.score,
                "tool_sequence": record.tool_sequence,
                "lesson": record.lesson,
                "created_at": record.created_at.isoformat(),
            })

        return LearningExperienceResponse(
            experiences=experiences[:limit],
            total=len(results),
            tags_distribution=tags_dist,
        )

    @app.get("/api/learning/strategies")
    async def get_strategies(status: str = ""):
        """学习策略查询端点：从记忆系统检索 STRATEGY 类别的规则，支持状态过滤。"""
        from solagent.agents.learning.models import StrategyRule
        from solagent.schema.memory import MemoryCategory, MemoryQuery

        memory = _get_memory()
        if not memory:
            return LearningStrategyResponse()

        query = MemoryQuery(
            query="",
            categories=[MemoryCategory.STRATEGY],
            limit=100,
        )
        results = await memory.search(query)

        strategies = []
        status_dist: dict[str, int] = {}
        for r in results:
            rule = StrategyRule.from_memory(r.record)
            if status and rule.status != status:
                continue
            status_dist[rule.status] = status_dist.get(rule.status, 0) + 1
            strategies.append({
                "rule_id": rule.rule_id,
                "description": rule.description,
                "status": rule.status,
                "success_rate": rule.success_rate,
                "use_count": rule.use_count,
                "recommended_tools": rule.recommended_tools,
                "deprecated_tools": rule.deprecated_tools,
                "forbidden_patterns": rule.forbidden_patterns,
                "created_at": rule.created_at.isoformat(),
            })

        return LearningStrategyResponse(
            strategies=strategies,
            total=len(results),
            status_distribution=status_dist,
        )

    @app.get("/api/learning/score")
    async def get_learning_score():
        """学习评分端点：综合计算任务成功率、工具效率、token 效率和学习进度加权总分。"""
        from solagent.agents.learning.models import ExperienceRecord
        from solagent.schema.memory import MemoryCategory, MemoryQuery

        memory = _get_memory()
        if not memory:
            return LearningScoreResponse()

        exp_query = MemoryQuery(
            query="",
            categories=[MemoryCategory.EXPERIENCE],
            limit=100,
        )
        exp_results = await memory.search(exp_query)
        experiences = [ExperienceRecord.from_memory(r.record) for r in exp_results]

        strat_query = MemoryQuery(
            query="",
            categories=[MemoryCategory.STRATEGY],
            limit=100,
        )
        strat_results = await memory.search(strat_query)

        # 计算各维度指标
        success_count = sum(1 for e in experiences if e.outcome == "success")
        task_success = success_count / max(1, len(experiences))
        avg_tools = sum(len(e.tool_sequence) for e in experiences) / max(1, len(experiences))
        tool_efficiency = min(1.0, 3.0 / max(1, avg_tools))
        total_tokens = sum(e.input_tokens + e.output_tokens for e in experiences)
        avg_tokens = total_tokens / max(1, len(experiences))
        token_efficiency = min(1.0, 2000.0 / max(1, avg_tokens))
        learning_score = min(1.0, len(experiences) / 100.0)

        # 加权计算综合评分
        overall = task_success * 0.4 + tool_efficiency * 0.2 + token_efficiency * 0.2 + learning_score * 0.2

        return LearningScoreResponse(
            overall=round(overall, 2),
            breakdown={
                "task_success": round(task_success, 2),
                "tool_efficiency": round(tool_efficiency, 2),
                "token_efficiency": round(token_efficiency, 2),
                "learning_score": round(learning_score, 2),
            },
            trend=[],
            experience_count=len(experiences),
            strategy_count=len(strat_results),
            last_reflection="",
            next_reflection_eta="",
        )

    @app.delete("/api/learning/experiences/{experience_id}")
    async def delete_experience(experience_id: str):
        """删除指定 ID 的学习经验记录。"""
        memory = _get_memory()
        if not memory:
            return JSONResponse({"error": "no memory configured"}, status_code=400)
        deleted = await memory.delete(experience_id)
        return JSONResponse({"deleted": deleted})

    @app.post("/api/learning/reflect")
    async def trigger_reflection():
        """触发学习系统的后台反思流程（当前为占位实现）。"""
        return {"status": "reflection triggered", "note": "background reflection scheduled"}

    return app


async def run_server(config_path: str | None = None, host: str = "0.0.0.0", port: int = 8000) -> None:
    """使用 uvicorn 启动 HTTP 服务器。

    参数:
        config_path: 配置文件路径。
        host: 监听地址。
        port: 监听端口。
    """
    import uvicorn
    app = create_app(config_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()