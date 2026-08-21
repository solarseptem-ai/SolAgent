"""
MCP 安全模块。

提供 SSRF（服务器端请求伪造）防护和 DNS 固定（DNS pinning）能力。
校验 MCP 服务器 URL 是否指向受保护的内部网络，阻止潜在的内网探测攻击。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# 禁止访问的内部网络段，防止 SSRF 攻击
_BLOCKED_NETWORKS = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
]


def validate_mcp_url(url: str) -> str:
    """校验 MCP 服务器 URL 的安全性。

    规则：
    1. URL 不能为空。
    2. 仅支持 http / https 协议。
    3. 必须包含主机名。
    4. localhost 和回环地址允许通过。
    5. 解析后的 IP 不能落在受保护的内部网段。

    Args:
        url: MCP 服务器 URL。

    Returns:
        校验通过的原 URL。

    Raises:
        ValueError: URL 为空、协议不支持或解析到受保护网段时。
    """
    if not url:
        raise ValueError("MCP server URL cannot be empty")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported protocol: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid URL: no hostname in {url}")
    # localhost 和回环地址直接放行
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return url
    try:
        # 尝试直接解析 IP
        addr = ipaddress.IPv4Address(hostname)
    except ValueError:
        # 主机名为域名时，解析 DNS 获取 IP
        try:
            resolved = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return url
        for _, _, _, _, sockaddr in resolved:
            ip = sockaddr[0]
            try:
                addr = ipaddress.IPv4Address(ip)
                break
            except ValueError:
                continue
        else:
            return url
    # 检查解析后的 IP 是否在受保护网段内
    for network in _BLOCKED_NETWORKS:
        if addr in network:
            raise ValueError(f"URL resolves to blocked network: {hostname} → {addr}")
    return url


def pinned_http_client(hostname: str, ip: str, timeout: float = 30.0) -> httpx.AsyncClient:
    """创建一个 DNS 固定的 HTTP 客户端。

    直接连接到指定 IP，同时保留原始 Host 头，用于绕过 DNS 重绑定攻击。

    Args:
        hostname: 原始主机名（用于 Host 头）。
        ip: 预先解析并校验过的 IP 地址。
        timeout: 请求超时时间（秒）。

    Returns:
        配置好的 httpx.AsyncClient 实例。
    """
    transport = httpx.AsyncHTTPTransport(
        verify=True,
        retries=0,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        headers={"Host": hostname},
        base_url=f"https://{ip}",
    )
