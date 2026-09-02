"""适配器注册表：source_name -> 适配器类。

新增源站：用 @register 装饰器注册，或用配置自动发现。
调度器通过 create_adapter(name) 拿到实例，无需关心具体类。
"""

from __future__ import annotations

from .base import CrawlerAdapter

_REGISTRY: dict[str, type[CrawlerAdapter]] = {}


def register(name: str | None = None):
    """类装饰器：把适配器注册进注册表。"""

    def deco(cls: type[CrawlerAdapter]) -> type[CrawlerAdapter]:
        key = name or cls.source_name
        if not key:
            raise ValueError(f"适配器 {cls.__name__} 未设置 source_name")
        _REGISTRY[key] = cls
        return cls

    return deco


def create_adapter(source_name: str, http=None) -> CrawlerAdapter:
    """按源站名创建适配器实例（注入共享的 HttpFetcher）。"""
    if source_name not in _REGISTRY:
        raise KeyError(
            f"未注册的源站: {source_name}，可用: {list_adapters()}"
        )
    if http is None:
        from ..http import HttpFetcher

        http = HttpFetcher()
    return _REGISTRY[source_name](http=http)


def list_adapters() -> list[str]:
    return sorted(_REGISTRY)
