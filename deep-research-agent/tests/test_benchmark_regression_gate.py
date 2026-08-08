import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.regression_gate import evaluate_gates


class BenchmarkRegressionGateTest(unittest.TestCase):
    def test_absolute_and_relative_gates_pass(self):
        current = {
            "summary": {
                "success_rate": 1.0,
                "average_overall_score": 90,
                "hard_error_count": 0,
                "trace_complete_rate": 1.0,
                "p95_elapsed_seconds": 120,
            }
        }
        baseline = {
            "summary": {
                "success_rate": 1.0,
                "average_overall_score": 92,
                "p95_elapsed_seconds": 100,
            }
        }
        checks = evaluate_gates(
            current,
            {
                "absolute": {
                    "min_success_rate": 1.0,
                    "min_average_overall_score": 80,
                    "max_hard_error_count": 0,
                    "min_trace_complete_rate": 1.0,
                },
                "relative": {
                    "max_success_rate_drop": 0,
                    "max_average_overall_score_drop": 5,
                    "max_p95_elapsed_increase_ratio": 0.35,
                },
            },
            baseline,
        )

        self.assertTrue(all(check["passed"] for check in checks))
        self.assertEqual(len(checks), 7)

    def test_gate_reports_quality_and_latency_regression(self):
        current = {
            "summary": {
                "success_rate": 0.8,
                "average_overall_score": 70,
                "hard_error_count": 2,
                "trace_complete_rate": 0.8,
                "p95_elapsed_seconds": 150,
            }
        }
        baseline = {
            "summary": {
                "success_rate": 1.0,
                "average_overall_score": 90,
                "p95_elapsed_seconds": 100,
            }
        }
        checks = evaluate_gates(
            current,
            {
                "absolute": {
                    "min_success_rate": 1.0,
                    "min_average_overall_score": 80,
                    "max_hard_error_count": 0,
                    "min_trace_complete_rate": 1.0,
                },
                "relative": {
                    "max_success_rate_drop": 0,
                    "max_average_overall_score_drop": 5,
                    "max_p95_elapsed_increase_ratio": 0.35,
                },
            },
            baseline,
        )

        failed_names = {
            check["name"] for check in checks if not check["passed"]
        }
        self.assertIn("success_rate", failed_names)
        self.assertIn("average_overall_score_drop", failed_names)
        self.assertIn("p95_elapsed_increase_ratio", failed_names)

    def test_tool_and_cost_gates_only_run_when_metrics_exist(self):
        current = {
            "summary": {
                "success_rate": 1.0,
                "tool_parameter_accuracy": 0.5,
                "supplemental_search_success_rate": 0.5,
                "rule_fallback_rate": 0.5,
                "total_tokens": 1400,
                "estimated_cost": 1.4,
            }
        }
        baseline = {
            "summary": {
                "success_rate": 1.0,
                "total_tokens": 1000,
                "estimated_cost": 1.0,
            }
        }
        checks = evaluate_gates(
            current,
            {
                "absolute": {
                    "min_tool_parameter_accuracy": 1.0,
                    "min_supplemental_search_success_rate": 0.8,
                    "max_rule_fallback_rate": 0.2,
                },
                "relative": {
                    "max_total_tokens_increase_ratio": 0.3,
                    "max_estimated_cost_increase_ratio": 0.3,
                },
            },
            baseline,
        )

        failed_names = {
            check["name"] for check in checks if not check["passed"]
        }
        self.assertEqual(
            failed_names,
            {
                "tool_parameter_accuracy",
                "supplemental_search_success_rate",
                "rule_fallback_rate",
                "total_tokens_increase_ratio",
                "estimated_cost_increase_ratio",
            },
        )


if __name__ == "__main__":
    unittest.main()
