from typing import Any

from backend.search.search_backends import SearchBackend, SearchRequest

try:
    from ddgs import DDGS
except Exception:
    DDGS = None


class SearchDuckDuckGoBackend(SearchBackend):
    """DuckDuckGo 搜索适配器。

    这个后端不需要 API Key，适合作为本地演示和其它后端不可用时的兜底。
    它只负责调用 ddgs 并把结果归一成 SearchTool 约定的结构。
    """
    name = "duckduckgo"

    def __init__(self, logger):
        """注入 logger，方便记录搜索异常。"""
        self.logger = logger

    def is_available(self) -> bool:
        """ddgs 依赖安装成功时可用。"""
        return DDGS is not None

    def search(self, request: SearchRequest) -> dict[str, Any]:
        """
               调 DuckDuckGo 搜索，并统一返回结构。

               返回结构固定为：
               {
                   "backend": "duckduckgo",
                   "results": [
                       {"title": "...", "url": "...", "content": "..."}
                   ],
                   "notices": []
               }
        """
        if not DDGS:
            return self._fallback_search_result("duckduckgo", ["duckduckgo 没有安装成功"])

        try:
            # ddgs 支持客户端级 timeout，这里使用 SearchRequest 传入的配置，
            # 避免 DuckDuckGo 网络抖动时卡住整个研究任务。
            with DDGS(timeout=request.timeout_seconds) as client:
                results = client.text(request.query, max_results=request.max_results)
        except Exception as e:
            return self._fallback_search_result("duckduckgo", [f"duckduckgo 搜索失败, error: {e}"])

        if not results:
            return self._fallback_search_result("duckduckgo", ["duckduckgo 搜索结果为空"])

        search_results = []
        notices = []

        for item in results:
            title = item.get("title") or ""
            url = item.get("url") or item.get("href") or ""
            content = item.get("content") or item.get("body") or ""

            if not url or not content:
                notices.append("url or content is empty")
                continue

            search_results.append(
                {
                    "title": title,
                    "url": url,
                    "content": self._limit_text(content, request.max_tokens),
                }
            )
        return {
            "backend": "duckduckgo",
            "results": search_results,
            "notices": notices
        }
