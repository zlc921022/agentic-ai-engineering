"""通过现有 SSE 接口运行固定问题集，并生成轻量回归快照。

这个模块故意不导入业务侧的 Agent、Service 或模型类。它只知道 HTTP/SSE
协议和最终 result 的公开结构，因此未来删除参考项目或重构业务内部实现时，
评测工具仍然可以独立工作。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    # ``python -m benchmarks.runner`` 和单元测试走包导入。
    from benchmarks.observability import SseTraceAnalyzer, latency_distribution
except ModuleNotFoundError:
    # README 保留了 ``python benchmarks/runner.py`` 的直接运行方式。
    from observability import SseTraceAnalyzer, latency_distribution


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_FILE = BENCHMARK_DIR / "cases.json"
DEFAULT_RUNS_DIR = BENCHMARK_DIR / "runs"
DEFAULT_REPORTS_DIR = BENCHMARK_DIR / "reports"
CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

SseMessage = dict[str, Any]
StreamFactory = Callable[..., Iterator[SseMessage]]


def load_cases(path: Path) -> list[dict[str, str]]:
    """读取并校验固定问题集，尽早暴露重复 ID 或空问题。"""
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases.json 必须是非空数组。")

    cases: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 case 必须是 JSON 对象。")

        case_id = str(item.get("case_id") or "").strip()
        topic = str(item.get("topic") or "").strip()
        description = str(item.get("description") or "").strip()
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(
                f"case_id={case_id!r} 非法，只允许小写字母、数字、下划线和连字符。"
            )
        if case_id in seen_ids:
            raise ValueError(f"case_id 重复：{case_id}")
        if not topic:
            raise ValueError(f"case_id={case_id} 缺少 topic。")

        seen_ids.add(case_id)
        cases.append(
            {
                "case_id": case_id,
                "topic": topic,
                "description": description,
            }
        )

    return cases


def select_cases(
    cases: list[dict[str, str]],
    selected_ids: list[str] | None,
) -> list[dict[str, str]]:
    """默认运行全部六题；--case 只用于本地快速调试某几题。"""
    if not selected_ids:
        return cases

    requested = set(selected_ids)
    selected = [case for case in cases if case["case_id"] in requested]
    missing = sorted(requested - {case["case_id"] for case in selected})
    if missing:
        raise ValueError(f"未找到指定 case：{missing}")
    return selected


def iter_sse_messages(lines: Iterable[str | bytes]) -> Iterator[SseMessage]:
    """把 requests.iter_lines() 产生的文本行还原成 SSE 消息。

    SSE 使用空行分隔消息；一个消息可以包含 id、event 和多行 data。
    后端当前 data 是一段 JSON，但解析器仍保留标准 SSE 的多行拼接行为。
    """
    message_id = ""
    event_name = "message"
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r")

        if line == "":
            if data_lines:
                data_text = "\n".join(data_lines)
                try:
                    data: Any = json.loads(data_text)
                except json.JSONDecodeError:
                    data = data_text
                yield {
                    "id": message_id,
                    "event": event_name,
                    "data": data,
                }
            message_id = ""
            event_name = "message"
            data_lines = []
            continue

        if line.startswith(":"):
            # 冒号开头是 SSE 心跳或注释，不属于业务事件。
            continue

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]

        if field == "id":
            message_id = value
        elif field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)

    # 某些测试流或异常断流没有以空行结尾，仍尽量保留最后一条消息。
    if data_lines:
        data_text = "\n".join(data_lines)
        try:
            data = json.loads(data_text)
        except json.JSONDecodeError:
            data = data_text
        yield {
            "id": message_id,
            "event": event_name,
            "data": data,
        }


def stream_research(
    *,
    base_url: str,
    topic: str,
    backend: str,
    connect_timeout: float,
    read_timeout: float,
) -> Iterator[SseMessage]:
    """调用业务已有的 SSE，不直接依赖任何业务 Python 模块。"""
    endpoint = f"{base_url.rstrip('/')}/api/research/stream"
    with requests.get(
        endpoint,
        params={"topic": topic, "backend": backend},
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=(connect_timeout, read_timeout),
    ) as response:
        response.raise_for_status()
        yield from iter_sse_messages(
            response.iter_lines(decode_unicode=True)
        )


def result_from_event(event: Any) -> dict[str, Any] | None:
    """workflow_done.payload.result 是业务流向评测指标的唯一入口。"""
    if not isinstance(event, dict) or event.get("type") != "workflow_done":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def event_failure_message(event: Any) -> str:
    """从失败事件中提取一条适合写入 case 快照的错误摘要。"""
    if not isinstance(event, dict):
        return ""
    if event.get("type") not in {
        "api_error",
        "workflow_failed",
        "planner_failed",
        "report_failed",
    }:
        return ""

    error = event.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if event.get("message"):
        return str(event["message"])
    return str(event.get("type") or "unknown error")


def extract_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    """优先从最终 tasks 取来源，兼容只有 traces 的旧快照。"""
    sources: list[dict[str, Any]] = []
    tasks = result.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            search_results = task.get("search_results")
            if not isinstance(search_results, list):
                continue
            sources.extend(
                source
                for source in search_results
                if isinstance(source, dict)
            )
    if sources:
        return sources

    traces = result.get("traces")
    if isinstance(traces, list):
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            top_sources = trace.get("top_sources")
            if isinstance(top_sources, list):
                sources.extend(
                    source
                    for source in top_sources
                    if isinstance(source, dict)
                )
    return sources


def normalized_domain(url: str) -> str:
    """统一域名格式，让 www.example.com 与 example.com 只计一次。"""
    domain = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return domain[4:] if domain.startswith("www.") else domain


def extract_case_metrics(
    *,
    case_id: str,
    result: dict[str, Any] | None,
    elapsed_seconds: float,
    event_count: int,
    error: str = "",
    trace_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把最终 result 压缩成便于跨版本对比的一行基础指标。

    数据链如下：
    workflow_done -> payload.result -> tasks/search_results/evaluator -> metrics
    """
    result = result or {}
    tasks = [
        task
        for task in result.get("tasks", [])
        if isinstance(task, dict)
    ] if isinstance(result.get("tasks"), list) else []
    completed_tasks = [
        task for task in tasks if task.get("status") == "completed"
    ]
    summaries = [
        str(task.get("summary") or "")
        for task in tasks
        if str(task.get("summary") or "")
    ]
    sources = extract_sources(result)
    domains = {
        domain
        for source in sources
        if (domain := normalized_domain(str(source.get("url") or "")))
    }

    evaluator = result.get("evaluator")
    evaluator = evaluator if isinstance(evaluator, dict) else {}
    warnings = evaluator.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    overall_score = evaluator.get("overall_score")
    if not isinstance(overall_score, (int, float)):
        overall_score = None

    def evaluator_number(key: str) -> int | float | None:
        value = evaluator.get(key)
        return value if isinstance(value, (int, float)) else None

    report = result.get("report")
    report = report if isinstance(report, str) else ""
    llm_usage = result.get("llm_usage")
    llm_usage = llm_usage if isinstance(llm_usage, dict) else {}
    usage_cost = llm_usage.get("cost")
    usage_cost = usage_cost if isinstance(usage_cost, dict) else {}
    estimated_cost = usage_cost.get("estimated")
    if not isinstance(estimated_cost, (int, float)):
        estimated_cost = None

    metrics = {
        "case_id": case_id,
        # 收到 workflow_done 且拿到 result，就表示业务主流程走到了终点。
        "success": bool(result),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "task_count": len(tasks),
        "completed_task_count": len(completed_tasks),
        "source_count": len(sources),
        "unique_domain_count": len(domains),
        "average_summary_chars": round(
            sum(len(summary) for summary in summaries) / len(summaries)
        ) if summaries else 0,
        "report_chars": len(report),
        "overall_score": overall_score,
        "citation_precision": evaluator_number("citation_precision"),
        "citation_recall": evaluator_number("citation_recall"),
        "primary_source_ratio": evaluator_number("primary_source_ratio"),
        "weak_source_ratio": evaluator_number("weak_source_ratio"),
        "evaluator_unique_domain_count": evaluator_number("unique_domain_count"),
        "max_domain_concentration": evaluator_number("max_domain_concentration"),
        "hard_error_count": int(evaluator_number("hard_error_count") or 0),
        "quality_warning_count": int(evaluator_number("quality_warning_count") or 0),
        "warning_count": len(warnings),
        "event_count": event_count,
        "error": error,
        "llm_usage_available": bool(llm_usage.get("available")),
        "llm_request_count": int(llm_usage.get("request_count") or 0),
        "prompt_tokens": int(llm_usage.get("prompt_tokens") or 0),
        "completion_tokens": int(llm_usage.get("completion_tokens") or 0),
        "total_tokens": int(llm_usage.get("total_tokens") or 0),
        "cached_tokens": int(llm_usage.get("cached_tokens") or 0),
        "reasoning_tokens": int(llm_usage.get("reasoning_tokens") or 0),
        "llm_usage_by_stage": (
            llm_usage.get("by_stage")
            if isinstance(llm_usage.get("by_stage"), dict)
            else {}
        ),
        "estimated_cost": estimated_cost,
        "cost_currency": str(usage_cost.get("currency") or ""),
    }
    # Trace 指标由 Benchmark 客户端根据 SSE 推导，不要求业务结果新增字段。
    metrics.update(trace_metrics or {})
    return metrics


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_case(
    *,
    case: dict[str, str],
    run_dir: Path,
    base_url: str,
    backend: str,
    connect_timeout: float,
    read_timeout: float,
    stream_factory: StreamFactory = stream_research,
) -> dict[str, Any]:
    """运行单个问题，并在返回前完整落盘事件、结果和报告。"""
    case_id = case["case_id"]
    events_path = run_dir / f"{case_id}_events.jsonl"
    result_path = run_dir / f"{case_id}.json"
    report_path = run_dir / f"{case_id}_report.md"

    started_at = datetime.now().astimezone()
    started_perf = time.perf_counter()
    event_count = 0
    final_result: dict[str, Any] | None = None
    error_message = ""
    trace_analyzer = SseTraceAnalyzer()

    try:
        # 边接收边写 JSONL：即使网络或模型在中途失败，已收到的轨迹仍会留下。
        with events_path.open("w", encoding="utf-8") as event_file:
            for message in stream_factory(
                base_url=base_url,
                topic=case["topic"],
                backend=backend,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            ):
                event_file.write(
                    json.dumps(message, ensure_ascii=False) + "\n"
                )
                event_count += 1

                event = message.get("data")
                trace_analyzer.observe(event)
                candidate_result = result_from_event(event)
                if candidate_result is not None:
                    final_result = candidate_result

                failure = event_failure_message(event)
                if failure:
                    error_message = failure
    except Exception as exc:  # 网络失败也要生成可比较的失败快照。
        error_message = f"{exc.__class__.__name__}: {exc}"

    elapsed_seconds = time.perf_counter() - started_perf
    metrics = extract_case_metrics(
        case_id=case_id,
        result=final_result,
        elapsed_seconds=elapsed_seconds,
        event_count=event_count,
        error=error_message,
        trace_metrics=trace_analyzer.summary(),
    )
    report = (
        final_result.get("report", "")
        if isinstance(final_result, dict)
        and isinstance(final_result.get("report"), str)
        else ""
    )
    report_path.write_text(report, encoding="utf-8")

    snapshot = {
        "case": case,
        "request": {
            "base_url": base_url,
            "endpoint": "/api/research/stream",
            "backend": backend,
            "started_at": started_at.isoformat(timespec="seconds"),
        },
        "metrics": metrics,
        "result": final_result,
        "artifacts": {
            "events": events_path.name,
            "report": report_path.name,
        },
    }
    write_json(result_path, snapshot)
    return metrics


