# SolAgent

Production-grade AI Agent Framework.

SolAgent 是一个生产级 Python AI Agent 框架，采用事件溯源会话（SessionLog）作为消息唯一来源，提供 11 阶段可插拔工具管道、8 种执行模式、4 种多 Agent 编排策略，以及完整的插件生命周期管理。

核心设计原则：**Model-visible ⟺ logged** — 所有到达 LLM 的消息均可从事件日志重建。

## 特性

- **事件溯源会话** — SessionLog 作为消息唯一来源，支持重放恢复和上下文压缩
- **8 种执行模式** — ReAct、Chat、FunctionCall、Plan-Execute、Reflexion、DAG、Compiler、CodeAsAction
- **11 阶段工具管道** — Resolve→Parse→Validate→Guard→Cache→HITL→Hook→Timeout→Execute→PostProcess→Finalize，每阶段可独立扩展
- **4 种多 Agent 编排** — Sequential、Delegate、Swarm、Team
- **插件系统** — Fiber 4 态状态机，副作用随 fiber 销毁自动撤销，5 种事件模式
- **三层韧性** — 熔断器 + 指数退避重试 + 限流器
- **渐进式工具披露** — 按 token 预算决定即时暴露 vs 延迟发现
- **MCP 集成** — 多服务器管理、命名空间隔离、熔断保护、SSRF 防护
- **自进化引擎** — UCB1 算法选优技能、引导轮曝光、置信度阈值遗忘

## 安装

```bash
pip install solagent
```

可选依赖：

```bash
pip install "solagent[remote]"      # arq + nats-py（分布式适配器）
pip install "solagent[media]"      # Pillow（图像处理）
pip install "solagent[docker]"     # Docker 沙箱
pip install "solagent[chromadb]"   # ChromaDB 向量存储
pip install "solagent[observability]"  # OpenTelemetry 链路追踪
pip install "solagent[all]"        # 全部可选依赖
```

## 快速开始

### CLI

```bash
# 创建新项目
solagent init myproject
cd myproject
pip install -e .

# 一次性提示
solagent run -p "What is 2+2?"

# 交互式对话（流式输出）
solagent run -s

# 指定模型和模式
solagent run -m gpt-4o -M react -p "Write a haiku about coding"

# 使用配置文件中定义的 Agent
solagent run -a my-agent -s

# 启动 HTTP API 服务
solagent serve --host 0.0.0.0 --port 8000
```

### Python API

```python
import asyncio
from solagent.agents.builder import AgentBuilder
from solagent.llms.factory import LLMFactory
from solagent.schema.agent import AgentConfig, AgentMode
from solagent.schema.messages import Message

async def main():
    provider = LLMFactory().create("gpt-4o")
    config = AgentConfig(
        name="my-agent",
        model="gpt-4o",
        mode=AgentMode.REACT,
        max_iterations=10,
        max_tokens=4096,
        temperature=0.7,
    )

    messages = [
        Message.system("You are a helpful AI assistant."),
        Message.user("Explain event sourcing in one sentence."),
    ]

    result = await (
        AgentBuilder()
        .with_config(config)
        .with_provider(provider)
        .run(messages)
    )
    print(result.content)

asyncio.run(main())
```

流式执行：

```python
async for step in builder.run_stream(messages):
    if step.content:
        print(step.content, end="", flush=True)
    if step.tool_calls:
        print(f"\n[Tool: {step.tool_calls[0].get('name')}]")
    if step.is_final:
        print()
```

## 配置

SolAgent 通过 `solagent.yaml` 管理配置：

```yaml
default_model: gpt-4o
default_mode: react

log:
  level: INFO
  format: text

providers:
  - name: openai
    default_model: gpt-4o
    models:
      - gpt-4o
      - gpt-4o-mini
    api_key_env: OPENAI_API_KEY

agents:
  - name: coder
    model: gpt-4o
    mode: react
    max_iterations: 20
    tools: [file_io, edit_file, shell, web_search]
    temperature: 0.7

mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

## 架构

```
┌─────────────────────────────────────────────┐
│                 CLI / Server                 │
├─────────────────────────────────────────────┤
│              AgentBuilder (链式构建)           │
├──────────┬──────────┬───────────────────────┤
│ BaseAgent │ AgentLoop │   8 种执行模式        │
│ (模板方法) │(Phase状态机)│ ReAct/DAG/Plan-Execute│
├──────────┴──────────┴───────────────────────┤
│        SessionLog (事件溯源，单一来源)         │
│        Inbox (next-turn / next-step 双队列)    │
├─────────────────────────────────────────────┤
│     11 阶段工具管道 + 调度器 + 守卫 + 缓存      │
├─────────────────────────────────────────────┤
│     插件系统 (Fiber 生命周期 + 5 种事件模式)    │
├──────────┬──────────┬──────────┬────────────┤
│   MCP    │ Subagent │ Sandbox  │  Skills    │
└──────────┴──────────┴──────────┴────────────┘
```

## 执行模式

| 模式 | 说明 |
|------|------|
| `react` | 推理-行动循环，Thought→Action→Observation |
| `chat` | 单轮对话，无工具调用 |
| `function_call` | 原生函数调用，工具并行执行 |
| `plan_execute` | 先规划再执行，两阶段 |
| `reflexion` | 自我反思，失败后反思再试 |
| `dag` | 有向无环图执行，拓扑排序 |
| `compiler` | 编译型，自然语言编译为执行计划 |
| `code_as_action` | 代码即行动，生成并执行代码 |

## License

MIT
