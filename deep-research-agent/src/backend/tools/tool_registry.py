import logging
import time
from typing import Any
from typing import Optional

from backend.tools.tool import Tool


logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表。

    它是 Agent 和具体工具之间的中间层：
    Agent 只知道要调用某个 tool_name，ToolRegistry 负责查找工具实例并执行。
    当前深度研究主流程主要直接调用 SearchService，不强依赖模型工具调用；
    但保留这个抽象方便后续扩展真正的 tool-calling Agent。
    """

    def __init__(self):
        """初始化工具字典。"""
        self.tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool):
        """注册或覆盖一个工具。"""
        if tool.name in self.tools:
            logger.warning("tool already registered name=%s", tool.name)
        self.tools[tool.name] = tool

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """按名称获取工具，不存在返回 None。"""
        if tool_name in self.tools:
            return self.tools[tool_name]
        else:
            return None

    def unregister_tool(self, tool: Tool):
        """注销一个工具。"""
        if tool.name in self.tools:
            del self.tools[tool.name]

    def execute_tool(self, name : str, input_text: str) -> Optional[str]:
        """执行工具并把异常转换成文本结果。

        这里不抛异常给 LLM，避免工具调用失败直接打断 Agent 对话。
        """
        try:
            if name in self.tools:
                tool = self.tools[name]
                return tool.run({"input": input_text})
            return f"工具不存在: {name}"
        except Exception as e:
            return f"错误：执行工具 '{name}' 时发生异常: {str(e)}"

    def get_function_schemas(self) -> list[dict[str, Any]]:
        """汇总注册工具的原生 Function Calling Schema。"""
        return [tool.get_function_schema() for tool in self.tools.values()]

    def execute_function(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            context: object = None,
    ) -> dict[str, Any]:
        """校验并执行一次原生工具调用，返回适合回传模型的标准结果。

        第一版工具都是只读能力。这里统一吞掉业务异常并返回错误码，保证单个工具
        失败不会直接打断 Deep Research 主流程。
        """
        started_at = time.perf_counter()
        tool = self.get_tool(name)
        if tool is None:
            return self._function_error(
                code="TOOL_NOT_FOUND",
                message=f"工具不存在: {name}",
                started_at=started_at,
            )

        if not isinstance(arguments, dict):
            return self._function_error(
                code="INVALID_ARGUMENTS",
                message="工具参数必须是 JSON object。",
                started_at=started_at,
            )

        try:
            validated_arguments = tool.validate_parameters(arguments)
        except ValueError as exc:
            return self._function_error(
                code="INVALID_ARGUMENTS",
                message=str(exc),
                started_at=started_at,
            )

        try:
            data = tool.run(validated_arguments, context=context)
        except PermissionError as exc:
            return self._function_error(
                code="PERMISSION_DENIED",
                message=str(exc) or "当前上下文不允许调用该工具。",
                started_at=started_at,
            )
        except TimeoutError:
            return self._function_error(
                code="TOOL_TIMEOUT",
                message="工具响应超时，请稍后重试。",
                started_at=started_at,
                retryable=True,
            )
        except Exception:
            logger.exception("function tool failed name=%s", name)
            return self._function_error(
                code="TOOL_EXECUTION_FAILED",
                message="工具执行失败，请稍后重试。",
                started_at=started_at,
                retryable=True,
            )

        return {
            "success": True,
            "data": data,
            "error": None,
            "meta": {
                "duration_ms": self._duration_ms(started_at),
            },
        }

    def get_tool_description(self) -> str:
        """生成工具列表说明，供 SimpleAgent 拼到 system prompt。"""
        if not self.tools:
            return "没有工具可以调用"
        return "\n".join(
            f"{tool.name} : {tool.description}"
            for tool in self.tools.values()
        )

    @classmethod
    def _function_error(
            cls,
            *,
            code: str,
            message: str,
            started_at: float,
            retryable: bool = False,
    ) -> dict[str, Any]:
        """构造统一工具错误，避免把 Python 堆栈和内部配置泄漏给模型。"""
        return {
            "success": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
            "meta": {
                "duration_ms": cls._duration_ms(started_at),
            },
        }

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, round((time.perf_counter() - started_at) * 1000))
