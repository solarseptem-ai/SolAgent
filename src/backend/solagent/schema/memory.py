"""Agent 记忆系统相关的数据模型定义。

本模块定义了记忆记录的结构化表示，包括记忆分类、记忆条目、查询条件及搜索结果。
记忆系统允许 Agent 在长期运行中保存和检索事实、偏好、经验等信息，
从而在多轮对话和跨会话场景中保持上下文连贯性和个性化。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """记忆分类枚举，用于对记忆内容进行语义归类，便于分类检索和优先级管理。

    各类别含义：
        FACT: 客观事实。
        PREFERENCE: 用户偏好和习惯。
        EVENT: 发生过的具体事件。
        KNOWLEDGE: 领域知识。
        SUMMARY: 会话或任务的摘要。
        EXPERIENCE: Agent 从过往交互中获得的经验。
        STRATEGY: 解决问题的策略和方法。
        CONVERSATION: 对话片段。
    """
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    KNOWLEDGE = "knowledge"
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    STRATEGY = "strategy"
    CONVERSATION = "conversation"


class MemoryRecord(BaseModel):
    """单条记忆记录模型，表示 Agent 记忆系统中的一个原子知识单元。

    属性说明：
        id: 记忆的唯一标识符，默认自动生成 UUID。
        content: 记忆的文本内容。
        category: 记忆所属的语义分类。
        scope: 记忆的作用范围，如特定 Agent 或全局。
        importance: 重要程度评分，范围通常为 0.0 到 1.0，越高越重要。
        embedding: 向量嵌入表示，用于语义相似度搜索。
        source: 记忆来源标识，如某次会话 ID 或工具名称。
        metadata: 扩展元数据字典。
        created_at: 记录创建时间（UTC）。
        last_accessed: 最后一次访问时间（UTC），用于 LRU 淘汰策略。
        private: 是否为私有记忆，私有记忆不与其他 Agent 共享。
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    category: MemoryCategory
    scope: str = ""
    importance: float = 0.5
    embedding: list[float] = Field(default_factory=list)
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    private: bool = False


class MemoryQuery(BaseModel):
    """记忆查询条件模型，用于在记忆存储中检索相关记录。

    属性说明：
        query: 查询文本，可基于语义相似度或关键词匹配。
        categories: 限定检索的记忆分类列表，空列表表示不限制。
        scope: 限定记忆的作用范围。
        limit: 返回结果的最大数量。
        min_importance: 最小重要程度阈值，低于此值的记录被过滤。
        include_private: 是否包含私有记忆，默认为 False 以保护隐私。
    """
    query: str
    categories: list[MemoryCategory] = Field(default_factory=list)
    scope: str = ""
    limit: int = 10
    min_importance: float = 0.0
    include_private: bool = False


class MemorySearchResult(BaseModel):
    """记忆搜索结果模型，封装了匹配到的记忆记录及其相关度信息。

    属性说明：
        record: 匹配到的记忆记录。
        score: 匹配得分，越高表示与查询越相关。
        match_reason: 匹配原因的简要说明，用于可解释性展示。
    """
    record: MemoryRecord
    score: float
    match_reason: str = ""