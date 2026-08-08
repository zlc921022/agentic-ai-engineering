import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


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
from backend.search.search_tool import SearchTool
from backend.services.search_service import SearchService
from backend.services.source_quality import SourceQualityService
from backend.tools.supplemental_search_tool import (
    SupplementalSearchContext,
    SupplementalSearchTool,
)
from backend.tools.tool_registry import ToolRegistry


class FakeNativeLlm:
    """按顺序返回 tool call 和最终文本，离线验证原生消息闭环。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), **kwargs})
        if len(self.calls) == 1:
            arguments = (
                '{"query":"AI Agent production failure cases",'
                '"focus":"limitations",'
                '"reason":"缺少真实失败案例"}'
            )
            return NativeChatResponse(
                tool_calls=[
                    NativeToolCall(
                        id="call_retry_1",
                        name="supplemental_search",
                        arguments=arguments,
                    )
                ],
                assistant_message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_retry_1",
                        "type": "function",
                        "function": {
                            "name": "supplemental_search",
                            "arguments": arguments,
                        },
                    }],
                },
            )
        return NativeChatResponse(
            content="补充搜索完成。",
            assistant_message={
                "role": "assistant",
                "content": "补充搜索完成。",
            },
        )


class FakeSearchTool:
    """记录 Function Tool 最终下发给搜索后端的可信参数。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, parameters):
        self.calls.append(parameters)
        return {
            "backend": parameters["backend"],
            "results": [{
                "title": "Production Agent Failure Report",
                "url": "https://docs.example.com/agent-failures",
                "content": "production agent evaluation limitations failure cases",
            }],
            "notices": [],
        }


class FunctionCallingSearchRetryTest(unittest.TestCase):
    def test_agent_executes_tool_and_returns_result_to_model(self):
        """原生 tool_call_id 应贯穿工具请求和 tool result 回传。"""
        llm = FakeNativeLlm()
        search_tool = FakeSearchTool()
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

        self.assertEqual(len(result.executions), 1)
        self.assertTrue(result.executions[0].result["success"])
        self.assertEqual(search_tool.calls[0]["backend"], "duckduckgo")
        self.assertEqual(search_tool.calls[0]["timeout_seconds"], 12)
        second_messages = llm.calls[1]["messages"]
        tool_messages = [
            message
            for message in second_messages
            if message.get("role") == "tool"
        ]
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_retry_1")

    def test_registry_rejects_extra_model_arguments(self):
        """模型多传运行参数时，应在执行 SearchTool 前被 Schema 校验拦截。"""
        search_tool = FakeSearchTool()
        registry = ToolRegistry()
        registry.register_tool(SupplementalSearchTool(search_tool))  # type: ignore[arg-type]

        result = registry.execute_function(
            "supplemental_search",
            {
                "query": "AI Agent production failures",
                "focus": "limitations",
                "reason": "缺少失败案例",
                "backend": "internal-backend",
            },
            context=SupplementalSearchContext(
                backend="duckduckgo",
                requested_max_results=4,
                mode="structured",
                fetch_full_page=False,
                max_tokens_per_source=500,
                timeout_seconds=12,
            ),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")
        self.assertEqual(search_tool.calls, [])

    def test_search_service_uses_function_result_when_enabled(self):
        """Function Calling 成功后，不应再执行确定性规则补搜。"""
        strong_content = (
            "AI Agent production evaluation official documentation "
            "limitations failure cases benchmark evidence quality. "
        ) * 5
        tool_data = {
            "backend": "duckduckgo",
            "results": [{
                "title": "Official AI Agent Production Evaluation",
                "url": "https://docs.example.com/agent-evaluation",
                "content": strong_content,
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
        fake_agent = SimpleNamespace(run=lambda *args, **kwargs: run_result)
        fallback_search_tool = FakeSearchTool()
        service = SearchService(
            fallback_search_tool,  # type: ignore[arg-type]
            Config.from_env(
                enable_search_quality_retry=True,
                search_retry_mode="function_calling",
            ),
            function_calling_agent=fake_agent,  # type: ignore[arg-type]
        )
        task = TodoItem(
            id=1,
            title="Agent 失败治理",
            intent="研究生产失败案例",
            query="AI Agent evaluation",
        )
        first_result = {
            "backend": "duckduckgo",
            "results": [],
            "notices": [],
        }

        observation = {}
        result = service.apply_search_quality_retry(
            task=task,
            backend="duckduckgo",
            mode="structured",
            fetch_full_page=False,
            max_tokens_per_source=500,
            requested_max_results=4,
            source_quality=SourceQualityService(keep_results=4),
            first_search_results=first_result,
            filtered_result=first_result,
            observation=observation,
        )

        self.assertEqual(fallback_search_tool.calls, [])
        self.assertTrue(
            any(
                item.get("search_query") == "AI Agent production failure cases"
                for item in result["results"]
            )
        )
        self.assertTrue(observation["function_calling_attempted"])
        self.assertEqual(observation["tool_call_count"], 1)
        self.assertEqual(observation["tool_parameter_valid_count"], 1)
        self.assertEqual(observation["tool_execution_success_count"], 1)
        self.assertTrue(observation["supplemental_search_success"])
        self.assertFalse(observation["fallback_used"])

    def test_search_service_falls_back_to_rule_retry(self):
        """Function Calling 没有成功工具结果时，应自动使用现有规则查询。"""
        fake_agent = SimpleNamespace(
            run=lambda *args, **kwargs: FunctionCallingRunResult()
        )
        fallback_search_tool = FakeSearchTool()
        service = SearchService(
            fallback_search_tool,  # type: ignore[arg-type]
            Config.from_env(
                enable_search_quality_retry=True,
                search_retry_mode="function_calling",
            ),
            function_calling_agent=fake_agent,  # type: ignore[arg-type]
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

        observation = {}
        service.apply_search_quality_retry(
            task=task,
            backend="duckduckgo",
            mode="structured",
            fetch_full_page=False,
            max_tokens_per_source=500,
            requested_max_results=4,
            source_quality=SourceQualityService(keep_results=4),
            first_search_results=empty_result,
            filtered_result=empty_result,
            observation=observation,
        )

        self.assertEqual(len(fallback_search_tool.calls), 2)
        self.assertTrue(observation["function_calling_attempted"])
        self.assertEqual(observation["tool_call_count"], 0)
        self.assertTrue(observation["rule_retry_used"])
        self.assertTrue(observation["fallback_used"])
        self.assertEqual(
            observation["fallback_reason"],
            "tool_returned_no_usable_result",
        )

    def test_broken_observation_shape_is_fail_open(self):
        """指标对象异常时只记录降级码，不能把异常抛给补检索主流程。"""

        class BrokenRunResult:
            @property
            def executions(self):
                raise RuntimeError("broken observation payload")

        service = SearchService(
            FakeSearchTool(),  # type: ignore[arg-type]
            Config.from_env(enable_search_quality_retry=True),
        )
        observation = {}

        service._record_function_calling_observation(
            observation,
            BrokenRunResult(),  # type: ignore[arg-type]
            task_id=1,
        )

        self.assertEqual(
            observation["observation_error"],
            "FUNCTION_CALLING_OBSERVATION_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
