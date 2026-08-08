import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.domain.models import TodoItem
from backend.core.config import Config
from backend.services.search_service import SearchService


class FakeSearchTool:
    """记录 SearchService 实际发起的搜索请求，避免测试依赖网络。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        query = str(payload["input"])
        index = len(self.calls)
        return {
            "backend": "duckduckgo",
            "notices": [f"fake notice {index}"],
            "results": [
                {
                    "title": f"RAG hallucination official source {index}",
                    "url": f"https://docs{index}.example.com/rag-hallucination",
                    "content": (
                        "RAG hallucination evaluation retrieval generation "
                        "official documentation academic paper production "
                        "risk limitation evidence quality. "
                    ) * 4,
                },
                {
                    "title": f"RAG hallucination academic source {index}",
                    "url": f"https://arxiv.org/abs/000{index}",
                    "content": (
                        "RAG hallucination evaluation retrieval generation "
                        "academic paper benchmark faithfulness answer relevance. "
                    ) * 4,
                },
                {
                    "title": f"RAG hallucination practice source {index}",
                    "url": f"https://practice{index}.example.com/rag",
                    "content": (
                        "RAG hallucination production risk limitation "
                        "guardrails evaluation evidence quality. "
                    ) * 4,
                },
            ],
            "query": query,
        }


class SearchServiceTest(unittest.TestCase):
    def test_multi_query_search_runs_three_queries_and_keeps_configured_count(self):
        """默认多查询会扩大候选池，但最终来源数量仍由 max_results 控制。"""
        fake_tool = FakeSearchTool()
        service = SearchService(fake_tool)  # type: ignore[arg-type]
        task = TodoItem(
            id=1,
            title="RAG 幻觉治理",
            intent="分析 RAG 幻觉治理",
            query="RAG hallucination evaluation",
        )

        result = service.run_search(
            task=task,
            backend="duckduckgo",
            max_results=5,
            enable_multi_query_search=True,
            query_variant_count=3,
        )

        self.assertEqual(len(fake_tool.calls), 3)
        self.assertEqual(
            [call["input"] for call in fake_tool.calls],
            SearchService.build_query_variants(
                "RAG hallucination evaluation",
                enabled=True,
                variant_count=3,
            ),
        )
        self.assertEqual(len(result.results["results"]), 5)
        self.assertTrue(
            all(source.get("source_id") for source in result.results["results"])
        )
        self.assertTrue(
            all(source.get("search_query") for source in result.results["results"])
        )
        self.assertTrue(
            any(
                "多查询检索：3 个 query"
                in notice
                for notice in result.results["notices"]
            )
        )

    def test_disabled_multi_query_search_runs_original_query_only(self):
        """关闭多查询和补检索时，应退回到原来的单 query 行为。"""
        fake_tool = FakeSearchTool()
        service = SearchService(  # type: ignore[arg-type]
            fake_tool,
            Config(enable_search_quality_retry=False),
        )
        task = TodoItem(
            id=2,
            title="RAG 检索",
            intent="分析 RAG 检索",
            query="RAG retrieval recall",
        )

        result = service.run_search(
            task=task,
            backend="duckduckgo",
            max_results=2,
            enable_multi_query_search=False,
            query_variant_count=3,
        )

        self.assertEqual(len(fake_tool.calls), 1)
        self.assertEqual(fake_tool.calls[0]["input"], "RAG retrieval recall")
        self.assertEqual(len(result.results["results"]), 2)


if __name__ == "__main__":
    unittest.main()
