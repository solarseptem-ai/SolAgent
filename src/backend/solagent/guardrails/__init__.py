"""
安全防护（Guardrails）模块聚合导出。

提供输入/输出内容的审查机制，包括防护规则定义（Guardrail）、
规则注册中心（GuardrailRegistry）以及审查结果（GuardrailResult）。
"""
from solagent.guardrails.base import Guardrail, GuardrailResult
from solagent.guardrails.registry import GuardrailRegistry

__all__ = ["Guardrail", "GuardrailRegistry", "GuardrailResult"]