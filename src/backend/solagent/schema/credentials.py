"""凭证存储后端协议定义，作为连接各种凭证管理实现的窄腰层。

本模块定义了 CredentialStore 协议接口，SolAgent 框架通过该协议与具体的
凭证存储实现（如环境变量、密钥管理服务、本地加密存储等）解耦，
确保在不同部署环境中都能安全地获取 LLM Provider 所需的 API 密钥等敏感信息。
"""
from __future__ import annotations

from typing import Any, Protocol


class CredentialStore(Protocol):
    """凭证存储协议，定义了获取和枚举 Provider 凭证的标准接口。

    任何具体的凭证存储后端（如环境变量读取器、HashiCorp Vault 客户端、
    AWS Secrets Manager 适配器等）均需实现此协议，以便 Agent 在执行期间
    安全地获取所需认证信息。
    """

    def get(self, provider: str) -> dict[str, Any] | None:
        """根据 Provider 名称获取对应的凭证字典。

        Args:
            provider: Provider 标识名称，如 "openai"、"anthropic"。

        Returns:
            包含凭证信息的字典，若该 Provider 未配置则返回 None。
        """
        ...

    def list_providers(self) -> set[str]:
        """返回当前已配置的所有 Provider 名称集合。

        Returns:
            已配置 Provider 的名称集合。
        """
        ...