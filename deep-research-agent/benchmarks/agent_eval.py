"""离线运行固定 Agent 行为评测集。

评测使用 Fake LLM 和 Fake Search，不访问真实模型或搜索服务。它直接复用正式
FunctionCallingAgent、ToolRegistry、SupplementalSearchTool 和 SearchService，
验证工具协议、Schema、安全参数、补检索与规则回退在代码变更后仍然成立。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.core.config import Config
from backend.domain.models import TodoItem
from backend.llm.client import NativeChatResponse, NativeToolCall
from backend.llm.function_calling_agent import (
    FunctionCallingAgent,
    FunctionCallingRunResult,
    FunctionToolExecution,
)
from backend.services.search_service import SearchService
from backend.services.source_quality import SourceQualityService
from backend.tools.supplemental_search_tool import (
    SupplementalSearchContext,
    SupplementalSearchTool,
)
from backend.tools.tool_registry import ToolRegistry


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_FILE = BENCHMARK_DIR / "agent_cases.json"
DEFAULT_OUTPUT_FILE = BENCHMARK_DIR / "reports" / "agent_eval_latest.json"
CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ScriptedNativeLlm:
    """按 case 脚本返回 Tool Call，第二轮固定返回最终文本。"""

    def __init__(
        self,
        *,
        scenario: str,
        arguments: str,
    ) -> None:
        self.scenario = scenario
        self.arguments = arguments
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, **kwargs) -> NativeChatResponse:
        self.calls.append({"messages": list(messages), **kwargs})
        if len(self.calls) > 1 or self.scenario == "no_tool_call":
            return NativeChatResponse(
                content="补充搜索处理完成。",
                assistant_message={
                    "role": "assistant",
                    "content": "补充搜索处理完成。",
                },
            )

        call_count = 2 if self.scenario == "duplicate_tool_call" else 1
        tool_calls = [
            NativeToolCall(
                id=f"call_{index}",
                name="supplemental_search",
                arguments=self.arguments,
            )
            for index in range(1, call_count + 1)
        ]
        assistant_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in tool_calls
        ]
        return NativeChatResponse(
            tool_calls=tool_calls,
            assistant_message={
                "role": "assistant",
                "content": "",
                "tool_calls": assistant_calls,
            },
        )


class FakeSearchTool:
    """记录可信运行参数，并按 case 返回成功、超时或异常。"""

    def __init__(self, behavior: str = "success") -> None:
        self.behavior = behavior
        self.calls: list[dict[str, Any]] = []

    def run(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(parameters)
        if self.behavior == "timeout":
            raise TimeoutError("fake search timeout")
        if self.behavior == "error":
            raise RuntimeError("fake search failed")
        return {
            "backend": str(parameters.get("backend") or "duckduckgo"),
            "results": [{
                "title": "Agent Production Evaluation",
                "url": "https://docs.example.com/agent-evaluation",
                "content": (
                    "AI Agent production evaluation official documentation "
                    "limitations failure cases benchmark evidence quality. "
                ) * 6,
            }],
            "notices": [],
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Agent 固定评测集必须是非空数组。")

    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 case 必须是 JSON object。")
        case_id = str(item.get("case_id") or "")
        scenario = str(item.get("scenario") or "")
        expected = item.get("expected")
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"case_id 非法：{case_id!r}")
        if case_id in seen:
            raise ValueError(f"case_id 重复：{case_id}")
        if scenario not in {
            "tool_call",
            "duplicate_tool_call",
            "no_tool_call",
            "search_retry_success",
            "search_retry_fallback",
        }:
            raise ValueError(f"case_id={case_id} 的 scenario 不支持：{scenario}")
        if not isinstance(expected, dict) or not expected:
            raise ValueError(f"case_id={case_id} 缺少 expected。")
        seen.add(case_id)
        cases.append(item)
    return cases


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    scenario = str(case["scenario"])
    if scenario in {"search_retry_success", "search_retry_fallback"}:
        actual = _run_search_retry_case(scenario)
    else:
        actual = _run_tool_call_case(case)

    expected = case["expected"]
    mismatches = [
        {
            "metric": key,
            "expected": expected_value,
            "actual": actual.get(key),
        }
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    ]
    return {
        "case_id": case["case_id"],
        "scenario": scenario,
        "passed": not mismatches,
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
    }


def _run_tool_call_case(case: dict[str, Any]) -> dict[str, Any]:
    scenario = str(case["scenario"])
    llm = ScriptedNativeLlm(
        scenario=scenario,
        arguments=str(case.get("arguments") or "{}"),
    )
    search_tool = FakeSearchTool(str(case.get("search_behavior") or "success"))
    registry = ToolRegistry()
    registry.register_tool(SupplementalSearchTool(search_tool))  # type: ignore[arg-type]
    agent = FunctionCallingAgent(
        llm=llm,  # type: ignore[arg-type]
        tool_registry=registry,
        system_prompt="执行一次补充搜索。",
        max_steps=2,
    )
    context = SupplementalSearchContext(
        backend="duckduckgo",
        requested_max_results=4,
        mode="structured",
        fetch_full_page=False,
        max_tokens_per_source=500,
        timeout_seconds=12,
    )

    result = agent.run(
        "现有来源缺少失败案例。",
        context=context,
        forced_tool_name="supplemental_search",
    )
    error_codes = [
        execution.result.get("error", {}).get("code")
        for execution in result.executions
        if isinstance(execution.result.get("error"), dict)
    ]
    successful_data = result.successful_tool_data("supplemental_search")
    has_results = any(
        isinstance(data, dict) and bool(data.get("results"))
        for data in successful_data
    )
    return {
        "tool_call_compliant": bool(result.executions)
        and all(
            execution.name == "supplemental_search"
            for execution in result.executions
        ),
        "parameter_valid": bool(result.executions)
        and "INVALID_ARGUMENTS" not in error_codes,
        "tool_execution_success": any(
            bool(execution.result.get("success"))
            for execution in result.executions
        ),
        "supplemental_search_success": has_results,
        "duplicate_suppressed": "DUPLICATE_TOOL_CALL" in error_codes,
        "error_code": next(
            (
                code
                for code in error_codes
                if code != "DUPLICATE_TOOL_CALL"
            ),
            None,
        ),
        "tool_call_count": len(result.executions),
        "search_execution_count": len(search_tool.calls),
    }


def _run_search_retry_case(scenario: str) -> dict[str, Any]:
    fallback_search = FakeSearchTool()
    if scenario == "search_retry_success":
        tool_data = {
            "backend": "duckduckgo",
            "results": [{
                "title": "Agent Production Evaluation",
                "url": "https://docs.example.com/agent-evaluation",
                "content": (
                    "AI Agent production evaluation official documentation "
                    "limitations failure cases benchmark evidence quality. "
                ) * 6,
                "search_query": "AI Agent production failure cases",
            }],
            "notices": ["Function Calling 补充搜索"],
        }
        run_result = FunctionCallingRunResult(
            final_answer="完成",
            executions=[
                FunctionToolExecution(
                    call_id="call_1",
                    name="supplemental_search",
                    arguments={
                        "query": "AI Agent production failure cases",
                        "focus": "limitations",
                        "reason": "来源不足",
                    },
                    result={
                        "success": True,
                        "data": tool_data,
                        "error": None,
                        "meta": {"duration_ms": 1},
                    },
                )
            ],
        )
    else:
        run_result = FunctionCallingRunResult()

    service = SearchService(
        fallback_search,  # type: ignore[arg-type]
        Config.from_env(
            enable_search_quality_retry=True,
            search_retry_mode="function_calling",
        ),
        function_calling_agent=SimpleNamespace(
            run=lambda *args, **kwargs: run_result
        ),  # type: ignore[arg-type]
    )
    task = TodoItem(
        id=1,
        title="Agent 失败治理",
        intent="研究生产失败案例",
        query="AI Agent evaluation",
    )
    empty_result = {
        "backend": "duckduckgo",
        "results": [],
        "notices": [],
    }
    result = service.apply_search_quality_retry(
        task=task,
        backend="duckduckgo",
        mode="structured",
        fetch_full_page=False,
        max_tokens_per_source=500,
        requested_max_results=4,
        source_quality=SourceQualityService(keep_results=4),
        first_search_results=empty_result,
        filtered_result=empty_result,
    )
    result_rows = result.get("results") or []
    supplemental_success = any(
        isinstance(item, dict)
        and item.get("search_query") == "AI Agent production failure cases"
        for item in result_rows
    )
    return {
        "supplemental_search_success": supplemental_success,
        "fallback_used": bool(fallback_search.calls),
        "fallback_call_count": len(fallback_search.calls),
        "result_count": len(result_rows),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_metric_total = sum(
        len(result["expected"]) for result in results
    )
    matched_metric_total = sum(
        len(result["expected"]) - len(result["mismatches"])
        for result in results
    )
    return {
        "case_count": len(results),
        "passed_case_count": sum(1 for result in results if result["passed"]),
        "case_pass_rate": round(
            sum(1 for result in results if result["passed"]) / len(results),
            4,
        ) if results else 0,
        "expected_metric_count": expected_metric_total,
        "matched_metric_count": matched_metric_total,
        "behavior_accuracy": round(
            matched_metric_total / expected_metric_total,
            4,
        ) if expected_metric_total else 0,
    }


def run_suite(
    *,
    cases_file: Path,
    output_file: Path,
) -> dict[str, Any]:
    cases = load_cases(cases_file)
    results = [run_case(case) for case in cases]
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cases_file": str(cases_file.resolve()),
        "summary": summarize(results),
        "cases": results,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行离线 Agent 固定评测集。")
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=DEFAULT_CASES_FILE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_suite(
            cases_file=args.cases_file,
            output_file=args.output,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Agent 评测启动失败：{exc}", file=sys.stderr)
        return 2

    for result in report["cases"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['case_id']}")
        for mismatch in result["mismatches"]:
            print(
                "  {metric}: expected={expected!r}, actual={actual!r}".format(
                    **mismatch
                )
            )
    summary = report["summary"]
    print(
        "Agent 固定评测：{passed}/{total}，行为准确率 {accuracy:.1%}".format(
            passed=summary["passed_case_count"],
            total=summary["case_count"],
            accuracy=summary["behavior_accuracy"],
        )
    )
    print(f"报告：{args.output}")
    return 0 if summary["passed_case_count"] == summary["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
