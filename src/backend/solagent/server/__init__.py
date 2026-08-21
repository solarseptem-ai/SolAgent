"""HTTP 服务器模块：基于 FastAPI 提供 SolarSeptem Agent 的 REST API。

包含应用创建（create_app）和服务器运行（run_server）入口，
暴露 Agent 执行、健康检查、指标监控、学习系统管理等功能端点。
"""
from solagent.server.app import create_app, run_server

__all__ = ["create_app", "run_server"]