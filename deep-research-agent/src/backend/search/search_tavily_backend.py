from typing import Any

from backend.search.search_backends import SearchBackend, SearchRequest

try:
    from tavily import TavilyClient
except Exception:
    TavilyClient = None


class SearchTavilyBackend(SearchBackend):
    """Tavily 搜索适配器。

    Tavily 更适合 deep research 场景，因为它可以返回 raw_content。
    当前只有在 fetch_full_page=True 时才请求 raw_content，避免无谓拉长上下文。
    """
    name = "tavily"

    def __init__(self, api_key: str, logger):
        """保存 Tavily Key，并延迟创建 TavilyClient。"""
        self.api_key = api_key
        self.logger = logger
        self.tavily_client = None

    def is_available(self) -> bool:
        """API Key 存在且 tavily 依赖可导入时可用。"""
        return bool(self.api_key) and TavilyClient is not None

    def search(self, request: SearchRequest) -> dict[str, Any]:
        """调用 Tavily 并归一化搜索结果。"""
        self._build_tavily_client()
        if not self.api_key or self.tavily_client is None:
            return self._fallback_search_result("tavily", ["tavily 没有初始化成功"])

        try:
            response = self.tavily_client.search(
                query=request.query,
                max_results=request.max_results,
                include_raw_content=request.fetch_full_page,
                # Tavily SDK 原生支持 timeout。这里做后端级防卡死，
                # workflow timeout 只负责整条链路兜底，不替代外部依赖超时。
                timeout=request.timeout_seconds,
            )
        except Exception as e:
            return self._fallback_search_result("tavily", [f"tavily 搜索异常，error: {e}"])

        if response is None:
            return self._fallback_search_result("tavily", ["tavily 没有获取到正确的数据"])

        results = response.get("results", [])
        if not results or len(results) == 0:
            return self._fallback_search_result("tavily", ["tavily 没有获取到正确的数据"])

        notices = []
        search_results = []

        for item in results:
            if not isinstance(item, dict):
                continue

            title = item.get("title") or ""
            url = item.get("url") or ""
            content = (item.get("raw_content") if request.fetch_full_page else item.get("content")) or ""

            if not url or not content:
                notices.append(
                    "没有上下文和摘要数据跳过"
                )
                continue
            search_results.append(
                {
                    "title": title,
                    "url": url,
                    "content": self._limit_text(content, request.max_tokens),
                }
            )
        return {
            "backend": "tavily",
            "results": search_results,
            "notices": notices,
        }

    def _build_tavily_client(self):
        """懒初始化 TavilyClient。

        这样 SearchTool 初始化时不会立即访问 Tavily 依赖或网络相关逻辑，
        只有真正搜索时才创建 client。
        """
        if not self.api_key or TavilyClient is None:
            return
        if self.tavily_client is not None:
            return
        try:
            self.tavily_client = TavilyClient(api_key=self.api_key)
        except Exception as e:
            self.logger.exception("failed to build Tavily client: %s", e)
