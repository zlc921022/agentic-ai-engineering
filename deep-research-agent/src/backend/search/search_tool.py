from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_logger import get_logger
from backend.core.config import Config
from backend.search.search_backends import SearchBackend, SearchRequest
from backend.search.search_duckduckgo_backend import SearchDuckDuckGoBackend
from backend.search.search_serpapi_backend import SearchSerpapiBackend
from backend.search.search_tavily_backend import SearchTavilyBackend
from backend.tools.tool import Tool

SUPPORTED_RETURN_MODES = {"text", "structured", "json", "dict"}
SUPPORTED_BACKENDS = {
    "hybrid",
    "tavily",
    "serpapi",
    "duckduckgo",
}


class SearchToolArguments(BaseModel):
    """SearchTool 的通用参数模型，兼容直接调用和未来工具注册。"""

    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=500)
    mode: str = "structured"
    max_results: int = Field(default=5, ge=1, le=20)
    fetch_full_page: bool = False
    max_tokens_per_source: int = Field(default=1000, ge=100, le=8000)
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    backend: str = "hybrid"


class SearchTool(Tool):
    """
    搜索工具路由器：负责选择搜索后端、降级兜底和返回格式统一。

    核心思路：
    1. 从 parameters 里取 query；
    2. 根据 backend 选择 Tavily / SerpApi / DuckDuckGo；
    3. 把搜索结果统一成固定结构；
    4. 默认返回文本，方便直接喂给 summarizer；
    5. mode="structured" 时返回 dict，方便程序继续处理。

    举例：
    用户选择 backend="hybrid" 时，SearchTool 会按 Tavily -> SerpApi -> DuckDuckGo
    的顺序尝试；如果 Tavily 没配置 key 或没结果，会自动降级并把原因写进 notices。
    """

    def __init__(self, config: Config | None = None) -> None:
        """初始化搜索后端适配器。"""
        super().__init__(
            name="search",
            description=(
                "智能网页搜索引擎，支持 Tavily、SerpApi、DuckDuckGo 等后端，可返回结构化或文本化的搜索结果。"
            )
        )
        self.arguments_model = SearchToolArguments
        self.config = config or Config.from_env()
        self.config.ensure_dirs()
        self.logger = get_logger(__name__)
        self.backends: dict[str, SearchBackend] = {
            "tavily": SearchTavilyBackend(self.config.tavily_api_key, self.logger),
            "serpapi": SearchSerpapiBackend(self.config.serpapi_api_key, self.logger),
            "duckduckgo": SearchDuckDuckGoBackend(self.logger),
        }

    def check_backend(self, backend: str) -> str:
        """校验并修正请求的搜索后端。

        不支持或不可用的后端会降级为 hybrid，避免用户选错配置导致整条流程失败。
        """
        if backend not in SUPPORTED_BACKENDS:
            self.logger.warning("unsupported search backend=%s, fallback=hybrid", backend)
            return "hybrid"

        if backend == "hybrid":
            self.logger.info("setup search backend=%s", backend)
            return backend

        search_backend = self.backends.get(backend)
        if search_backend is None or not search_backend.is_available():
            self.logger.warning("search backend unavailable backend=%s, fallback=hybrid", backend)
            return "hybrid"

        self.logger.info("setup search backend=%s", backend)
        return backend

    def run(
            self,
            parameters: dict[str, Any],
            *,
            context: object = None,
    ) -> str | dict[str, Any]:
        """
        工具入口。
        ToolRegistry 执行 search 工具时，最终会走到这里。
        parameters 常见格式：
        {"input": "多模态模型最新进展"}
        返回固定格式：
        {
            "backend": "duckduckgo",
            "results": [
                {"title": "...", "url": "...", "content": "..."}
            ],
            "notices": []
        }
        """
        requested_backend = str(
            parameters.get("backend", self.config.default_search_backend)
        ).lower()

        query = parameters.get("input") or ""
        if not query:
            return {
                "backend": requested_backend,
                "results": [],
                "notices": ["搜索问题为空"],
            }

        max_results = int(parameters.get("max_results", self.config.search_max_results))
        fetch_full_page = parameters.get("fetch_full_page", self.config.fetch_full_page)
        max_tokens = int(
            parameters.get(
                "max_tokens_per_source",
                self.config.max_tokens_per_source,
            )
        )
        timeout_seconds = int(
            parameters.get(
                "timeout_seconds",
                self.config.search_timeout_seconds,
            )
        )
        requested_backend = parameters.get(
            "backend",
            self.config.default_search_backend,
        ).lower()
        backend = self.check_backend(requested_backend)

        mode = parameters.get("mode", "text").lower()
        if mode not in SUPPORTED_RETURN_MODES:
            mode = "text"

        # 深度研究强调资料时效性，每次执行都发起真实搜索请求。
        search_results = self._structured_search(
            query=query,
            backend=backend,
            max_results=max_results,
            max_tokens=max_tokens,
            fetch_full_page=fetch_full_page,
            timeout_seconds=timeout_seconds,
        )

        if requested_backend != backend:
            search_results.setdefault("notices", []).append(
                f"请求的搜索后端 {requested_backend} 不可用，已降级为 {backend}"
            )

        if mode in ["structured", "dict", "json"]:
            return search_results

        return self._format_text_response(query, search_results)

    def get_parameters(self) -> dict[str, Any]:
        """描述这个工具需要什么参数。"""
        return {
            "input": "搜索的问题",
            "mode": "structured",
            "max_results": self.config.search_max_results,
            "fetch_full_page": self.config.fetch_full_page,
            "max_tokens_per_source": self.config.max_tokens_per_source,
            "timeout_seconds": self.config.search_timeout_seconds,
            "backend": self.config.default_search_backend,
        }

    def get_function_schema(self) -> dict[str, Any]:
        """返回 SearchTool 的原生 Function Calling 描述。

        Deep Research 第一版不会把这些底层运行参数全部暴露给模型；真正注册给
        FunctionCallingAgent 的是约束更窄的 SupplementalSearchTool。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": SearchToolArguments.model_json_schema(),
            },
        }

    def _structured_search(
            self,
            query: str,
            backend: str,
            max_results: int,
            max_tokens: int,
            fetch_full_page: bool,
            timeout_seconds: int,
    ) -> dict[str, Any]:
        """执行结构化搜索，并返回统一 dict。"""
        search_request = SearchRequest(
            query=query,
            max_results=max_results,
            max_tokens=max_tokens,
            fetch_full_page=fetch_full_page,
            timeout_seconds=timeout_seconds,
        )
        if backend == "hybrid":
            return self._search_hybrid(search_request)

        search_result = self.backends[backend].search(search_request)
        if backend in ["tavily", "serpapi"]:
            return self._fallback_to_duckduckgo_if_empty(search_result, search_request)

        return search_result

    def _search_hybrid(
            self,
            request: SearchRequest
    ) -> dict[str, Any]:
        """按优先级执行 hybrid 搜索。

        优先 Tavily，其次 SerpApi，最后 DuckDuckGo。
        这样有 API Key 时优先质量更高的后端，没有 Key 时本地演示仍然能跑。
        """
        notices = []

        # 优先 tavily搜索
        tavily_backend = self.backends["tavily"]
        if tavily_backend.is_available():
            search_result = tavily_backend.search(request)
            if search_result.get("results"):
                return search_result
            notices.extend(search_result.get("notices") or [])
        else:
            notices.append("未配置 TAVILY_API_KEY 或 Tavily 依赖不可用，跳过 Tavily")

        # 其次serpapi搜索
        serpapi_backend = self.backends["serpapi"]
        if serpapi_backend.is_available():
            search_result = serpapi_backend.search(request)
            if search_result.get("results"):
                search_result.setdefault("notices", []).extend(notices)
                return search_result
            notices.extend(search_result.get("notices") or [])
        else:
            notices.append("未配置 SERPAPI_API_KEY 或 SerpApi 依赖不可用，跳过 SerpApi")

        # duckduckgo 搜索兜底
        fallback = self.backends["duckduckgo"].search(request)
        fallback_notices = notices + ["已使用 DuckDuckGo 作为搜索兜底"]
        fallback_notices.extend(fallback.get("notices") or [])
        return {
            **fallback,
            "notices": fallback_notices,
        }

    def _fallback_to_duckduckgo_if_empty(
            self,
            search_result: dict[str, Any],
            request: SearchRequest,
    ) -> dict[str, Any]:
        """指定后端无结果时，用 DuckDuckGo 做最后兜底。

        比如用户显式选择 Tavily/SerpApi，但对应 key 缺失、接口报错或结果为空，
        这里会尝试 DuckDuckGo，并把降级原因写进 notices 给 Trace 展示。
        """
        if search_result.get("results"):
            return search_result

        primary_backend = search_result.get("backend", "unknown")
        fallback = self.backends["duckduckgo"].search(request)
        fallback_notices = search_result.get("notices") or []
        fallback_notices.append(f"{primary_backend} 未返回可用结果，已尝试 DuckDuckGo 兜底")
        fallback_notices.extend(fallback.get("notices") or [])

        if fallback.get("results"):
            self.logger.info(
                "fallback search succeeded primary=%s fallback=duckduckgo query=%s",
                primary_backend,
                request.query,
            )
            return {
                **fallback,
                "notices": fallback_notices,
            }

        self.logger.warning("all search backends failed query=%s", request.query)
        return {
            **search_result,
            "notices": fallback_notices,
        }

    @staticmethod
    def _format_text_response(query, payload: str | dict[str, Any]) -> str:
        """
        把结构化搜索结果转成一段文本。
        summarizer 更适合吃这种格式：
        [1] 标题
            摘要
            来源：URL
        """
        if not isinstance(payload, dict):
            return payload

        lines = [
            f"搜索关键词：{query}",
            f"搜索后端：{payload.get('backend', 'unknown')}",
            "",
            "参考来源：",
        ]

        results = payload.get("results") or []

        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue

            title = item.get("title") or ""
            url = item.get("url") or ""
            content = item.get("content") or ""
            score = item.get("score")
            reasons = item.get("reasons") or []
            source_type = item.get("source_type") or "unknown"
            source_id = item.get("source_id")
            if source_id:
                lines.append(f"[{source_id}]. {title}")
                lines.append(f"来源ID：{source_id}")
            else:
                lines.append(f"[{index}]. {title}")
            lines.append(f"来源类型：{source_type}")

            if score is not None:
                lines.append(f"来源质量评分: {score}/100")
            if reasons:
                lines.append(f"来源质量判断：{';'.join(reasons)}")
            if url:
                lines.append(f"来源：{url}")
            if content:
                lines.append(f"摘要：{content}")

        notices = payload.get("notices") or []
        if notices:
            lines.append("注意事项：")
            for notice in notices:
                if notice:
                    lines.append(f"- {notice}")

        return "\n\n".join(lines)
