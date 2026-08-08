import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.runner import (
    build_latest_report,
    extract_case_metrics,
    iter_sse_messages,
    load_cases,
    run_case,
    summarize_run,
)


class BenchmarkRunnerTest(unittest.TestCase):
    def test_fixed_case_set_contains_six_unique_questions(self):
        cases = load_cases(ROOT_DIR / "benchmarks" / "cases.json")

        self.assertEqual(len(cases), 6)
        self.assertEqual(len({case["case_id"] for case in cases}), 6)
        self.assertTrue(all(case["topic"] for case in cases))

    def test_iter_sse_messages_parses_backend_event(self):
        lines = [
            "id: 1",
            "event: research_event",
            'data: {"type":"workflow_started","payload":{}}',
            "",
        ]

        messages = list(iter_sse_messages(lines))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], "1")
        self.assertEqual(messages[0]["event"], "research_event")
        self.assertEqual(messages[0]["data"]["type"], "workflow_started")

    def test_extract_case_metrics_maps_result_fields(self):
        result = {
            "tasks": [
                {
                    "status": "completed",
                    "summary": "a" * 100,
                    "search_results": [
                        {"url": "https://www.example.com/a"},
                        {"url": "https://example.com/b"},
                    ],
                },
                {
                    "status": "completed",
                    "summary": "b" * 200,
                    "search_results": [
                        {"url": "https://docs.example.org/page"},
                    ],
                },
            ],
            "report": "# 报告\n正文",
            "llm_usage": {
                "available": True,
                "request_count": 4,
                "prompt_tokens": 1000,
                "completion_tokens": 400,
                "total_tokens": 1400,
                "cached_tokens": 100,
                "reasoning_tokens": 20,
                "by_stage": {
                    "planner": {
                        "request_count": 1,
                        "prompt_tokens": 200,
                        "completion_tokens": 50,
                        "total_tokens": 250,
                        "cached_tokens": 0,
                        "reasoning_tokens": 0,
                    }
                },
                "cost": {
                    "calculated": True,
                    "estimated": 0.0123,
                    "currency": "CNY",
                },
            },
            "evaluator": {
                "overall_score": 95,
                "citation_precision": 1.0,
                "citation_recall": 0.8,
                "primary_source_ratio": 0.5,
                "weak_source_ratio": 0.25,
                "unique_domain_count": 2,
                "max_domain_concentration": 0.5,
                "hard_error_count": 0,
                "quality_warning_count": 1,
                "warnings": ["一个提示"],
            },
        }

        metrics = extract_case_metrics(
            case_id="rag_hallucination",
            result=result,
            elapsed_seconds=270.123,
            event_count=42,
        )

        self.assertTrue(metrics["success"])
        self.assertEqual(metrics["task_count"], 2)
        self.assertEqual(metrics["completed_task_count"], 2)
        self.assertEqual(metrics["source_count"], 3)
        self.assertEqual(metrics["unique_domain_count"], 2)
        self.assertEqual(metrics["average_summary_chars"], 150)
        self.assertEqual(metrics["overall_score"], 95)
        self.assertEqual(metrics["citation_precision"], 1.0)
        self.assertEqual(metrics["citation_recall"], 0.8)
        self.assertEqual(metrics["primary_source_ratio"], 0.5)
        self.assertEqual(metrics["weak_source_ratio"], 0.25)
        self.assertEqual(metrics["evaluator_unique_domain_count"], 2)
        self.assertEqual(metrics["max_domain_concentration"], 0.5)
        self.assertEqual(metrics["hard_error_count"], 0)
        self.assertEqual(metrics["quality_warning_count"], 1)
        self.assertEqual(metrics["warning_count"], 1)
        self.assertTrue(metrics["llm_usage_available"])
        self.assertEqual(metrics["llm_request_count"], 4)
        self.assertEqual(metrics["total_tokens"], 1400)
        self.assertEqual(metrics["estimated_cost"], 0.0123)
        self.assertEqual(
            metrics["llm_usage_by_stage"]["planner"]["total_tokens"],
            250,
        )

    def test_run_case_saves_events_result_and_report(self):
        final_result = {
            "tasks": [
                {
                    "status": "completed",
                    "summary": "任务总结",
                    "search_results": [{"url": "https://example.com"}],
                }
            ],
            "report": "# 最终报告\n\n研究完成。",
            "evaluator": {"overall_score": 90, "warnings": []},
        }

        def fake_stream(**_kwargs):
            yield {
                "id": "1",
                "event": "research_event",
                "data": {"type": "workflow_started", "payload": {}},
            }
            yield {
                "id": "2",
                "event": "research_event",
                "data": {
                    "type": "workflow_done",
                    "payload": {"result": final_result},
                },
            }

        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            metrics = run_case(
                case={
                    "case_id": "test_case",
                    "topic": "测试问题",
                    "description": "",
                },
                run_dir=run_dir,
                base_url="http://127.0.0.1:8000",
                backend="hybrid",
                connect_timeout=1,
                read_timeout=1,
                stream_factory=fake_stream,
            )

            snapshot = json.loads(
                (run_dir / "test_case.json").read_text(encoding="utf-8")
            )
            event_lines = (
                run_dir / "test_case_events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            report = (
                run_dir / "test_case_report.md"
            ).read_text(encoding="utf-8")

        self.assertTrue(metrics["success"])
        self.assertEqual(len(event_lines), 2)
        self.assertEqual(snapshot["result"]["report"], final_result["report"])
        self.assertEqual(report, final_result["report"])

    def test_summary_and_markdown_compare_two_runs(self):
        cases = [
            {
                "case_id": "a",
                "success": True,
                "elapsed_seconds": 100,
                "task_count": 4,
                "completed_task_count": 4,
                "source_count": 20,
                "unique_domain_count": 10,
                "average_summary_chars": 2000,
                "report_chars": 8000,
                "overall_score": 95,
                "primary_source_ratio": 0.5,
                "weak_source_ratio": 0.25,
                "max_domain_concentration": 0.4,
                "hard_error_count": 0,
                "quality_warning_count": 1,
                "warning_count": 1,
                "llm_usage_available": True,
                "llm_request_count": 6,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
                "estimated_cost": 0.01,
                "llm_usage_by_stage": {
                    "planner": {
                        "request_count": 1,
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                        "cached_tokens": 0,
                        "reasoning_tokens": 0,
                    }
                },
                "function_calling_attempt_count": 2,
                "tool_call_count": 2,
                "tool_parameter_valid_count": 2,
                "tool_execution_success_count": 1,
                "supplemental_search_success_count": 1,
                "rule_retry_count": 1,
                "rule_fallback_count": 1,
            },
            {
                "case_id": "failed",
                "success": False,
                "elapsed_seconds": 1,
                "task_count": 0,
                "completed_task_count": 0,
                "source_count": 0,
                "unique_domain_count": 0,
                "average_summary_chars": 0,
                "report_chars": 0,
                "overall_score": None,
                "hard_error_count": 0,
                "quality_warning_count": 0,
                "warning_count": 0,
                "error": "连接失败",
            },
        ]
        current = {
            "run_id": "current",
            "backend": "hybrid",
            "summary": summarize_run(cases),
            "cases": cases,
        }
        previous_cases = [
            dict(cases[0], elapsed_seconds=120, overall_score=90),
            cases[1],
        ]
        previous = {
            "run_id": "previous",
            "summary": summarize_run(previous_cases),
        }

        report = build_latest_report(
            run_metrics=current,
            previous_metrics=previous,
        )

        self.assertIn("current", report)
        self.assertIn("previous", report)
        self.assertIn("-16.7%", report)
        self.assertIn("+5.0", report)
        self.assertIn("主来源占比", report)
        self.assertEqual(current["summary"]["average_primary_source_ratio"], 0.5)
        self.assertEqual(current["summary"]["quality_warning_count"], 1)
        self.assertEqual(current["summary"]["average_elapsed_seconds"], 100)
        self.assertEqual(current["summary"]["p50_elapsed_seconds"], 100)
        self.assertEqual(current["summary"]["p95_elapsed_seconds"], 100)
        self.assertEqual(current["summary"]["total_tokens"], 1500)
        self.assertEqual(current["summary"]["tool_parameter_accuracy"], 1.0)
        self.assertEqual(
            current["summary"]["supplemental_search_success_rate"],
            0.5,
        )
        self.assertEqual(current["summary"]["rule_fallback_rate"], 0.5)
        self.assertIn("延迟分布", report)
        self.assertIn("Tool 参数正确率", report)


if __name__ == "__main__":
    unittest.main()
