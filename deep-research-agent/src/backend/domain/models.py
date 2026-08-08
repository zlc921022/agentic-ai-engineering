from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    """单个任务搜索阶段的标准输出。

    results 是结构化来源数据；search_results_text 是给 SummaryService 的
    长研究上下文，两者服务的对象不同。
    """
    task_id: int
    title: str
    intent: str
    query: str
    results: str | dict[str, Any]
    search_results_text: str
    # 只用于 SSE/Benchmark 的旁路指标，不参与 Summary prompt 或来源筛选。
    observation: dict[str, Any] = field(default_factory=dict)

@dataclass
class TodoItem:
    """Planner 生成的子研究任务。

    生命周期：
    pending -> searching -> summarizing -> completed / failed。
    同一个 TodoItem 会在搜索、总结、笔记、最终报告阶段不断补充字段。
    """
    id: int
    title: str
    intent: str
    query: str
    status: str = "pending"
    search_results: list[dict[str, Any]] = field(default_factory=list)
    source_summary: str = ""
    summary: str = ""
    notices: list[str] = field(default_factory=list)

    note_id: str | None = None
    note_path: str | None = None
    stream_token: str | None = None


@dataclass
class ResearchState:
    """一次研究运行的内存状态。

    ResearchState 是 workflow 内部的状态容器：
    - tasks：所有子任务；
    - report：最终报告；
    - evaluator：质检结果；
    - reflection：反思修正状态；
    - errors：各阶段错误列表。
    """
    topic: str
    backend: str = "hybrid"
    tasks: list[TodoItem] = field(default_factory=list)
    report: str = ""
    evaluator: dict[str, Any] = field(default_factory=dict)
    reflection: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    # 模型响应结束后汇总的 Token 数据；为空表示供应商没有返回 usage。
    llm_usage: dict[str, Any] = field(default_factory=dict)
