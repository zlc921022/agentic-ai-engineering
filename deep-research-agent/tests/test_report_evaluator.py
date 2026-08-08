import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.services.report_evaluator import ReportEvaluatorService


class ReportEvaluatorTest(unittest.TestCase):
    def setUp(self):
        self.evaluator = ReportEvaluatorService()

    def test_source_title_year_is_not_old_citation(self):
        """参考文献和证据表标题中的 [2026] 不应被当成旧式引用。"""
        report = """# RAG 报告

## 关键结论

RAG 需要持续评估 [T1-S1]。

## 参考文献

[T1-S1] 12 Advanced RAG Techniques [2026] - https://example.com/rag

## 证据表

| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |
|---|---|---|---|---:|---|---|
| T1-S1 | RAG | 12 Advanced RAG Techniques [2026] | official_doc | 90 | strong | https://example.com/rag |
"""

        result = self.evaluator.run(report)

        self.assertFalse(
            any("发现旧式引用编号" in warning for warning in result["warnings"])
        )
        self.assertEqual(result["citation_score"], 100)

    def test_legacy_citation_in_body_is_still_reported(self):
        """正文中的 [1] 仍然属于需要迁移的旧式引用。"""
        report = """# RAG 报告

## 关键结论

RAG 需要持续评估 [1]。

## 参考文献

[1] RAG Evaluation - https://example.com/rag

## 证据表

| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |
|---|---|---|---|---:|---|---|
| T1-S1 | RAG | RAG Evaluation | official_doc | 90 | strong | https://example.com/rag |
"""

        result = self.evaluator.run(report)

        self.assertTrue(
            any("[1]" in warning for warning in result["warnings"])
        )
        self.assertEqual(result["citation_score"], 35)

    def test_four_digit_brackets_in_body_are_not_legacy_citations(self):
        """正文提到年份 [2026] 时也不应触发旧引用告警。"""
        report = "研究范围覆盖 [2026] 年发布的资料。"

        self.assertEqual(self.evaluator.extract_old_citations(report), [])

    def test_grouped_citations_are_supported(self):
        """同一方括号中的多个来源 ID 都应被识别。"""
        citations = self.evaluator.extract_citations(
            "结论由多个来源支持 [T1-S1, T1-S2, T2-S3]。"
        )

        self.assertEqual(
            citations,
            ["T1-S1", "T1-S2", "T2-S3"],
        )

    def test_only_body_citations_are_counted(self):
        """参考文献和证据表中的 ID 不能替正文增加引用数量。"""
        report = """# RAG 报告

## 关键结论

混合引用可以共同支撑一个结论 [T1-S1, T1-S2]。

## 参考文献

[T1-S1] 来源一 - https://example.com/1
[T1-S2] 来源二 - https://example.com/2
[T1-S3] 未使用来源 - https://example.com/3

## 证据表

| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |
|---|---|---|---|---:|---|---|
| T1-S1 | RAG | 来源一 | official_doc | 90 | strong | https://example.com/1 |
| T1-S2 | RAG | 来源二 | academic | 90 | strong | https://example.com/2 |
| T1-S3 | RAG | 未使用来源 | academic | 90 | strong | https://example.com/3 |
"""

        result = self.evaluator.run(report)

        self.assertEqual(result["citations_count"], 2)
        self.assertEqual(result["unique_citations_count"], 2)
        self.assertEqual(result["reference_sources_count"], 3)
        self.assertEqual(result["evidence_sources_count"], 3)
        self.assertEqual(result["citation_score"], 100)
        self.assertEqual(result["hard_error_count"], 0)
        self.assertEqual(result["quality_warning_count"], 1)
        self.assertEqual(result["citation_precision"], 1.0)
        self.assertEqual(result["citation_recall"], 0.6667)
        self.assertTrue(
            any("T1-S3" in warning for warning in result["warnings"])
        )

    def test_body_citation_must_exist_in_references_and_evidence(self):
        """正文中的未知引用应同时触发证据表和参考文献一致性告警。"""
        report = """# RAG 报告

## 关键结论

结论使用了未知来源 [T9-S9]。

## 参考文献

[T1-S1] 来源一 - https://example.com/1

## 证据表

| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |
|---|---|---|---|---:|---|---|
| T1-S1 | RAG | 来源一 | official_doc | 90 | strong | https://example.com/1 |
"""

        result = self.evaluator.run(report)

        self.assertEqual(result["citation_score"], 60)
        self.assertEqual(result["hard_error_count"], 2)
        self.assertEqual(result["quality_warning_count"], 1)
        self.assertEqual(result["citation_precision"], 0.0)
        self.assertEqual(result["citation_recall"], 0.0)
        self.assertTrue(
            any("未出现在证据表" in warning for warning in result["warnings"])
        )
        self.assertTrue(
            any("未列入参考文献" in warning for warning in result["warnings"])
        )

    def test_source_structure_metrics_are_exposed(self):
        """把证据表压缩成来源结构指标，方便 benchmark 做版本对比。"""
        report = """# AI Agent 报告

## 关键结论

多类来源共同支撑结论 [T1-S1, T1-S2, T1-S3, T1-S4]。

## 参考文献

[T1-S1] 官方文档 - https://docs.example.com/a
[T1-S2] 论文 - https://arxiv.org/abs/1
[T1-S3] 企业技术文章 - https://docs.example.com/b
[T1-S4] 社区文章 - https://medium.com/p/test

## 证据表

| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |
|---|---|---|---|---:|---|---|
| T1-S1 | Agent | 官方文档 | official_doc | 95 | strong | https://docs.example.com/a |
| T1-S2 | Agent | 论文 | academic | 90 | strong | https://arxiv.org/abs/1 |
| T1-S3 | Agent | 企业技术文章 | company_tech | 75 | medium | https://docs.example.com/b |
| T1-S4 | Agent | 社区文章 | community | 45 | weak | https://medium.com/p/test |
"""

        result = self.evaluator.run(report)

        self.assertEqual(result["hard_error_count"], 0)
        self.assertEqual(result["quality_warning_count"], 0)
        self.assertEqual(result["primary_source_ratio"], 0.5)
        self.assertEqual(result["weak_source_ratio"], 0.25)
        self.assertEqual(result["unique_domain_count"], 3)
        self.assertEqual(result["max_domain_concentration"], 0.5)


if __name__ == "__main__":
    unittest.main()
