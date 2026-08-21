from solagent.agents.modes.chat import ChatMode
from solagent.agents.modes.code_as_action import CodeAsActionMode
from solagent.agents.modes.compiler import CompilerMode
from solagent.agents.modes.dag import DAGAgent
from solagent.agents.modes.evolving_react import EvolvingReAct
from solagent.agents.modes.function_call import FunctionCallMode
from solagent.agents.modes.plan_execute import PlanExecuteMode
from solagent.agents.modes.react import ReActMode
from solagent.agents.modes.reflexion import ReflexionMode
from solagent.agents.modes.registry import ModeRegistry
from solagent.schema.agent import AgentMode

# Auto-register all modes (sync registration is thread-safe for module import time)
ModeRegistry.register_sync(AgentMode.CHAT, ChatMode)
ModeRegistry.register_sync(AgentMode.FUNCTION_CALL, FunctionCallMode)
ModeRegistry.register_sync(AgentMode.REACT, ReActMode)
ModeRegistry.register_sync(AgentMode.PLAN_EXECUTE, PlanExecuteMode)
ModeRegistry.register_sync(AgentMode.COMPILER, CompilerMode)
ModeRegistry.register_sync(AgentMode.REFLEXION, ReflexionMode)
ModeRegistry.register_sync(AgentMode.CODE_AS_ACTION, CodeAsActionMode)
ModeRegistry.register_sync(AgentMode.EVOLVING_REACT, EvolvingReAct)
ModeRegistry.register_sync(AgentMode.DAG, DAGAgent)

__all__ = ["ChatMode", "CodeAsActionMode", "CompilerMode", "DAGAgent", "EvolvingReAct", "FunctionCallMode", "ModeRegistry", "PlanExecuteMode", "ReActMode", "ReflexionMode"]
