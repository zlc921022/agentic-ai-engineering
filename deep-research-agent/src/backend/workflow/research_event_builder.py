from dataclasses import asdict
from typing import Any, Iterable

from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState, TodoItem
from backend.workflow.result_builder import ResultBuilder


class ResearchEventBuilder:
    """研究流程事件构造器，集中维护后端 SSE 事件协议。

    DeepResearchAgent 和 TaskExecutor 不直接手写 event dict，而是调用这里的方法。
    这样前端依赖的事件结构集中在一个类里，后续新增 tab、运行记录或阶段过滤时，
    不需要到 workflow/service 里到处找 payload。

    举例：
    - task_sources_done：告诉前端某个任务的检索来源已经完成；
    - evaluator_done：告诉前端质检器可以刷新；
    - reflection_done：告诉前端报告经过一次反思修正并完成复检。
    """
    emitter: EventEmitter = None
    state: ResearchState = None

    def __init__(
            self,
            result_builder: ResultBuilder
    ):
        """注入 result_builder，用于失败事件和 workflow_done 组装最终结果。"""
        self.result_builder = result_builder

    def register(
            self,
            emitter: EventEmitter,
            state: ResearchState
    ):
        """绑定本次 run 的 emitter 和 state。

        注意：这个类是 per-run 使用的，不建议作为全局单例复用。
        emitter 负责生成 seq / timestamp，state 负责提供当前任务、报告、质检信息。
        """
        self.emitter = emitter
        self.state = state

    def workflow_started(self) -> dict[str, Any]:
        """构造研究流程启动事件。"""
        return self.emitter.emit(
            "workflow_started",
            stage="workflow",
            status="started",
            message="研究流程启动",
            step=0,
            payload={
                "topic": self.state.topic,
                "backend": self.state.backend,
            },
        )

    def planner_done(self) -> dict[str, Any]:
        """构造 planner 完成事件，把任务列表一次性发给前端。"""
        return self.emitter.emit(
            "planner_done",
            stage="planner",
            status="completed",
            message="研究任务规划完成",
            step=1,
            payload={
                "tasks": [asdict(task) for task in self.state.tasks],
            },
        )

    def planner_failed(
            self,
            message: str,
    ) -> Iterable[dict[str, Any]]:
        """构造 planner 失败后的两个事件：阶段失败 + 全流程失败。"""
        yield self.emitter.emit(
            "planner_failed",
            stage="planner",
            status="failed",
            message=message,
            step=1,
            payload={
                "errors": self.state.errors,
            },
            error={
                "message": message,
            },
        )

        yield self.emitter.emit(
            "workflow_failed",
            stage="workflow",
            status="failed",
            message="研究流程已停止",
            step=1,
            payload={
                "result": self.result_builder.build_result(self.state),
            },
            error={
                "message": message,
            },
        )

    def reporter_start(self, completed_tasks) -> dict[str, Any]:
        """构造最终报告开始生成事件。"""
        return self.emitter.emit(
            "report_started",
            stage="reporter",
            status="started",
            message="开始生成最终报告",
            step=4,
            payload={
                "task_count": len(self.state.tasks),
                "completed_tasks": len(completed_tasks),
            },
        )

    def reporter_doing(self, chunk):
        """构造 reporter 流式增量事件。"""
        return self.emitter.emit(
            "llm_delta",
            stage="llm",
            status="running",
            message="最终报告生成中",
            step=4,
            payload={
                "business_stage": "reporter",
                "stream_key": "reporter",
                "delta": chunk,
            },
        )

    def reporter_done(self):
        """构造最终报告完成事件，携带完整 report 文本。"""
        return self.emitter.emit(
            "report_done",
            stage="reporter",
            status="completed",
            message="最终报告生成完成",
            step=4,
            payload={
                "report": self.state.report,
            },
        )

    def reporter_failed(
            self,
            message: str,
    ) -> Iterable[dict[str, Any]]:
        """构造 reporter 失败后的阶段失败和 workflow_failed 事件。"""
        state = self.state
        yield self.emitter.emit(
            "report_failed",
            stage="reporter",
            status="failed",
            message=message,
            step=4,
            payload={
                "errors": state.errors,
                "result": self.result_builder.build_result(state),
            },
            error={
                "message": message,
            },
        )

        yield self.emitter.emit(
            "workflow_failed",
            stage="workflow",
            status="failed",
            message="研究流程已停止",
            step=4,
            payload={
                "result": self.result_builder.build_result(state),
            },
            error={
                "message": message,
            },
        )

    def task_status_started(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务状态进入 in_progress 的事件。"""
        return emitter.emit(
            "task_status",
            stage="task",
            status="in_progress",
            message=f"开始执行任务：{task.title}",
            step=2,
            task_id=task.id,
            payload={"task": asdict(task)},
        )

    def task_started(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务开始事件，用于运行记录展示任务起点。"""
        return emitter.emit(
            "task_started",
            stage="task",
            status="started",
            message=f"开始任务：{task.title}",
            step=2,
            task_id=task.id,
            payload={"task": asdict(task)},
        )

    def task_sources_done(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            search_observation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造任务检索完成事件，携带来源数量和 task 快照。"""
        return emitter.emit(
            "task_sources_done",
            stage="searcher",
            status="completed",
            message=f"任务检索完成：{task.title}",
            step=2,
            task_id=task.id,
            payload={
                "task": asdict(task),
                "source_count": len(task.search_results),
                # 仅新增旁路字段；不包含网页正文、完整 Tool Result 或异常堆栈。
                "search_observation": search_observation or {},
            },
        )

    def task_sources_note_updated(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            payload: dict[str, Any],
    ) -> dict[str, Any]:
        """构造任务笔记来源更新事件。"""
        return emitter.emit(
            "note_event",
            stage="searcher",
            status="completed",
            message="search 更新来源",
            step=2,
            task_id=task.id,
            payload=payload,
        )

    def task_summary_started(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务总结开始事件。"""
        return emitter.emit(
            "task_summary_started",
            stage="summary",
            status="started",
            message=f"开始总结任务：{task.title}",
            step=3,
            task_id=task.id,
            payload={"task": asdict(task)},
        )

    def task_summary_delta(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            chunk: str,
    ) -> dict[str, Any]:
        """构造任务总结 LLM 流式增量事件。"""
        return emitter.emit(
            "llm_delta",
            stage="llm",
            status="running",
            message="任务总结生成中",
            step=3,
            task_id=task.id,
            payload={
                "business_stage": "summary",
                "stream_key": f"summary_task_{task.id}",
                "delta": chunk,
            },
        )

    def task_status_completed(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务状态完成事件，携带总结和来源摘要。"""
        return emitter.emit(
            "task_status",
            stage="task",
            status="completed",
            message=f"任务完成：{task.title}",
            step=3,
            task_id=task.id,
            payload={
                "task": asdict(task),
                "summary": task.summary,
                "sources_summary": task.source_summary,
            },
        )

    def task_summary_done(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务总结完成事件。"""
        return emitter.emit(
            "task_summary_done",
            stage="summary",
            status="completed",
            message=f"任务总结完成：{task.title}",
            step=3,
            task_id=task.id,
            payload={"task": asdict(task)},
        )

    def task_done(self, emitter: EventEmitter, task: TodoItem) -> dict[str, Any]:
        """构造任务完成事件，用于运行记录收口。"""
        return emitter.emit(
            "task_done",
            stage="task",
            status="completed",
            message=f"任务完成：{task.title}",
            step=3,
            task_id=task.id,
            payload={"task": asdict(task)},
        )

    def task_summary_note_updated(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            payload: dict[str, Any],
    ) -> dict[str, Any]:
        """构造任务笔记总结更新事件。"""
        return emitter.emit(
            "note_event",
            stage="summary",
            status="completed",
            message="summary 更新总结",
            step=3,
            task_id=task.id,
            payload=payload,
        )

    def task_status_failed(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            exc: Exception,
    ) -> dict[str, Any]:
        """构造任务状态失败事件，payload 和 error 都保留异常信息。"""
        return emitter.emit(
            "task_status",
            stage="task",
            status="failed",
            message=f"任务失败：{task.title}",
            step=3,
            task_id=task.id,
            payload={
                "task": asdict(task),
                "detail": str(exc),
            },
            error={
                "message": str(exc),
                "type": exc.__class__.__name__,
            },
        )

    def task_failed(
            self,
            emitter: EventEmitter,
            task: TodoItem,
            exc: Exception,
    ) -> dict[str, Any]:
        """构造任务失败事件，用于运行记录展示失败节点。"""
        return emitter.emit(
            "task_failed",
            stage="task",
            status="failed",
            message=f"任务失败：{task.title}",
            step=3,
            task_id=task.id,
            payload={"task": asdict(task)},
            error={
                "message": str(exc),
                "type": exc.__class__.__name__,
            },
        )

    def evaluator_done(self, pass_name: str) -> dict[str, Any]:
        """构造报告质检完成事件。

        pass_name 用于区分 initial 初检和 final 复检，前端可以据此展示
        “报告初检完成 / 报告复检完成”。
        """
        message = {
            "initial": "报告初检完成",
            "final": "报告复检完成",
        }.get(pass_name, "报告质检完成")
        return self.emitter.emit(
            "evaluator_done",
            stage="evaluator",
            status="completed",
            message=message,
            step=5,
            payload={
                "evaluator": self.state.evaluator,
                "name": pass_name
            },
        )

    def reflection_started(self) -> dict[str, Any]:
        """构造报告反思修正开始事件。"""
        return self.emitter.emit(
            "reflection_started",
            stage="reflection",
            status="started",
            message="质检未达标，开始反思修正报告",
            step=5,
            payload={
                "reflection": self.state.reflection,
            },
        )

    def reflection_done(self) -> dict[str, Any]:
        """构造反思修正完成事件，携带修正后的 report。"""
        return self.emitter.emit(
            "reflection_done",
            stage="reflection",
            status="completed",
            message="报告反思修正与复检完成",
            step=5,
            payload={
                "reflection": self.state.reflection,
                "report": self.state.report,
            },
        )

    def reflection_skipped(self, reflection, reasons) -> dict[str, Any]:
        """构造反思跳过事件。

        质检通过或未达到触发阈值时会进入这个分支，运行记录里会显示为 skipped。
        """
        return self.emitter.emit(
            "reflection_skipped",
            stage="reflection",
            status="skipped",
            message="报告质检通过，跳过反思修正",
            step=5,
            payload={
                "reflection": reflection,
                "reason": reasons,
            }
        )

    def reflection_failed(self, message : str) -> dict[str, Any]:
        """构造反思修正失败事件。

        失败时保留 reporter 初稿，不让反思失败破坏已有结果。
        """
        return self.emitter.emit(
            "reflection_failed",
            stage="reflection",
            status="failed",
            message="报告反思修正失败，保留初稿报告",
            step=5,
            payload={
                "reflection": self.state.reflection,
                "errors": self.state.errors,
            },
            error={
                "message": message,
            },
        )

    def create_plan_note(self, task_id: int, payload) -> dict[str, Any]:
        """构造 planner 创建任务笔记事件。"""
        return self.emitter.emit(
            "note_event",
            stage="planner",
            status="completed",
            message="planner 创建任务笔记",
            step=1,
            task_id=task_id,
            payload=payload,
        )

    def create_report_note(self, payload) -> dict[str, Any]:
        """构造 reporter 创建最终报告笔记事件。"""
        return self.emitter.emit(
            "note_event",
            stage="reporter",
            status="completed",
            message="report 创建报告笔记",
            step=4,
            payload=payload
        )

    def workflow_done(self) -> dict[str, Any]:
        """构造研究流程完成事件，携带最终 result。"""
        return self.emitter.emit(
            "workflow_done",
            stage="workflow",
            status="completed",
            message="研究流程完成",
            step=6,
            payload={
                "result": self.result_builder.build_result(self.state),
            },
        )
