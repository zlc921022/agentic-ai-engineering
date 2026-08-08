"""检查 Deep Research Benchmark 是否越过绝对阈值或相对基线。

真实模型评测具有成本和随机性，因此这个脚本不在每次普通单元测试中调用外部
服务。它只读取已经生成的 metrics.json，适合手动评测或定时 CI 使用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_THRESHOLDS_FILE = BENCHMARK_DIR / "regression_thresholds.json"


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 JSON object。")
    return data


def evaluate_gates(
    current_metrics: dict[str, Any],
    thresholds: dict[str, Any],
    baseline_metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """返回逐项 Gate 结果；没有 baseline 时只检查绝对阈值。"""
    current = current_metrics.get("summary")
    if not isinstance(current, dict):
        raise ValueError("当前 metrics.json 缺少 summary。")
    baseline = (
        baseline_metrics.get("summary")
        if isinstance(baseline_metrics, dict)
        else None
    )
    baseline = baseline if isinstance(baseline, dict) else None

    checks: list[dict[str, Any]] = []
    absolute = thresholds.get("absolute")
    absolute = absolute if isinstance(absolute, dict) else {}
    _minimum_check(
        checks,
        "success_rate",
        current.get("success_rate"),
        absolute.get("min_success_rate"),
    )
    _minimum_check(
        checks,
        "average_overall_score",
        current.get("average_overall_score"),
        absolute.get("min_average_overall_score"),
    )
    _maximum_check(
        checks,
        "hard_error_count",
        current.get("hard_error_count"),
        absolute.get("max_hard_error_count"),
    )
    _minimum_check(
        checks,
        "trace_complete_rate",
        current.get("trace_complete_rate"),
        absolute.get("min_trace_complete_rate"),
    )
    _minimum_check(
        checks,
        "tool_parameter_accuracy",
        current.get("tool_parameter_accuracy"),
        absolute.get("min_tool_parameter_accuracy"),
    )
    _minimum_check(
        checks,
        "supplemental_search_success_rate",
        current.get("supplemental_search_success_rate"),
        absolute.get("min_supplemental_search_success_rate"),
    )
    _maximum_check(
        checks,
        "rule_fallback_rate",
        current.get("rule_fallback_rate"),
        absolute.get("max_rule_fallback_rate"),
    )

    if baseline is None:
        return checks

    relative = thresholds.get("relative")
    relative = relative if isinstance(relative, dict) else {}
    _drop_check(
        checks,
        "success_rate_drop",
        current.get("success_rate"),
        baseline.get("success_rate"),
        relative.get("max_success_rate_drop"),
    )
    _drop_check(
        checks,
        "average_overall_score_drop",
        current.get("average_overall_score"),
        baseline.get("average_overall_score"),
        relative.get("max_average_overall_score_drop"),
    )
    _increase_ratio_check(
        checks,
        "p95_elapsed_increase_ratio",
        current.get("p95_elapsed_seconds"),
        baseline.get("p95_elapsed_seconds"),
        relative.get("max_p95_elapsed_increase_ratio"),
    )
    _increase_ratio_check(
        checks,
        "total_tokens_increase_ratio",
        current.get("total_tokens"),
        baseline.get("total_tokens"),
        relative.get("max_total_tokens_increase_ratio"),
    )
    _increase_ratio_check(
        checks,
        "estimated_cost_increase_ratio",
        current.get("estimated_cost"),
        baseline.get("estimated_cost"),
        relative.get("max_estimated_cost_increase_ratio"),
    )
    return checks


def _minimum_check(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    threshold: Any,
) -> None:
    if not _numbers(actual, threshold):
        return
    checks.append({
        "name": name,
        "passed": actual >= threshold,
        "actual": actual,
        "operator": ">=",
        "threshold": threshold,
    })


def _maximum_check(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    threshold: Any,
) -> None:
    if not _numbers(actual, threshold):
        return
    checks.append({
        "name": name,
        "passed": actual <= threshold,
        "actual": actual,
        "operator": "<=",
        "threshold": threshold,
    })


def _drop_check(
    checks: list[dict[str, Any]],
    name: str,
    current: Any,
    baseline: Any,
    threshold: Any,
) -> None:
    if not _numbers(current, baseline, threshold):
        return
    actual = round(baseline - current, 4)
    checks.append({
        "name": name,
        "passed": actual <= threshold,
        "actual": actual,
        "operator": "<=",
        "threshold": threshold,
    })


def _increase_ratio_check(
    checks: list[dict[str, Any]],
    name: str,
    current: Any,
    baseline: Any,
    threshold: Any,
) -> None:
    if not _numbers(current, baseline, threshold) or baseline <= 0:
        return
    actual = round((current - baseline) / baseline, 4)
    checks.append({
        "name": name,
        "passed": actual <= threshold,
        "actual": actual,
        "operator": "<=",
        "threshold": threshold,
    })


def _numbers(*values: Any) -> bool:
    return all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in values
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 Benchmark 回归门禁。")
    parser.add_argument("current", type=Path, help="本次 metrics.json。")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="可选的基线 metrics.json；不传时只检查绝对阈值。",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=DEFAULT_THRESHOLDS_FILE,
        help="回归阈值 JSON。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        current = load_json_object(args.current)
        baseline = load_json_object(args.baseline) if args.baseline else None
        thresholds = load_json_object(args.thresholds)
        checks = evaluate_gates(current, thresholds, baseline)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"回归门禁读取失败：{exc}", file=sys.stderr)
        return 2

    if not checks:
        print("没有可执行的回归阈值。", file=sys.stderr)
        return 2

    for check in checks:
        status = "PASS" if check["passed"] else "FAIL"
        print(
            f"[{status}] {check['name']}: actual={check['actual']} "
            f"{check['operator']} threshold={check['threshold']}"
        )
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
