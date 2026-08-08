from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchRequest:
    """搜索后端统一请求对象。

    SearchTool 会把用户参数转换成 SearchRequest，再交给 Tavily / SerpApi /
    DuckDuckGo 适配器执行，避免各个后端读取散乱的 dict。
    timeout_seconds 是单个搜索后端调用的超时上限，防止外部搜索服务长时间阻塞任务。
    """
    query: str
    max_results: int
    max_tokens: int
    fetch_full_page: bool = False
    timeout_seconds: int = 30


class SearchBackend(ABC):
    """搜索后端适配器抽象类。

    每个具体后端只需要实现：
    - is_available()：当前配置和依赖是否可用；
    - search()：执行搜索并返回统一结构。

    举例：
    SearchTavilyBackend 负责 Tavily API，SearchDuckDuckGoBackend 负责 ddgs，
    但它们返回的都是 {"backend": ..., "results": ..., "notices": ...}。
    """
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """判断当前搜索后端是否可用。"""
        raise NotImplementedError

    @abstractmethod
    def search(self, request: SearchRequest) -> dict[str, Any]:
        """执行搜索并返回统一结构。"""
        raise NotImplementedError

    def _fallback_search_result(
            self,
            backend: str,
            notices: list[str]
    ) -> dict[str, Any]:
        """构造空结果兜底结构。"""
        return {
            "backend": backend,
            "results": [],
            "notices": notices,
        }

    def _limit_text(
            self,
            text: str,
            token_limit: int
    ) -> str:
        """限制单条来源正文长度，避免后续 prompt 过长。"""
        char_limit = token_limit * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit] + "... [truncated]"
