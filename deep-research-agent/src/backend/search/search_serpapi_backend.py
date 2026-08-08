from typing import Any

from backend.search.search_backends import SearchBackend, SearchRequest

try:
    from serpapi import GoogleSearch  # type: ignore
except Exception:  # pragma: no cover - 可选依赖
    GoogleSearch = None  # type: ignore


class SearchSerpapiBackend(SearchBackend):
    """SerpApi 搜索适配器。

    负责把 Google Search 的 organic_results 转成统一结果结构。
    需要 SERPAPI_API_KEY 和 serpapi 依赖可用。
    """
    name = "serpapi"

    def __init__(self, api_key: str, logger) -> None:
        """保存 SerpApi Key 和 logger。"""
        self.api_key = api_key
        self.logger = logger

    def is_available(self) -> bool:
        """API Key 存在且依赖可导入时可用。"""
        return bool(self.api_key) and GoogleSearch is not None

    def search(self, request: SearchRequest) -> dict[str, Any]:
        """调用 SerpApi 并归一化 organic_results。"""
        params = {
            "engine": "google",
            "q": request.query,
            "api_key": self.api_key,
            "gl": "cn",
            "hl": "zh-cn",
            "num": request.max_results
        }

        try:
            # serpapi 的 GoogleSearch 构造函数不暴露 timeout 参数，
            # 但父类会读取实例上的 timeout 字段；这里显式覆盖成项目配置。
            search = GoogleSearch(params)
            search.timeout = request.timeout_seconds
            response = search.get_dict()
        except Exception as e:
            return self._fallback_search_result("serpapi", [f"serpapi 搜索异常，error: {e}"])

        if not response or not isinstance(response, dict):
            return self._fallback_search_result("serpapi", ["serpapi 没有获取到数据"])

        results = response.get("organic_results") or []
        notices = []
        search_results = []

        for item in results:
            if not isinstance(item, dict):
                continue

            title = item.get("title") or ""
            url = item.get("link") or ""
            content = item.get("snippet") or ""

            if not url or not content:
                notices.append(
                    "摘要或者上下文为空"
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
            "backend": "serpapi",
            "results": search_results,
            "notices": notices,
        }
