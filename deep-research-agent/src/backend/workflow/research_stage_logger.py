import logging
import time

from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState


class ResearchStageLogger:
    """研究阶段日志器，集中记录后端可观测性日志。

    这个类和 ResearchEventBuilder 是一对：
    - ResearchEventBuilder 面向前端，生成 SSE 运行记录；
    - ResearchStageLogger 面向后端，写入 app.log 方便排查问题。

    举例：
    如果某个任务检索到 0 个来源，前端会看到 searcher 阶段事件，
    后端日志也会记录 task_id、backend、notices、elapsed，方便定位是
    搜索后端失败、过滤过严，还是 query 本身质量不够。
    """
    emitter: EventEmitter = None
    state: ResearchState = None

    def __init__(self,
                 logger: logging.Logger, ):
        """注入标准 logging.Logger。"""
        self.logger = logger

    def init_logger(
            self,
            event_emitter: EventEmitter,
            research_state: ResearchState,
    ):
        """绑定本次 run 的 emitter/state。

        和事件构造器一样，这里也是 per-run 绑定，避免并发请求日志上下文混淆。
        """
        self.emitter = event_emitter
        self.state = research_state

    def research_started(self):
        """记录研究流程启动。"""
        self.logger.info(
            "research run started run_id=%s topic=%s backend=%s",
            self.emitter.run_id,
            self.state.topic,
            self.state.backend,
        )

    def planner_started(self):
        """记录 planner 开始。"""
        self.logger.info(
            "planner started run_id=%s topic=%s",
            self.emitter.run_id,
            self.state.topic,
        )

    def planner_done(
            self,
            started_at
    ):
        """记录 planner 完成，包括任务数量和任务标题。"""
        tasks = self.state.tasks
        self.logger.info(
            "planner done run_id=%s task_count=%s tasks=%s elapsed=%.2fs",
            self.emitter.run_id,
            len(tasks),
            [task.title for task in tasks],
            time.perf_counter() - started_at,
        )

    def planner_failed(
            self,
            started_at,
            message: str
    ):
        """记录 planner 失败。"""
        self.logger.info(
            "planner failed run_id=%s message=%s errors=%s elapsed=%.2fs",
            self.emitter.run_id,
            message,
            len(self.state.errors),
            time.perf_counter() - started_at,
        )

    def research_stop(
            self,
            run_started_at: float,
            msg: str
    ):
        """记录流程提前停止。"""
        self.logger.info(
            msg,
            self.emitter.run_id,
            len(self.state.errors),
            time.perf_counter() - run_started_at,
        )

    def tasks_started(self, max_workers: int):
        """记录并发任务执行开始。"""
        self.logger.info(
            "tasks execution started run_id=%s task_count=%s max_workers=%s",
            self.emitter.run_id,
            len(self.state.tasks),
            max_workers,
        )

    def tasks_done(
            self,
            started_at: float,
    ):
        """记录全部并发任务执行完成。"""
        self.logger.info(
            "tasks execution done run_id=%s task_count=%s elapsed=%.2fs",
            self.emitter.run_id,
            len(self.state.tasks),
            time.perf_counter() - started_at,
        )

    def single_task_started(self, id, title, query):
        """记录单个任务开始执行。"""
        self.logger.info(
            "task started run_id=%s task_id=%s title=%s query=%s",
            self.emitter.run_id,
            id,
            title,
            query,
        )

    def task_search_started(self, id, query):
        """记录单个任务开始检索。"""
        self.logger.info(
            "task search started run_id=%s task_id=%s backend=%s query=%s",
            self.emitter.run_id,
            id,
            self.state.backend,
            query,
        )

    def task_search_done(
            self,
            id,
            search_backend_from_result,
            search_results,
            notices,
            search_started_at
    ):
        """记录单个任务检索完成。"""
        self.logger.info(
            "task search done run_id=%s task_id=%s backend=%s sources=%s notices=%s elapsed=%.2fs",
            self.emitter.run_id,
            id,
            search_backend_from_result,
            len(search_results),
            len(notices),
            time.perf_counter() - search_started_at,
        )

    def task_summary_started(self, id, title, search_results):
        """记录单个任务开始总结。"""
        self.logger.info(
            "task summary started run_id=%s task_id=%s title=%s source_count=%s",
            self.emitter.run_id,
            id,
            title,
            len(search_results),
        )

    def task_summary_done(self, id, summary, summary_started_at):
        """记录单个任务总结完成。"""
        self.logger.info(
            "task summary done run_id=%s task_id=%s summary_chars=%s elapsed=%.2fs",
            self.emitter.run_id,
            id,
            len(summary or ""),
            time.perf_counter() - summary_started_at,
        )

    def task_failed_exception(self, id, title):
        """记录任务异常，使用 logger.exception 自动带 traceback。"""
        self.logger.exception(
            "task failed run_id=%s task_id=%s title=%s",
            self.emitter.run_id,
            id,
            title,
        )

    def single_task_done(self, id, status, started_at):
        """记录单个任务最终完成状态。"""
        self.logger.info(
            "task done run_id=%s task_id=%s status=%s elapsed=%.2fs",
            self.emitter.run_id,
            id,
            status,
            time.perf_counter() - started_at,
        )

    def reporter_started(self, completed_tasks):
        """记录 reporter 开始生成最终报告。"""
        self.logger.info(
            "reporter started run_id=%s topic=%s task_count=%s completed_tasks=%s",
            self.emitter.run_id,
            self.state.topic,
            len(self.state.tasks),
            len(completed_tasks),
        )

    def reporter_failed(
            self,
            message: str,
            started_at: float,
    ):
        """记录 reporter 失败。"""
        self.logger.info(
            "reporter failed run_id=%s message=%s errors=%s elapsed=%.2fs",
            self.emitter.run_id,
            message,
            len(self.state.errors),
            time.perf_counter() - started_at,
        )

    def reporter_done(self, started_at: float):
        """记录 reporter 完成。"""
        self.logger.info(
            "reporter done run_id=%s report_chars=%s elapsed=%.2fs",
            self.emitter.run_id,
            len(self.state.report or ""),
            time.perf_counter() - started_at,
        )

    def research_done(
            self,
            run_started_at: float
    ):
        """记录研究流程完整结束。"""
        self.logger.info(
            "research run done run_id=%s task_count=%s errors=%s report_chars=%s elapsed=%.2fs",
            self.emitter.run_id,
            len(self.state.tasks),
            len(self.state.errors),
            len(self.state.report or ""),
            time.perf_counter() - run_started_at,
        )

    def evaluator_started(self):
        """记录报告质检开始。"""
        self.logger.info(
            "evaluator started run_id=%s report_chars=%s",
            self.emitter.run_id,
            len(self.state.report or ""),
        )

    def evaluator_done(
            self,
            evaluate_started_at: float,
    ):
        """记录报告质检完成。"""
        self.logger.info(
            "evaluator done run_id=%s score=%s warnings=%s elapsed=%.2fs",
            self.emitter.run_id,
            self.state.evaluator.get("overall_score"),
            len(self.state.evaluator.get("warnings") or []),
            time.perf_counter() - evaluate_started_at,
        )

    def reflection_started(self, triggers: list[str]):
        """记录报告反思修正开始。"""
        self.logger.info(
            "reflection started run_id=%s triggers=%s report_chars=%s",
            self.emitter.run_id,
            triggers,
            len(self.state.report or ""),
        )

    def reflection_done(self, started_at: float):
        """记录报告反思修正完成。"""
        self.logger.info(
            "reflection done run_id=%s report_chars=%s elapsed=%.2fs",
            self.emitter.run_id,
            len(self.state.report or ""),
            time.perf_counter() - started_at,
        )

    def reflection_skipped(self):
        """记录报告反思跳过。"""
        self.logger.info(
            "reflection skipped run_id=%s score=%s",
            self.emitter.run_id,
            self.state.evaluator.get("overall_score"),
        )

    def reflection_failed(self, message: str, started_at: float):
        """记录报告反思失败。"""
        self.logger.info(
            "reflection failed run_id=%s message=%s elapsed=%.2fs",
            self.emitter.run_id,
            message,
            time.perf_counter() - started_at,
        )
