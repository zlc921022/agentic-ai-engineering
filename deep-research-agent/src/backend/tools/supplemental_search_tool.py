"""Function Calling 使用的受限补充搜索工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.search.search_tool import SearchTool
from backend.tools.tool import Tool


class SupplementalSearchArguments(BaseModel):
    """只暴露模型真正需要决定的搜索语义，不暴露底层运行配置。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=3,
        max_length=300,
        description="针对当前证据缺口生成的一条补充检索语句。",
    )
    focus: Literal[
        "official",
        "academic",
        "implementation",
        "limitations",
        "general",
    ] = Field(description="补充证据的主要方向。")
    reason: str = Field(
        min_length=3,
        max_length=300,
        description="为什么现有来源仍不足以覆盖研究任务。",
    )


@dataclass(frozen=True)
class SupplementalSearchContext:
    """由 Python 注入的可信运行参数，模型无法通过 arguments 修改。"""

    backend: str
    requested_max_results: int
    mode: str
    fetch_full_page: bool
    max_tokens_per_source: int
    timeout_seconds: int


class SupplementalSearchTool(Tool):
    """执行一次补充网页搜索，并返回可交给 SourceQuality 再治理的候选来源。"""

    def __init__(self, search_tool: SearchTool) -> None:
        super().__init__(
            name="supplemental_search",
            description=(
                "当现有来源数量、质量或语义覆盖不足时，执行一次有明确方向的补充搜索。"
                "只用于补齐证据缺口，不要重复原始查询。"
            ),
        )
        self.search_tool = search_tool
        self.arguments_model = SupplementalSearchArguments

    def get_parameters(self) -> dict[str, Any]:
        """保留旧 Tool 接口需要的参数说明。"""
        return SupplementalSearchArguments.model_json_schema()

    def get_function_schema(self) -> dict[str, Any]:
        """返回给模型的最小 Schema。

        backend、结果数量、超时等参数由 SupplementalSearchContext 注入，不允许
        模型自行扩大访问范围或搜索成本。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": SupplementalSearchArguments.model_json_schema(),
            },
        }

    def run(
            self,
            parameters: dict[str, Any],
            *,
            context: object = None,
    ) -> dict[str, Any]:
        """根据受信任上下文执行底层 SearchTool。"""
        if not isinstance(context, SupplementalSearchContext):
            raise PermissionError("补充搜索缺少可信运行上下文。")

        query = str(parameters["query"]).strip()
        result = self.search_tool.run({
            "input": query,
            "max_results": context.requested_max_results,
            "mode": context.mode,
            "backend": context.backend,
            "fetch_full_page": context.fetch_full_page,
            "max_tokens_per_source": context.max_tokens_per_source,
            "timeout_seconds": context.timeout_seconds,
        })

        if not isinstance(result, dict):
            raise TypeError("补充搜索必须返回结构化结果。")

        raw_results = result.get("results") or []
        normalized_results = [
            {
                **item,
                # 记录来源由哪条 Function Calling query 找到，后续 Note 和日志
                # 可以和现有多查询搜索使用同一字段展示。
                "search_query": query,
            }
            for item in raw_results
            if isinstance(item, dict)
        ]
        return {
            **result,
            "results": normalized_results,
            "function_call": {
                "focus": parameters["focus"],
                "reason": parameters["reason"],
            },
        }