def average(values: list[float | int]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def numeric_values(
    case_metrics: list[dict[str, Any]],
    key: str,
) -> list[float | int]:
    return [
        item[key]
        for item in case_metrics
        if isinstance(item.get(key), (int, float))
    ]


def safe_rate(numerator: int, denominator: int) -> float | None:
    """有真实样本时计算比例；没有 Tool Call 时返回 None 而不是虚假 0%。"""
    return round(numerator / denominator, 4) if denominator else None


def summarize_run(case_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """把每题指标聚合为版本对比所需的六个核心数字。"""
    # 失败 case 通常耗时很短且来源为 0；把它们混入均值会制造“变快了”的假象。
    # 因此成功率统计全部 case，其余平均指标只统计成功 case。
    successful = [item for item in case_metrics if item.get("success")]
    scores = [
        item["overall_score"]
        for item in successful
        if isinstance(item.get("overall_score"), (int, float))
    ]
    primary_source_ratios = numeric_values(successful, "primary_source_ratio")
    weak_source_ratios = numeric_values(successful, "weak_source_ratio")
    max_domain_concentrations = numeric_values(
        successful,
        "max_domain_concentration",
    )
    success_count = len(successful)
    case_count = len(case_metrics)
    elapsed_distribution = latency_distribution(
        item["elapsed_seconds"] for item in successful
    )
    stage_samples: dict[str, list[float]] = {}
    for item in successful:
        raw_stage_samples = item.get("stage_samples_ms")
        if not isinstance(raw_stage_samples, dict):
            continue
        for stage, samples in raw_stage_samples.items():
            if not isinstance(samples, list):
                continue
            stage_samples.setdefault(str(stage), []).extend(
                float(sample)
                for sample in samples
                if isinstance(sample, (int, float))
            )

    tool_call_count = sum(
        int(item.get("tool_call_count") or 0)
        for item in successful
    )
    tool_parameter_valid_count = sum(
        int(item.get("tool_parameter_valid_count") or 0)
        for item in successful
    )
    tool_execution_success_count = sum(
        int(item.get("tool_execution_success_count") or 0)
        for item in successful
    )
    function_calling_attempt_count = sum(
        int(item.get("function_calling_attempt_count") or 0)
        for item in successful
    )
    supplemental_search_success_count = sum(
        int(item.get("supplemental_search_success_count") or 0)
        for item in successful
    )
    rule_fallback_count = sum(
        int(item.get("rule_fallback_count") or 0)
        for item in successful
    )
    estimated_costs = numeric_values(successful, "estimated_cost")

    token_usage_by_stage: dict[str, dict[str, int]] = {}
    for item in successful:
        by_stage = item.get("llm_usage_by_stage")
        if not isinstance(by_stage, dict):
            continue
        for stage_name, values in by_stage.items():
            if not isinstance(values, dict):
                continue
            stage = token_usage_by_stage.setdefault(
                str(stage_name),
                {
                    "request_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cached_tokens": 0,
                    "reasoning_tokens": 0,
                },
            )
            for key in stage:
                stage[key] += int(values.get(key) or 0)

    return {
        "case_count": case_count,
        "success_count": success_count,
        "success_rate": round(success_count / case_count, 4) if case_count else 0,
        "average_elapsed_seconds": average(
            [item["elapsed_seconds"] for item in successful]
        ),
        "elapsed_seconds_distribution": elapsed_distribution,
        "p50_elapsed_seconds": elapsed_distribution["p50"],
        "p95_elapsed_seconds": elapsed_distribution["p95"],
        "p99_elapsed_seconds": elapsed_distribution["p99"],
        "trace_complete_count": sum(
            1 for item in case_metrics if item.get("trace_complete")
        ),
        "trace_complete_rate": round(
            sum(1 for item in case_metrics if item.get("trace_complete"))
            / case_count,
            4,
        ) if case_count else 0,
        "stage_latency_ms": {
            stage: latency_distribution(samples)
            for stage, samples in sorted(stage_samples.items())
        },
        "llm_usage_available_count": sum(
            1 for item in successful if item.get("llm_usage_available")
        ),
        "llm_request_count": sum(
            int(item.get("llm_request_count") or 0)
            for item in successful
        ),
        "prompt_tokens": sum(
            int(item.get("prompt_tokens") or 0)
            for item in successful
        ),
        "completion_tokens": sum(
            int(item.get("completion_tokens") or 0)
            for item in successful
        ),
        "total_tokens": sum(
            int(item.get("total_tokens") or 0)
            for item in successful
        ),
        "average_total_tokens": average(
            [
                int(item.get("total_tokens") or 0)
                for item in successful
                if item.get("llm_usage_available")
            ]
        ),
        "cached_tokens": sum(
            int(item.get("cached_tokens") or 0)
            for item in successful
        ),
        "reasoning_tokens": sum(
            int(item.get("reasoning_tokens") or 0)
            for item in successful
        ),
        "estimated_cost": (
            round(sum(estimated_costs), 8)
            if estimated_costs
            else None
        ),
        "token_usage_by_stage": token_usage_by_stage,
        "function_calling_attempt_count": function_calling_attempt_count,
        "tool_call_count": tool_call_count,
        "tool_parameter_valid_count": tool_parameter_valid_count,
        "tool_parameter_accuracy": safe_rate(
            tool_parameter_valid_count,
            tool_call_count,
        ),
        "tool_execution_success_count": tool_execution_success_count,
        "tool_execution_success_rate": safe_rate(
            tool_execution_success_count,
            tool_call_count,
        ),
        "supplemental_search_success_count": supplemental_search_success_count,
        "supplemental_search_success_rate": safe_rate(
            supplemental_search_success_count,
            function_calling_attempt_count,
        ),
        "rule_retry_count": sum(
            int(item.get("rule_retry_count") or 0)
            for item in successful
        ),
        "rule_fallback_count": rule_fallback_count,
        "rule_fallback_rate": safe_rate(
            rule_fallback_count,
            function_calling_attempt_count,
        ),
        "average_source_count": average(
            [item["source_count"] for item in successful]
        ),
        "average_unique_domain_count": average(
            [item["unique_domain_count"] for item in successful]
        ),
        "average_summary_chars": average(
            [item["average_summary_chars"] for item in successful]
        ),
        "average_report_chars": average(
            [item["report_chars"] for item in successful]
        ),
        "average_overall_score": average(scores) if scores else None,
        "average_primary_source_ratio": (
            average(primary_source_ratios)
            if primary_source_ratios
            else None
        ),
        "average_weak_source_ratio": (
            average(weak_source_ratios)
            if weak_source_ratios
            else None
        ),
        "average_max_domain_concentration": (
            average(max_domain_concentrations)
            if max_domain_concentrations
            else None
        ),
        "hard_error_count": sum(
            int(item.get("hard_error_count") or 0)
            for item in case_metrics
        ),
        "quality_warning_count": sum(
            int(item.get("quality_warning_count") or 0)
            for item in case_metrics
        ),
        "warning_count": sum(
            int(item.get("warning_count") or 0)
            for item in case_metrics
        ),
    }


def create_run_dir(runs_dir: Path) -> tuple[str, Path]:
    """创建形如 2026-06-18_153000 的目录，秒级重名时增加序号。"""
    runs_dir.mkdir(parents=True, exist_ok=True)
    base_run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_id = base_run_id
    suffix = 2
    while (runs_dir / run_id).exists():
        run_id = f"{base_run_id}_{suffix:02d}"
        suffix += 1

    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    return run_id, run_dir


def find_previous_run(
    *,
    runs_dir: Path,
    current_run_id: str,
    case_ids: list[str],
    backend: str,
) -> dict[str, Any] | None:
    """只比较相同问题集和 backend，避免把局部调试结果误当版本回归。"""
    if not runs_dir.exists():
        return None

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir() or run_dir.name == current_run_id:
            continue
        metrics_path = run_dir / "metrics.json"
        if not metrics_path.exists():
            continue
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metrics.get("case_ids") != case_ids:
            continue
        if metrics.get("backend") != backend:
            continue
        return metrics
    return None


def format_number(value: Any, digits: int = 1) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:.{digits}f}"


def format_percent(value: Any, digits: int = 1) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:.{digits}%}"


