"""任务调度相关的数据模型定义。

本模块定义了任务状态枚举、任务规格和任务结果模型，
用于 SolAgent 的任务队列和调度系统中，支持 Agent 间的任务委托和异步执行。
"""
from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态枚举，描述任务在生命周期中的当前阶段。"""
    PENDING = "pending"       # 已提交，等待调度执行
    RUNNING = "running"       # 正在执行中
    COMPLETED = "completed"   # 已成功完成
    FAILED = "failed"         # 执行失败
    TIMEOUT = "timeout"       # 执行超时


class TaskSpec(BaseModel):
    """任务规格模型，定义一个待执行任务的完整描述。

    属性说明：
        task_id: 任务唯一标识符，默认自动生成 UUID。
        target_agent: 目标 Agent 的标识，指定由哪个 Agent 处理该任务。
        payload: 任务负载，通常为需要处理的输入内容或指令。
        deadline: 任务截止时间（Unix 时间戳），0 表示无截止时间。
        priority: 任务优先级，数值越大优先级越高。
        metadata: 扩展元数据字典。
    """
    model_config = {"frozen": True}

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_agent: str
    payload: str
    deadline: float = 0
    priority: int = 0
    metadata: dict = Field(default_factory=dict)


class TaskResult(BaseModel):
    """任务执行结果模型，封装任务完成后的输出和状态信息。

    属性说明：
        task_id: 关联的任务标识符。
        status: 任务的最终状态。
        output: 任务的输出内容，成功时为主要结果。
        error: 失败时的错误描述。
        duration_ms: 任务执行耗时（毫秒）。
    """
    model_config = {"frozen": True}

    task_id: str
    status: TaskStatus
    output: str = ""
    error: str = ""
    duration_ms: int = 0