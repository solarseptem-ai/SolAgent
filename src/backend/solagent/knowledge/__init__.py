"""
知识库（Knowledge）模块聚合导出。

提供文档模型（Document）、知识库抽象（KnowledgeBase）和检索器（KnowledgeRetriever）。
用于 Agent 的外部知识增强和上下文检索。
"""
from solagent.knowledge.base import Document, KnowledgeBase
from solagent.knowledge.retriever import KnowledgeRetriever

__all__ = ["Document", "KnowledgeBase", "KnowledgeRetriever"]