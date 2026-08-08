import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.services.source_quality import SourceQualityConfig, SourceQualityService


class SourceQualityServiceTest(unittest.TestCase):
    def test_diverse_selection_limits_same_domain_when_possible(self):
        """候选足够时，同一域名不会挤占全部来源位。"""
        service = SourceQualityService(keep_results=5, max_per_domain=2)
        content = (
            "RAG evaluation architecture retrieval generation citation "
            "benchmark evidence quality source governance production practice. "
            "This summary is intentionally long enough for source scoring."
        )
        search_results = {
            "backend": "fake",
            "results": [
                {
                    "title": f"RAG evaluation architecture doc {index}",
                    "url": f"https://docs.example.com/rag/{index}",
                    "content": content,
                }
                for index in range(3)
            ] + [
                {
                    "title": "RAG evaluation architecture practice one",
                    "url": "https://practice-one.example.com/rag-evaluation",
                    "content": content,
                },
                {
                    "title": "RAG evaluation architecture practice two",
                    "url": "https://practice-two.example.com/rag-evaluation",
                    "content": content,
                },
                {
                    "title": "RAG evaluation architecture practice three",
                    "url": "https://practice-three.example.com/rag-evaluation",
                    "content": content,
                },
            ],
            "notices": [],
        }

        result = service.process_result(
            "rag evaluation architecture",
            search_results,
        )
        domains = [item["domain"] for item in result["results"]]

        self.assertEqual(len(result["results"]), 5)
        self.assertLessEqual(domains.count("docs.example.com"), 2)
        self.assertTrue(
            any("来源多样性控制" in notice for notice in result["notices"])
        )

    def test_official_source_beats_marketing_page(self):
        """官方/一手资料应明显优先于营销转化页。"""
        service = SourceQualityService()
        official = service.score_item(
            "rag evaluation",
            {
                "title": "RAG evaluation with citations",
                "url": "https://platform.openai.com/docs/guides/rag-evaluation",
                "content": (
                    "RAG evaluation citation source grounding retrieval "
                    "generation benchmark quality production."
                ),
            },
        )
        marketing = service.score_item(
            "rag evaluation",
            {
                "title": "Best RAG tools and alternatives",
                "url": "https://vendor.example.com/solutions/rag-evaluation",
                "content": (
                    "Book a demo and contact sales for our services. "
                    "RAG evaluation tooling for teams."
                ),
            },
        )

        self.assertGreater(official["score"], marketing["score"])
        self.assertIn("原始/一手资料加权", official["reasons"])
        self.assertTrue(
            any("营销" in reason for reason in marketing["reasons"])
        )

    def test_custom_config_controls_filter_threshold(self):
        """过滤阈值可以通过配置调整。"""
        service = SourceQualityService(
            config=SourceQualityConfig(min_score=95, keep_results=5)
        )
        result = service.process_result(
            "rag hallucination evaluation",
            {
                "backend": "fake",
                "results": [
                    {
                        "title": "RAG hallucination evaluation benchmark",
                        "url": "https://example.com/rag-eval",
                        "content": (
                            "RAG hallucination evaluation benchmark evidence "
                            "quality source governance."
                        ),
                    }
                ],
                "notices": [],
            },
        )

        self.assertEqual(result["results"], [])

    def test_custom_config_adds_academic_domain(self):
        """可信域名集合可以通过配置扩展。"""
        service = SourceQualityService(
            config=SourceQualityConfig(
                academic_domains=frozenset({"research.example.com"})
            )
        )

        item = service.score_item(
            "rag hallucination evaluation",
            {
                "title": "RAG hallucination evaluation benchmark",
                "url": "https://research.example.com/paper",
                "content": (
                    "RAG hallucination evaluation benchmark evidence "
                    "quality source governance."
                ),
            },
        )

        self.assertEqual(item["source_type"], "academic")


if __name__ == "__main__":
    unittest.main()
