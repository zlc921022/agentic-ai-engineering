import sys
import unittest
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.core.config import Config
from backend.search.search_backends import SearchRequest
from backend.search.search_tool import SearchTool


class FakeBackend:
    """可控搜索后端，避免 SearchTool 测试依赖真实网络。"""

    def __init__(
            self,
            name: str,
            *,
            available: bool = True,
            results: list[dict[str, Any]] | None = None,
            notices: list[str] | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.results = results or []
        self.notices = notices or [f"{name} notice"]
        self.calls: list[SearchRequest] = []

    def is_available(self) -> bool:
        return self.available

    def search(self, request: SearchRequest) -> dict[str, Any]:
        self.calls.append(request)
        return {
            "backend": self.name,
            "results": self.results,
            "notices": list(self.notices),
        }


class SearchToolTest(unittest.TestCase):
    def _build_tool(
            self,
            *,
            tavily: FakeBackend | None = None,
            serpapi: FakeBackend | None = None,
            duckduckgo: FakeBackend | None = None,
    ) -> SearchTool:
        tool = SearchTool(
            Config.from_env(
                tavily_api_key="fake-tavily-key",
                serpapi_api_key="fake-serpapi-key",
                default_search_backend="hybrid",
                search_max_results=3,
                search_timeout_seconds=12,
                fetch_full_page=False,
                max_tokens_per_source=100,
            )
        )
        tool.backends = {
            "tavily": tavily or FakeBackend("tavily"),
            "serpapi": serpapi or FakeBackend("serpapi"),
            "duckduckgo": duckduckgo or FakeBackend("duckduckgo"),
        }
        return tool

    def test_empty_query_returns_without_calling_backend(self):
        tavily = FakeBackend("tavily")
        duckduckgo = FakeBackend("duckduckgo")
        tool = self._build_tool(tavily=tavily, duckduckgo=duckduckgo)

        result = tool.run({
            "input": "",
            "backend": "tavily",
            "mode": "structured",
        })

        self.assertEqual(
            result,
            {
                "backend": "tavily",
                "results": [],
                "notices": ["搜索问题为空"],
            },
        )
        self.assertEqual(tavily.calls, [])
        self.assertEqual(duckduckgo.calls, [])

    def test_explicit_backend_empty_result_falls_back_to_duckduckgo(self):
        tavily = FakeBackend("tavily", results=[], notices=["tavily empty"])
        duckduckgo = FakeBackend(
            "duckduckgo",
            results=[
                {
                    "title": "Duck result",
                    "url": "https://example.com/duck",
                    "content": "fallback content",
                }
            ],
            notices=["duck notice"],
        )
        tool = self._build_tool(tavily=tavily, duckduckgo=duckduckgo)

        result = tool.run({
            "input": "rag evaluation",
            "backend": "tavily",
            "mode": "structured",
        })

        self.assertEqual(result["backend"], "duckduckgo")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(len(tavily.calls), 1)
        self.assertEqual(len(duckduckgo.calls), 1)
        self.assertIn("tavily empty", result["notices"])
        self.assertIn("tavily 未返回可用结果，已尝试 DuckDuckGo 兜底", result["notices"])
        self.assertIn("duck notice", result["notices"])

    def test_hybrid_uses_first_available_backend_with_results(self):
        tavily = FakeBackend(
            "tavily",
            results=[
                {
                    "title": "Tavily result",
                    "url": "https://example.com/tavily",
                    "content": "tavily content",
                }
            ],
        )
        serpapi = FakeBackend("serpapi")
        duckduckgo = FakeBackend("duckduckgo")
        tool = self._build_tool(
            tavily=tavily,
            serpapi=serpapi,
            duckduckgo=duckduckgo,
        )

        result = tool.run({
            "input": "rag evaluation",
            "backend": "hybrid",
            "mode": "structured",
        })

        self.assertEqual(result["backend"], "tavily")
        self.assertEqual(len(tavily.calls), 1)
        self.assertEqual(serpapi.calls, [])
        self.assertEqual(duckduckgo.calls, [])

    def test_unavailable_explicit_backend_degrades_to_hybrid(self):
        tavily = FakeBackend("tavily", available=False)
        serpapi = FakeBackend("serpapi", available=False)
        duckduckgo = FakeBackend(
            "duckduckgo",
            results=[
                {
                    "title": "Duck result",
                    "url": "https://example.com/duck",
                    "content": "fallback content",
                }
            ],
            notices=[],
        )
        tool = self._build_tool(
            tavily=tavily,
            serpapi=serpapi,
            duckduckgo=duckduckgo,
        )

        result = tool.run({
            "input": "rag evaluation",
            "backend": "tavily",
            "mode": "structured",
        })

        self.assertEqual(result["backend"], "duckduckgo")
        self.assertEqual(tavily.calls, [])
        self.assertEqual(serpapi.calls, [])
        self.assertEqual(len(duckduckgo.calls), 1)
        self.assertTrue(
            any("已降级为 hybrid" in notice for notice in result["notices"])
        )

    def test_search_request_carries_timeout_seconds(self):
        tavily = FakeBackend(
            "tavily",
            results=[
                {
                    "title": "Tavily result",
                    "url": "https://example.com/tavily",
                    "content": "tavily content",
                }
            ],
        )
        tool = self._build_tool(tavily=tavily)

        tool.run({
            "input": "rag evaluation",
            "backend": "tavily",
            "mode": "structured",
        })

        self.assertEqual(len(tavily.calls), 1)
        self.assertEqual(tavily.calls[0].timeout_seconds, 12)


if __name__ == "__main__":
    unittest.main()