def absolute_change(previous: Any, current: Any, suffix: str = "") -> str:
    if not isinstance(previous, (int, float)) or not isinstance(current, (int, float)):
        return "—"
    change = current - previous
    return f"{change:+.1f}{suffix}"


def percent_change(previous: Any, current: Any) -> str:
    if (
        not isinstance(previous, (int, float))
        or not isinstance(current, (int, float))
        or previous == 0
    ):
        return "—"
    return f"{(current - previous) / previous:+.1%}"


def percentage_point_change(previous: Any, current: Any) -> str:
    if not isinstance(previous, (int, float)) or not isinstance(current, (int, float)):
        return "—"
    return f"{(current - previous) * 100:+.1f} pp"


def markdown_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_latest_report(
    *,
    run_metrics: dict[str, Any],
    previous_metrics: dict[str, Any] | None,
) -> str:
    """生成给人看的 latest.md；metrics.json 保留机器可读的完整数据。"""
    current = run_metrics["summary"]
    previous = previous_metrics.get("summary", {}) if previous_metrics else {}
    previous_run_id = previous_metrics.get("run_id", "—") if previous_metrics else "—"

    comparison_rows = [
        (
            "成功率",
            f"{previous.get('success_rate', 0):.1%}" if previous_metrics else "—",
            f"{current['success_rate']:.1%}",
            percentage_point_change(
                previous.get("success_rate"),
                current.get("success_rate"),
            ) if previous_metrics else "—",
        ),
        (
            "平均耗时",
            f"{format_number(previous.get('average_elapsed_seconds'))}s",
            f"{format_number(current.get('average_elapsed_seconds'))}s",
            percent_change(
                previous.get("average_elapsed_seconds"),
                current.get("average_elapsed_seconds"),
            ),
        ),
        (
            "P95 耗时",
            f"{format_number(previous.get('p95_elapsed_seconds'))}s",
            f"{format_number(current.get('p95_elapsed_seconds'))}s",
            percent_change(
                previous.get("p95_elapsed_seconds"),
                current.get("p95_elapsed_seconds"),
            ),
        ),
        (
            "LLM 总 Token",
            format_number(previous.get("total_tokens"), 0),
            format_number(current.get("total_tokens"), 0),
            percent_change(
                previous.get("total_tokens"),
                current.get("total_tokens"),
            ),
        ),
        (
            "估算成本",
            format_number(previous.get("estimated_cost"), 6),
            format_number(current.get("estimated_cost"), 6),
            percent_change(
                previous.get("estimated_cost"),
                current.get("estimated_cost"),
            ),
        ),
        (
            "Tool 参数正确率",
            format_percent(previous.get("tool_parameter_accuracy")),
            format_percent(current.get("tool_parameter_accuracy")),
            percentage_point_change(
                previous.get("tool_parameter_accuracy"),
                current.get("tool_parameter_accuracy"),
            ),
        ),
        (
            "补检索成功率",
            format_percent(previous.get("supplemental_search_success_rate")),
            format_percent(current.get("supplemental_search_success_rate")),
            percentage_point_change(
                previous.get("supplemental_search_success_rate"),
                current.get("supplemental_search_success_rate"),
            ),
        ),
        (
            "规则回退率",
            format_percent(previous.get("rule_fallback_rate")),
            format_percent(current.get("rule_fallback_rate")),
            percentage_point_change(
                previous.get("rule_fallback_rate"),
                current.get("rule_fallback_rate"),
            ),
        ),
        (
            "Trace 完整率",
            format_percent(previous.get("trace_complete_rate")),
            format_percent(current.get("trace_complete_rate")),
            percentage_point_change(
                previous.get("trace_complete_rate"),
                current.get("trace_complete_rate"),
            ),
        ),
        (
            "平均来源数",
            format_number(previous.get("average_source_count")),
            format_number(current.get("average_source_count")),
            absolute_change(
                previous.get("average_source_count"),
                current.get("average_source_count"),
            ),
        ),
        (
            "总结平均长度",
            format_number(previous.get("average_summary_chars"), 0),
            format_number(current.get("average_summary_chars"), 0),
            percent_change(
                previous.get("average_summary_chars"),
                current.get("average_summary_chars"),
            ),
        ),
        (
            "Evaluator 分数",
            format_number(previous.get("average_overall_score")),
            format_number(current.get("average_overall_score")),
            absolute_change(
                previous.get("average_overall_score"),
                current.get("average_overall_score"),
            ),
        ),
        (
            "Warnings 总数",
            format_number(previous.get("warning_count"), 0),
            format_number(current.get("warning_count"), 0),
            absolute_change(
                previous.get("warning_count"),
                current.get("warning_count"),
            ),
        ),
        (
            "硬错误",
            format_number(previous.get("hard_error_count"), 0),
            format_number(current.get("hard_error_count"), 0),
            absolute_change(
                previous.get("hard_error_count"),
                current.get("hard_error_count"),
            ),
        ),
        (
            "质量提醒",
            format_number(previous.get("quality_warning_count"), 0),
            format_number(current.get("quality_warning_count"), 0),
            absolute_change(
                previous.get("quality_warning_count"),
                current.get("quality_warning_count"),
            ),
        ),
        (
            "主来源占比",
            format_percent(previous.get("average_primary_source_ratio")),
            format_percent(current.get("average_primary_source_ratio")),
            percentage_point_change(
                previous.get("average_primary_source_ratio"),
                current.get("average_primary_source_ratio"),
            ),
        ),
        (
            "Weak 来源占比",
            format_percent(previous.get("average_weak_source_ratio")),
            format_percent(current.get("average_weak_source_ratio")),
            percentage_point_change(
                previous.get("average_weak_source_ratio"),
                current.get("average_weak_source_ratio"),
            ),
        ),
        (
            "最大域名集中度",
            format_percent(previous.get("average_max_domain_concentration")),
            format_percent(current.get("average_max_domain_concentration")),
            percentage_point_change(
                previous.get("average_max_domain_concentration"),
                current.get("average_max_domain_concentration"),
            ),
        ),
    ]

    lines = [
        "# Deep Research 轻量回归报告",
        "",
        f"- 本次运行：`{run_metrics['run_id']}`",
        f"- 上次可比运行：`{previous_run_id}`",
        f"- Backend：`{run_metrics['backend']}`",
        f"- 问题数：{current['case_count']}",
        f"- 运行目录：`benchmarks/runs/{run_metrics['run_id']}`",
        "",
        "## 版本对比",
        "",
        "| 指标 | 上次 | 本次 | 变化 |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {name} | {old} | {new} | {change} |"
        for name, old, new, change in comparison_rows
    )

    lines.extend(
        [
            "",
            "## 延迟分布",
            "",
            "| 范围 | 样本数 | P50 | P95 | P99 | 平均 | 最大 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            "| 整次研究(s) | {count} | {p50} | {p95} | {p99} | {average} | {maximum} |".format(
                count=current["elapsed_seconds_distribution"]["count"],
                p50=format_number(current["p50_elapsed_seconds"], 2),
                p95=format_number(current["p95_elapsed_seconds"], 2),
                p99=format_number(current["p99_elapsed_seconds"], 2),
                average=format_number(current["average_elapsed_seconds"], 2),
                maximum=format_number(
                    current["elapsed_seconds_distribution"]["max"],
                    2,
                ),
            ),
            "",
            "| SSE 阶段 | 样本数 | P50(ms) | P95(ms) | P99(ms) | 平均(ms) | 最大(ms) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for stage, distribution in current.get("stage_latency_ms", {}).items():
        lines.append(
            "| {stage} | {count} | {p50} | {p95} | {p99} | {average} | {maximum} |".format(
                stage=markdown_escape(stage),
                count=distribution["count"],
                p50=format_number(distribution["p50"], 2),
                p95=format_number(distribution["p95"], 2),
                p99=format_number(distribution["p99"], 2),
                average=format_number(distribution["average"], 2),
                maximum=format_number(distribution["max"], 2),
            )
        )

    lines.extend(
        [
            "",
            "## 单题结果",
            "",
            "| Case | 成功 | 耗时(s) | 任务 | 完成 | 来源 | 域名 | 报告长度 | 分数 | 硬错 | 质量 | 主来源 | Weak | Warnings |",
            "|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in run_metrics["cases"]:
        lines.append(
            "| {case_id} | {success} | {elapsed} | {tasks} | {completed} | "
            "{sources} | {domains} | {report_chars} | {score} | {hard_errors} | "
            "{quality_warnings} | {primary_ratio} | {weak_ratio} | {warnings} |".format(
                case_id=markdown_escape(item["case_id"]),
                success="是" if item["success"] else "否",
                elapsed=format_number(item["elapsed_seconds"], 2),
                tasks=item["task_count"],
                completed=item["completed_task_count"],
                sources=item["source_count"],
                domains=item["unique_domain_count"],
                report_chars=item["report_chars"],
                score=format_number(item["overall_score"], 0),
                hard_errors=item.get("hard_error_count", 0),
                quality_warnings=item.get("quality_warning_count", 0),
                primary_ratio=format_percent(item.get("primary_source_ratio"), 0),
                weak_ratio=format_percent(item.get("weak_source_ratio"), 0),
                warnings=item["warning_count"],
            )
        )

    failed = [item for item in run_metrics["cases"] if not item["success"]]
    if failed:
        lines.extend(["", "## 失败摘要", ""])
        for item in failed:
            lines.append(
                f"- `{item['case_id']}`：{markdown_escape(item.get('error') or '未收到 workflow_done')}"
            )

    lines.extend(
        [
            "",
            "> 这份报告用于比较同一固定问题集的版本变化，不代表绝对质量排名。",
            "",
        ]
    )
    return "\n".join(lines)


def run_suite(
    *,
    cases: list[dict[str, str]],
    cases_file: Path,
    runs_dir: Path,
    reports_dir: Path,
    base_url: str,
    backend: str,
    connect_timeout: float,
    read_timeout: float,
    stream_factory: StreamFactory = stream_research,
) -> tuple[dict[str, Any], Path]:
    """顺序运行固定问题集，产出本次 metrics.json 和 reports/latest.md。"""
    run_id, run_dir = create_run_dir(runs_dir)
    started_at = datetime.now().astimezone()
    started_perf = time.perf_counter()

    metrics: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] 运行 {case['case_id']}：{case['topic']}")
        case_metrics = run_case(
            case=case,
            run_dir=run_dir,
            base_url=base_url,
            backend=backend,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            stream_factory=stream_factory,
        )
        metrics.append(case_metrics)
        status = "成功" if case_metrics["success"] else "失败"
        print(
            f"  {status}，耗时 {case_metrics['elapsed_seconds']}s，"
            f"来源 {case_metrics['source_count']}，分数 {case_metrics['overall_score']}"
        )

    finished_at = datetime.now().astimezone()
    run_metrics = {
        "run_id": run_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started_perf, 2),
        "base_url": base_url,
        "endpoint": "/api/research/stream",
        "backend": backend,
        "cases_file": str(cases_file.resolve()),
        "case_ids": [case["case_id"] for case in cases],
        "summary": summarize_run(metrics),
        "cases": metrics,
    }
    write_json(run_dir / "metrics.json", run_metrics)

    previous = find_previous_run(
        runs_dir=runs_dir,
        current_run_id=run_id,
        case_ids=run_metrics["case_ids"],
        backend=backend,
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest_report = reports_dir / "latest.md"
    latest_report.write_text(
        build_latest_report(
            run_metrics=run_metrics,
            previous_metrics=previous,
        ),
        encoding="utf-8",
    )
    return run_metrics, latest_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行 Deep Research 固定问题集并生成版本回归报告。",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="已启动的 deep-research-agent 后端地址。",
    )
    parser.add_argument(
        "--backend",
        default="hybrid",
        help="传给 /api/research/stream 的搜索 backend。",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=DEFAULT_CASES_FILE,
        help="固定问题集 JSON 路径。",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="只运行指定 case_id；可重复传入。默认运行全部。",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=10,
        help="HTTP 建连超时秒数。",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=1200,
        help="等待下一条 SSE 数据的超时秒数。",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="运行快照目录。",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help="Markdown 汇总目录。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        cases = select_cases(
            load_cases(args.cases_file),
            args.case_ids,
        )
        run_metrics, latest_report = run_suite(
            cases=cases,
            cases_file=args.cases_file,
            runs_dir=args.runs_dir,
            reports_dir=args.reports_dir,
            base_url=args.base_url,
            backend=args.backend,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"评测启动失败：{exc}", file=sys.stderr)
        return 2

    print(f"\n运行快照：{args.runs_dir / run_metrics['run_id']}")
    print(f"汇总报告：{latest_report}")
    return 0 if run_metrics["summary"]["success_count"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
