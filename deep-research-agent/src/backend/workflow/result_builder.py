from dataclasses import asdict
from typing import Any

from backend.domain.models import ResearchState, TodoItem


class ResultBuilder:
    """把内部 ResearchState 转换为前端需要的结果、Trace 和错误报告。

    Workflow 内部使用 ResearchState 记录运行状态；前端不直接理解这个对象，
    所以由 ResultBuilder 统一输出稳定的 result 契约。

    举例：
    workflow_done 事件里的 payload.result 就来自 build_result()，
    前端会从里面读取 tasks、report、evaluator、reflection、traces。
    """

    def build_result(
            self,
            state: ResearchState,
    ) -> dict[str, Any]:
        """构建新工作台使用的最终结果。
            当前前端统一读取 result.tasks / result.report / result.evaluator，
            不再维护 plan/search/summaries 等旧返回结构。
        """
        return {
            "topic": state.topic,
            "backend": state.backend,
            "tasks": [asdict(task) for task in state.tasks],
            "report": state.report,
            "evaluator": state.evaluator,
            "errors": state.errors,
            "reflection":state.reflection,
            # 新增字段保持向后兼容；前端不读取时不会影响现有展示。
            "llm_usage": state.llm_usage,
            "traces": [
                self._build_trace(task, state.backend)
                for task in state.tasks
            ]
        }

    # 执行过程记录
    def _build_trace(
            self,
            task: TodoItem,
            backend: str = "unknown",
    ) -> dict[str, Any]:
        """构建单个任务的执行过程记录。
        TodoItem 是 dataclass，所以不能用 task.get(...)。
        这里统一读取 task.id / task.title / task.query / task.search_results。
        """
        sources = task.search_results or []

        return {
            "task_index": task.id,
            "title": task.title or "",
            "query": task.query or "",
            "stage": task.status or "unknown",
            "source_count": len(sources),
            "backend": backend or "unknown",
            "notices": task.notices,
            "summary": task.summary or "",
            "source_summary": task.source_summary or "",
            "top_sources": [
                {
                    "source_id": source.get("source_id") or "",
                    "title": source.get("title") or "",
                    "url": source.get("url") or "",
                    "source_type": source.get("source_type") or "",
                    "score": source.get("score") or 0,
                    "reasons": source.get("reasons") or [],
                }
                for source in sources
            ]
        }

    def append_task_failure_warning(
            self,
            report: str,
            tasks: list[TodoItem],
            errors: list[dict[str, Any]],
    ) -> str:
        """把部分任务失败信息追加到报告尾部。

        如果 4 个任务里 3 个成功、1 个失败，流程仍然可以生成报告；
        但需要在报告里明确说明哪个任务没纳入正文，避免用户误以为覆盖完整。
        """
        failed_tasks = [task for task in tasks if task.status == "failed"]
        if not failed_tasks:
            return report

        error_by_task_id = {
            error.get("task_id"): error
            for error in errors
            if error.get("stage") == "task"
        }

        lines = [
            report.rstrip(),
            "",
            "## 执行限制",
            "",
            "以下研究任务执行失败，未纳入最终报告正文：",
            "",
        ]

        for task in failed_tasks:
            error = error_by_task_id.get(task.id, {})
            message = error.get("message") or "未知错误"
            lines.append(f"- 任务 {task.id:02d}：{task.title}，原因：{message}")

        return "\n".join(lines)

    def build_error_report(
            self,
            stage: str,
            errors: list[dict[str, Any]]
    ) -> str:
        """构建流程失败时的兜底报告。

        planner / task / reporter 关键阶段失败时，前端仍然需要展示可读内容，
        所以这里生成一份包含失败阶段、错误信息和排查建议的 Markdown。
        """
        lines = [
            "# 研究流程未完成",
            "",
            "## 失败阶段",
            "",
            f"`{stage}`",
            "",
            "## 错误信息",
            "",
        ]
        for error in errors:
            lines.append(f"- **{error.get('stage', 'unknown')}**：{error.get('message', '')}")
        lines.extend([
            "",
            "## 建议",
            "",
            "- 检查 API Key、网络连接和搜索后端配置。",
            "- 查看 `deep-research-agent/logs/app.log` 获取完整异常日志。",
        ])
        return "\n".join(lines)
