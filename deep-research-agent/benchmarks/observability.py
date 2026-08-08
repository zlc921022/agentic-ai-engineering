"""只基于公开 SSE 事件计算 Trace 完整性和阶段耗时。

这个模块位于 benchmarks 侧，不导入业务 Agent、Service，也不要求业务流程新增
埋点。它把现有 run_id 当作 trace_id，并使用事件中的 timestamp 计算阶段耗时。
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


def percentile(values: Iterable[float | int], percent: float) -> float | None:
    """使用最近秩（nearest-rank）计算分位数，适合延迟/SLO 统计。"""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil((percent / 100) * len(ordered)))
    return round(ordered[min(rank, len(ordered)) - 1], 2)


def latency_distribution(values: Iterable[float | int]) -> dict[str, Any]:
    """生成一组统一的 count/min/avg/P50/P95/P99/max 延迟指标。"""
    samples = [round(float(value), 2) for value in values]
    if not samples:
        return {
            "count": 0,
            "min": None,
            "average": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(samples),
        "min": min(samples),
        "average": round(sum(samples) / len(samples), 2),
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "p99": percentile(samples, 99),
        "max": max(samples),
    }


class SseTraceAnalyzer:
    """在 Benchmark 客户端侧观察一条 SSE 流，不侵入后端业务代码。

    支持的阶段：
    - planner：workflow_started -> planner_done；
    - searcher：task_started -> task_sources_done；
    - summary：task_summary_started -> task_summary_done；
    - reporter：report_started -> report_done；
    - reflection：reflection_started -> reflection_done/failed；
    - workflow：workflow_started -> workflow_done/failed。

    Search 和 Summary 可能并发，因此开始时间以 ``(stage, task_id)`` 隔离。
    """

    _START_EVENTS = {
        "workflow_started": ("workflow", False),
        "task_started": ("searcher", True),
        "task_summary_started": ("summary", True),
        "report_started": ("reporter", False),
        "reflection_started": ("reflection", False),
    }
    _END_EVENTS = {
        "planner_done": ("planner", False),
        "task_sources_done": ("searcher", True),
        "task_summary_done": ("summary", True),
        "report_done": ("reporter", False),
        "reflection_done": ("reflection", False),
        "reflection_failed": ("reflection", False),
        "workflow_done": ("workflow", False),
        "workflow_failed": ("workflow", False),
    }

    def __init__(self) -> None:
        self._run_ids: set[str] = set()
        self._sequences: list[int] = []
        self._starts: dict[tuple[str, int | None], float] = {}
        self._stage_samples_ms: dict[str, list[float]] = defaultdict(list)
        self._search_observations: list[dict[str, Any]] = []
        self._workflow_started = False
        self._workflow_finished = False

    def observe(self, event: Any) -> None:
        """消费一条 research_event；非字典或缺时间戳事件会被安全忽略。"""
        if not isinstance(event, dict):
            return

        run_id = str(event.get("run_id") or "").strip()
        if run_id:
            self._run_ids.add(run_id)

        sequence = event.get("seq")
        if isinstance(sequence, int):
            self._sequences.append(sequence)

        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            return

        event_type = str(event.get("type") or "")
        task_id = event.get("task_id")
        task_key = task_id if isinstance(task_id, int) else None

        if event_type == "task_sources_done":
            payload = event.get("payload")
            observation = (
                payload.get("search_observation")
                if isinstance(payload, dict)
                else None
            )
            if isinstance(observation, dict) and observation:
                self._search_observations.append(dict(observation))

        if event_type == "workflow_started":
            self._workflow_started = True
            self._starts[("planner", None)] = float(timestamp)

        start = self._START_EVENTS.get(event_type)
        if start:
            stage, task_scoped = start
            self._starts[(stage, task_key if task_scoped else None)] = float(timestamp)

        end = self._END_EVENTS.get(event_type)
        if not end:
            return

        stage, task_scoped = end
        key = (stage, task_key if task_scoped else None)
        started_at = self._starts.pop(key, None)
        if started_at is not None and timestamp >= started_at:
            self._stage_samples_ms[stage].append(
                round((float(timestamp) - started_at) * 1000, 2)
            )
        if event_type in {"workflow_done", "workflow_failed"}:
            self._workflow_finished = True

    def summary(self) -> dict[str, Any]:
        """返回可以直接并入单题 metrics.json 的结构化 Trace 指标。"""
        sorted_sequences = sorted(set(self._sequences))
        missing_sequences: list[int] = []
        if sorted_sequences:
            expected = set(
                range(sorted_sequences[0], sorted_sequences[-1] + 1)
            )
            missing_sequences = sorted(expected - set(sorted_sequences))

        trace_id = next(iter(self._run_ids)) if len(self._run_ids) == 1 else ""
        trace_complete = (
            len(self._run_ids) == 1
            and self._workflow_started
            and self._workflow_finished
            and not missing_sequences
        )
        stage_samples = {
            stage: samples
            for stage, samples in sorted(self._stage_samples_ms.items())
        }
        return {
            "trace_id": trace_id,
            "trace_complete": trace_complete,
            "trace_run_id_count": len(self._run_ids),
            "trace_missing_sequences": missing_sequences,
            "stage_samples_ms": stage_samples,
            "stage_latency_ms": {
                stage: latency_distribution(samples)
                for stage, samples in stage_samples.items()
            },
            **self._search_observation_summary(),
        }

    def _search_observation_summary(self) -> dict[str, Any]:
        """聚合真实 SSE 中的补检索、参数校验和规则回退结果。"""
        observations = self._search_observations
        tool_call_count = sum(
            self._integer(item.get("tool_call_count"))
            for item in observations
        )
        parameter_valid_count = sum(
            self._integer(item.get("tool_parameter_valid_count"))
            for item in observations
        )
        execution_success_count = sum(
            self._integer(item.get("tool_execution_success_count"))
            for item in observations
        )
        function_calling_attempt_count = sum(
            1 for item in observations
            if item.get("function_calling_attempted") is True
        )
        supplemental_success_count = sum(
            1 for item in observations
            if item.get("supplemental_search_success") is True
        )
        fallback_count = sum(
            1 for item in observations
            if item.get("fallback_used") is True
        )
        tool_duration_samples = [
            float(duration)
            for item in observations
            for duration in (
                item.get("tool_duration_ms")
                if isinstance(item.get("tool_duration_ms"), list)
                else []
            )
            if isinstance(duration, (int, float))
        ]

        return {
            "search_observation_count": len(observations),
            "search_retry_trigger_count": sum(
                1 for item in observations
                if item.get("retry_triggered") is True
            ),
            "function_calling_attempt_count": function_calling_attempt_count,
            "tool_call_count": tool_call_count,
            "tool_parameter_valid_count": parameter_valid_count,
            "tool_parameter_accuracy": self._rate(
                parameter_valid_count,
                tool_call_count,
            ),
            "tool_execution_success_count": execution_success_count,
            "tool_execution_success_rate": self._rate(
                execution_success_count,
                tool_call_count,
            ),
            "supplemental_search_success_count": supplemental_success_count,
            "supplemental_search_success_rate": self._rate(
                supplemental_success_count,
                function_calling_attempt_count,
            ),
            "rule_retry_count": sum(
                1 for item in observations
                if item.get("rule_retry_used") is True
            ),
            "rule_fallback_count": fallback_count,
            "rule_fallback_rate": self._rate(
                fallback_count,
                function_calling_attempt_count,
            ),
            "tool_duration_ms": latency_distribution(tool_duration_samples),
        }

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0
