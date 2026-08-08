"""Deep Research 使用的原生 Function Calling Agent。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.llm.client import NativeToolCall, QwenChatClient
from backend.llm.usage import usage_stage_scope
from backend.tools.tool_registry import ToolRegistry


@dataclass(frozen=True)
class FunctionToolExecution:
    """记录模型的一次工具请求以及 Python 后端的真实执行结果。"""

    call_id: str
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class FunctionCallingRunResult:
    """补检索调用结果，SearchService 只消费成功工具返回的结构化数据。"""

    final_answer: str = ""
    executions: list[FunctionToolExecution] = field(default_factory=list)

    def successful_tool_data(self, tool_name: str) -> list[Any]:
        """按工具名提取成功结果，失败结果仍保留在 executions 供日志排查。"""
        return [
            execution.result.get("data")
            for execution in self.executions
            if execution.name == tool_name
            and execution.result.get("success")
            and execution.result.get("data") is not None
        ]


class FunctionCallingAgent:
    """执行“模型请求工具 → Python 执行 → 结果回传模型”的原生循环。

    第一版只为补检索服务，并通过 ``forced_tool_name`` 强制模型生成一次
    ``supplemental_search`` 参数。工具执行后仍会把 result 作为 ``tool`` 消息
    回传模型，完整走通原生 Function Calling 协议。
    """

    def __init__(
            self,
            llm: QwenChatClient,
            tool_registry: ToolRegistry,
            *,
            system_prompt: str,
            max_steps: int = 2,
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt.strip()
        self.max_steps = max(1, max_steps)

    def run(
            self,
            input_text: str,
            *,
            context: object = None,
            forced_tool_name: str | None = None,
    ) -> FunctionCallingRunResult:
        """执行一次独立工具会话。

        messages 只在本次研究任务内存在，避免并发 TodoItem 共用消息历史。
        第一轮可强制指定工具；执行成功后第二轮禁止继续调用，避免模型重复补搜。
        """
        schemas = self.tool_registry.get_function_schemas()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": input_text},
        ]
        result = FunctionCallingRunResult()
        executed_signatures: set[str] = set()

        for step in range(self.max_steps):
            tool_choice = self._tool_choice(
                step=step,
                forced_tool_name=forced_tool_name,
            )
            with usage_stage_scope("supplemental_search"):
                response = self.llm.chat(
                    messages,
                    tools=schemas,
                    tool_choice=tool_choice,
                    temperature=0.1,
                    max_tokens=1024,
                    # DashScope 思考模式不支持强制指定 tool_choice。这里关闭思考
                    # 只影响轻量的工具参数生成，不影响 Planner / Summary / Report。
                    force_non_thinking=bool(forced_tool_name),
                )
            messages.append(response.assistant_message)

            if not response.tool_calls:
                result.final_answer = response.content.strip()
                break

            for tool_call in response.tool_calls:
                arguments = self._parse_arguments(tool_call)
                signature = self._call_signature(tool_call.name, arguments)
                if signature in executed_signatures:
                    tool_result = {
                        "success": False,
                        "data": None,
                        "error": {
                            "code": "DUPLICATE_TOOL_CALL",
                            "message": "相同参数的工具调用已经执行，本次不再重复搜索。",
                            "retryable": False,
                        },
                        "meta": {"duration_ms": 0},
                    }
                else:
                    executed_signatures.add(signature)
                    tool_result = self.tool_registry.execute_function(
                        tool_call.name,
                        arguments,
                        context=context,
                    )

                result.executions.append(
                    FunctionToolExecution(
                        call_id=tool_call.id,
                        name=tool_call.name,
                        arguments=arguments,
                        result=tool_result,
                    )
                )
                # tool_call_id 必须与模型提出请求时的 id 完全一致，否则模型无法
                # 将这条工具结果关联到对应的 Function Call。
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

        return result

    @staticmethod
    def _tool_choice(
            *,
            step: int,
            forced_tool_name: str | None,
    ) -> str | dict[str, Any]:
        """第一轮强制补检索，后续轮只允许模型整理工具结果。"""
        if step == 0 and forced_tool_name:
            return {
                "type": "function",
                "function": {"name": forced_tool_name},
            }
        return "none"

    @staticmethod
    def _parse_arguments(tool_call: NativeToolCall) -> dict[str, Any]:
        """解析模型参数；非法 JSON 交给 Registry 返回标准校验错误。"""
        try:
            arguments = json.loads(tool_call.arguments)
        except json.JSONDecodeError:
            return {"__invalid_json__": tool_call.arguments}
        return arguments if isinstance(arguments, dict) else {
            "__invalid_json__": tool_call.arguments,
        }

    @staticmethod
    def _call_signature(name: str, arguments: dict[str, Any]) -> str:
        """构造稳定调用签名，用于抑制同一轮内完全重复的搜索。"""
        return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"
