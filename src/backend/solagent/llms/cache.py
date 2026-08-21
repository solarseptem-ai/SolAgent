"""LLM 响应缓存模块。

为 LLM 请求提供基于消息内容、模型名称和温度参数的响应缓存，
避免对相同参数的重复请求产生额外的 API 调用开销，从而降低成本并提升响应速度。
"""
import hashlib
import json

from pydantic import BaseModel

from solagent.schema.llm import LLMResponse


class LLMCache:
    """LLM 响应缓存器，通过哈希键缓存和复用 LLM 响应结果。

    属性:
        _cache: 内部字典，存储哈希键到 LLMResponse 的映射。
        _max_size: 缓存容量上限，达到上限后会移除最早插入的条目。
    """

    def __init__(self, max_size: int = 1000):
        self._cache: dict[str, LLMResponse] = {}
        self._max_size = max_size

    def _key(self, messages: list, model: str, temperature: float) -> str:
        """根据请求参数生成唯一的缓存键（SHA256 哈希值）。"""
        # 将消息列表序列化为 JSON 字符串，确保相同内容的消息产生相同的键
        content = json.dumps([m.model_dump(mode="json") if isinstance(m, BaseModel) else str(m) for m in messages], sort_keys=True)
        raw = f"{content}:{model}:{temperature}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: list, model: str, temperature: float) -> LLMResponse | None:
        """根据请求参数从缓存中获取响应，未命中时返回 None。"""
        return self._cache.get(self._key(messages, model, temperature))

    def set(self, messages: list, model: str, temperature: float, response: LLMResponse) -> None:
        """将响应结果写入缓存，若缓存已满则淘汰最早插入的条目。"""
        if len(self._cache) >= self._max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[self._key(messages, model, temperature)] = response

    def clear(self) -> None:
        """清空所有缓存条目。"""
        self._cache.clear()