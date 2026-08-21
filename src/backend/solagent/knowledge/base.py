"""
知识库基础定义模块。

定义文档数据模型和知识库抽象协议，具体存储和检索实现需遵循 KnowledgeBase 接口。
"""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Document:
    """知识库中的文档单元。

    Attributes:
        id: 文档唯一标识。
        content: 文档文本内容。
        metadata: 附加元数据字典，如来源、时间戳、标签等。
    """
    id: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)


class KnowledgeBase(Protocol):
    """知识库协议，定义文档增删查的基本操作。"""

    async def add(self, documents: list[Document]) -> None:
        """批量添加文档到知识库。

        Args:
            documents: 要添加的文档列表。
        """
        ...

    async def search(self, query: str, top_k: int = 5) -> list[Document]:
        """按查询文本检索最相关的文档。

        Args:
            query: 查询文本。
            top_k: 返回的最大结果数，默认 5。

        Returns:
            相关文档列表。
        """
        ...

    async def delete(self, doc_id: str) -> bool:
        """删除指定文档。

        Args:
            doc_id: 要删除的文档 ID。

        Returns:
            是否成功删除。
        """
        ...

    async def clear(self) -> None:
        """清空知识库中的所有文档。"""
        ...