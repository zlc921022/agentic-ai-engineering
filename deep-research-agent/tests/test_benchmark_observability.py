import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.observability import (
    SseTraceAnalyzer,
    latency_distribution,
    percentile,
)


class BenchmarkObservabilityTest(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self):
        samples = [10, 20, 30, 40, 50]

        self.assertEqual(percentile(samples, 50), 30)
        self.assertEqual(percentile(samples, 95), 50)
        self.assertIsNone(percentile([], 99))

    def test_analyzer_builds_trace_and_parallel_stage_latency(self):
        analyzer = SseTraceAnalyzer()
        events = [
            self.event(1, "workflow_started", 100.0),
            self.event(2, "planner_done", 101.0),
            self.event(3, "task_started", 102.0, task_id=1),
            self.event(4, "task_started", 102.1, task_id=2),
            self.event(5, "task_sources_done", 103.0, task_id=1),
            self.event(6, "task_sources_done", 104.1, task_id=2),
            self.event(7, "task_summary_started", 104.2, task_id=1),
            self.event(8, "task_summary_done", 105.2, task_id=1),
            self.event(9, "report_started", 106.0),
            self.event(10, "report_done", 108.0),
            self.event(11, "workflow_done", 108.1),
        ]
        for event in events:
            analyzer.observe(event)

        summary = analyzer.summary()

        self.assertEqual(summary["trace_id"], "run-1")
        self.assertTrue(summary["trace_complete"])
        self.assertEqual(
            summary["stage_samples_ms"]["searcher"],
            [1000.0, 2000.0],
        )
        self.assertEqual(summary["stage_latency_ms"]["searcher"]["p95"], 2000)
        self.assertEqual(summary["stage_latency_ms"]["workflow"]["p50"], 8100)

    def test_analyzer_marks_sequence_gap_as_incomplete(self):
        analyzer = SseTraceAnalyzer()
        analyzer.observe(self.event(1, "workflow_started", 100.0))
        analyzer.observe(self.event(3, "workflow_done", 101.0))

        summary = analyzer.summary()

        self.assertFalse(summary["trace_complete"])
        self.assertEqual(summary["trace_missing_sequences"], [2])

    def test_latency_distribution_contains_required_percentiles(self):
        distribution = latency_distribution([100, 200, 300, 400])

        self.assertEqual(distribution["count"], 4)
        self.assertEqual(distribution["p50"], 200)
        self.assertEqual(distribution["p95"], 400)
        self.assertEqual(distribution["p99"], 400)

    def test_analyzer_aggregates_function_calling_search_observation(self):
        analyzer = SseTraceAnalyzer()
        analyzer.observe(
            self.event(
                1,
                "task_sources_done",
                100.0,
                task_id=1,
                payload={
                    "search_observation": {
                        "retry_triggered": True,
                        "function_calling_attempted": True,
                        "tool_call_count": 1,
                        "tool_parameter_valid_count": 1,
                        "tool_execution_success_count": 1,
                        "supplemental_search_success": True,
                        "rule_retry_used": False,
                        "fallback_used": False,
                        "tool_duration_ms": [120],
                    }
                },
            )
        )
        analyzer.observe(
            self.event(
                2,
                "task_sources_done",
                101.0,
                task_id=2,
                payload={
                    "search_observation": {
                        "retry_triggered": True,
                        "function_calling_attempted": True,
                        "tool_call_count": 1,
                        "tool_parameter_valid_count": 0,
                        "tool_execution_success_count": 0,
                        "supplemental_search_success": False,
                        "rule_retry_used": True,
                        "fallback_used": True,
                        "tool_duration_ms": [300],
                    }
                },
            )
        )

        summary = analyzer.summary()

        self.assertEqual(summary["tool_call_count"], 2)
        self.assertEqual(summary["tool_parameter_accuracy"], 0.5)
        self.assertEqual(summary["tool_execution_success_rate"], 0.5)
        self.assertEqual(summary["supplemental_search_success_rate"], 0.5)
        self.assertEqual(summary["rule_fallback_rate"], 0.5)
        self.assertEqual(summary["tool_duration_ms"]["p95"], 300)

    @staticmethod
    def event(
        sequence: int,
        event_type: str,
        timestamp: float,
        *,
        task_id: int | None = None,
        payload: dict | None = None,
    ) -> dict:
        return {
            "run_id": "run-1",
            "seq": sequence,
            "type": event_type,
            "task_id": task_id,
            "timestamp": timestamp,
            "payload": payload or {},
        }


if __name__ == "__main__":
    unittest.main()
