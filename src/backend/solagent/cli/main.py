"""
CLI 主入口模块。

提供 solagent 命令行的完整功能：
- init: 项目脚手架
- run: 交互式运行 Agent（支持流式输出和一次性提示）
- config: 显示当前配置
- serve: 启动 HTTP API 服务器
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)


def _init_project(args: argparse.Namespace) -> None:
    """执行 init 子命令：创建新项目。"""
    from solagent.cli.init import init_project, validate_name

    name = args.name
    if name is None:
        name = input("Project name: ").strip()

    validate_name(name)
    target_dir = Path(args.target_dir) / name if args.target_dir else Path.cwd() / name
    result = init_project(name, target_dir)
    print(f"Project '{name}' created at {result}")
    print(f"  cd {name}")
    print("  pip install -e .")
    print("  solagent run")


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="solagent",
        description="Production-grade AI Agent Framework",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # run 子命令：交互式运行 Agent
    run_parser = sub.add_parser("run", help="Run an agent interactively")
    run_parser.add_argument(
        "-c", "--config", dest="config_path", type=str, default=None,
        help="Path to solagent.yaml config file",
    )
    run_parser.add_argument(
        "-m", "--model", type=str, default=None,
        help="Model to use (overrides config)",
    )
    run_parser.add_argument(
        "-M", "--mode", type=str, default=None,
        choices=["chat", "function_call", "react", "plan_execute", "compiler", "reflexion", "code_as_action"],
        help="Agent mode (overrides config)",
    )
    run_parser.add_argument(
        "-a", "--agent", dest="agent_name", type=str, default=None,
        help="Agent name from config (uses agent's model, mode, tools, skills)",
    )
    run_parser.add_argument(
        "-s", "--stream", action="store_true", default=False,
        help="Enable streaming output",
    )
    run_parser.add_argument(
        "-p", "--prompt", type=str, default=None,
        help="One-shot prompt (non-interactive mode)",
    )

    # init 子命令：项目脚手架
    init_parser = sub.add_parser("init", help="Scaffold a new project")
    init_parser.add_argument(
        "name", type=str, nargs="?", default=None,
        help="Project name (must be a valid Python identifier)",
    )
    init_parser.add_argument(
        "-d", "--dir", dest="target_dir", type=str, default=None,
        help="Target directory (defaults to current directory / project name)",
    )

    # config 子命令：显示配置
    sub.add_parser("config", help="Show current config")

    # serve 子命令：启动 HTTP 服务
    serve_parser = sub.add_parser("serve", help="Start HTTP API server with Web UI")
    serve_parser.add_argument(
        "-c", "--config", dest="config_path", type=str, default=None,
        help="Path to solagent.yaml config file",
    )
    serve_parser.add_argument(
        "--host", type=str, default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "-p", "--port", type=int, default=8000,
        help="Port to bind (default: 8000)",
    )

    parser.add_argument("--version", action="version", version="solagent 0.1.0")
    return parser


def _show_config(config_path: str | None = None) -> None:
    """显示当前 SolAgent 配置摘要。"""
    from solagent.config import ConfigLoader
    loader = ConfigLoader(config_path)
    cfg = loader.load()
    print(f"Default model: {cfg.default_model}")
    print(f"Default mode: {cfg.default_mode}")
    print(f"Log level: {cfg.log.level}")
    print(f"Providers ({len(cfg.providers)}):")
    for p in cfg.providers:
        print(f"  - {p.name}: {p.default_model} ({len(p.models)} models)")
    print(f"Agents ({len(cfg.agents)}):")
    for a in cfg.agents:
        print(f"  - {a.name}: {a.model} ({a.mode})")
    print(f"MCP Servers ({len(cfg.mcp_servers)}):")
    for m in cfg.mcp_servers:
        print(f"  - {m.name}: {m.transport}")


async def _run_agent(
    config_path: str | None = None,
    model: str | None = None,
    mode: str | None = None,
    agent_name: str | None = None,
    stream: bool = False,
    prompt: str | None = None,
) -> None:
    """异步运行 Agent，支持交互模式和一次性提示模式。

    Args:
        config_path: 配置文件路径。
        model: 覆盖配置的模型名称。
        mode: 覆盖配置的 Agent 模式。
        agent_name: 配置中指定的 Agent 名称。
        stream: 是否启用流式输出。
        prompt: 一次性提示内容，非交互模式。
    """
    from solagent.agents.builder import AgentBuilder
    from solagent.config import ConfigLoader, register_providers_from_config
    from solagent.config.config_model import AgentConfigBlock
    from solagent.llms.factory import LLMFactory
    from solagent.llms.providers.registry import get_registry
    from solagent.schema.agent import AgentConfig, AgentMode
    from solagent.schema.messages import Message

    loader = ConfigLoader(config_path)
    cfg = loader.load()
    registry = get_registry()
    register_providers_from_config(cfg, registry)
    registry.auto_register_discovered()

    target_model = model or cfg.default_model
    target_mode_str = mode or cfg.default_mode
    target_mode = AgentMode(target_mode_str)
    agent_block: AgentConfigBlock | None = None

    # 若指定了 agent_name，从配置中查找对应 Agent 配置块
    if agent_name:
        for a in cfg.agents:
            if a.name == agent_name:
                agent_block = a
                break
        if not agent_block:
            print(f"Agent '{agent_name}' not found in config. Available agents:")
            for a in cfg.agents:
                print(f"  - {a.name}")
            return

        target_model = agent_block.model or target_model
        if not mode:
            target_mode_str = agent_block.mode or target_mode_str
            target_mode = AgentMode(target_mode_str)

    factory = LLMFactory()
    provider = factory.create(target_model)

    # 根据是否指定了 agent_block 构建 Agent 配置
    if agent_block:
        builder_config = AgentConfig(
            name=agent_block.name,
            description=agent_block.description,
            system_prompt=agent_block.system_prompt,
            model=agent_block.model or target_model,
            mode=target_mode,
            max_iterations=agent_block.max_iterations,
            max_tokens=agent_block.max_tokens,
            temperature=agent_block.temperature,
            tools=list(agent_block.tools),
            skills=list(agent_block.skills),
            middleware=list(agent_block.middleware),
            guardrails=list(agent_block.guardrails),
        )
    else:
        builder_config = AgentConfig(
            name="cli-agent",
            model=target_model,
            mode=target_mode,
            max_iterations=10,
            max_tokens=4096,
            temperature=0.7,
        )

    def _build_builder() -> AgentBuilder:
        """构建并配置 AgentBuilder 实例。"""
        builder = AgentBuilder()
        builder.with_config(builder_config).with_provider(provider)
        return builder

    # 一次性提示模式（非交互）
    if prompt:
        messages = [Message.system("You are a helpful AI assistant."), Message.user(prompt)]
        builder = _build_builder()

        if stream:
            async for step in builder.run_stream(messages):
                if step.tool_calls:
                    for tc in step.tool_calls:
                        print(f"\n[Tool: {tc.get('name', '')}]", flush=True)
                if step.content:
                    print(step.content, end="", flush=True)
                if step.tool_results:
                    for tr in step.tool_results:
                        output_preview = tr.get('output', '')[:200]
                        if output_preview:
                            print(f"\n[Result: {output_preview}]", flush=True)
                if step.is_final:
                    print()
        else:
            result = await builder.run(messages)
            print(result.content)
        return

    # 交互模式：循环读取用户输入
    print(f"Model: {target_model}")
    print(f"Mode: {target_mode_str}")
    print(f"Provider: {provider.profile.display_name}")
    print("Type 'quit' to exit, 'config' to show config.\n")

    messages: list = [Message.system("You are a helpful AI assistant.")]
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if user_input.lower() == "config":
            _show_config(config_path)
            continue

        messages.append(Message.user(user_input))
        builder = _build_builder()

        if stream:
            print("\nAgent: ", end="", flush=True)
            try:
                async for step in builder.run_stream(messages):
                    if step.tool_calls:
                        for tc in step.tool_calls:
                            print(f"\n[Tool: {tc.get('name', '')}]", flush=True)
                    if step.content:
                        print(step.content, end="", flush=True)
                    if step.tool_results:
                        for tr in step.tool_results:
                            output_preview = tr.get('output', '')[:200]
                            if output_preview:
                                print(f"\n[Result: {output_preview}]", flush=True)
                    if step.is_final:
                        print()
            except Exception as e:
                _logger.warning("CLI command failed", exc_info=True)
                print(f"\n[Error: {e}]")
            messages = builder.messages if builder.messages else messages
        else:
            result = await builder.run(messages)
            print(f"\nAgent: {result.content}\n")
            messages = list(result.messages)


def main() -> None:
    """CLI 主入口，解析参数并分发到对应子命令处理函数。"""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        _init_project(args)
    elif args.command == "config":
        cfg_path = getattr(args, 'config_path', None) if hasattr(args, 'config_path') else None
        _show_config(cfg_path)
    elif args.command == "run":
        asyncio.run(_run_agent(
            config_path=getattr(args, 'config_path', None),
            model=getattr(args, 'model', None),
            mode=getattr(args, 'mode', None),
            agent_name=getattr(args, 'agent_name', None),
            stream=getattr(args, 'stream', False),
            prompt=getattr(args, 'prompt', None),
        ))
    elif args.command == "serve":
        asyncio.run(_serve(
            config_path=getattr(args, 'config_path', None),
            host=getattr(args, 'host', '0.0.0.0'),
            port=getattr(args, 'port', 8000),
        ))
    else:
        parser.print_help()
        sys.exit(1)


async def _serve(config_path: str | None = None, host: str = "0.0.0.0", port: int = 8000) -> None:
    """启动 HTTP API 服务器。

    Args:
        config_path: 配置文件路径。
        host: 监听主机地址。
        port: 监听端口。
    """
    from solagent.server import run_server
    print(f"Server starting at http://{host}:{port}")
    print(f"Web UI: http://localhost:{port}")
    print(f"API docs: http://localhost:{port}/docs")
    await run_server(config_path, host, port)


if __name__ == "__main__":
    main()
