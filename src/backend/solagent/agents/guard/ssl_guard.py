"""SSL 证书验证守卫。

在 Agent 启动时检查系统环境变量中指定的 CA 证书 bundle 是否存在且有效，
同时验证 certifi 提供的默认 bundle，确保 HTTPS 请求不会因证书问题而失败。
仅做日志警告，不会中断程序启动。
"""

from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path

_logger = logging.getLogger(__name__)


class SSLGuard:
    """SSL CA 证书 bundle 验证器。

    检查常见 SSL 环境变量指向的证书文件是否存在、可读且包含有效证书，
    同时验证 certifi 默认 bundle 的可用性。
    """

    _CA_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

    @staticmethod
    def verify() -> None:
        """执行 CA bundle 验证，仅记录日志不做拦截。"""
        try:
            import certifi
        except ImportError:
            _logger.debug("SSL: certifi not installed, skipping CA bundle verification")
            return

        # 检查环境变量中显式指定的 CA 文件
        for env_var in SSLGuard._CA_ENV_VARS:
            value = os.environ.get(env_var)
            if not value:
                continue
            path = Path(value).expanduser()
            if not path.exists():
                _logger.warning("SSL: %s=%s does not exist", env_var, value)
                continue
            if not path.is_file():
                _logger.warning("SSL: %s=%s is not a file", env_var, value)
                continue
            try:
                ctx = ssl.create_default_context(cafile=str(path))
                if not ctx.get_ca_certs():
                    _logger.warning("SSL: %s=%s loaded but contains no certificates", env_var, value)
            except Exception as e:
                _logger.warning("SSL: %s=%s failed to load: %s", env_var, value, e)

        # 检查 certifi 默认 bundle
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            if not ctx.get_ca_certs():
                _logger.warning("SSL: certifi default bundle contains no certificates")
        except Exception as e:
            _logger.warning("SSL: certifi default bundle failed to load: %s", e)