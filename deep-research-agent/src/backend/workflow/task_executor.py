import time
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from queue import Queue
from threading import Lock
from typing import Iterator, Any, Callable

from backend.core.config import Config
from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState, TodoItem, SearchResult
from backend.llm.usage import usage_run_scope, usage_task_scope
from backend.notes.note_service import NoteService
from backend.workflow.research_event_builder import ResearchEventBuilder
from backend.workflow.research_stage_logger import ResearchStageLogger
from backend.services.search_service import SearchService
from backend.services.summary_service import SummaryService


class TaskExecutor:
    """并发执行子研究任务，并把 search/summary 过程转换成稳定 SSE 事件。

    这个类只负责“任务怎么跑”，不负责 planner、reporter、evaluator。
    典型执行模型：
    - 任务 1、2、3、4 可以并发；
    - 每个任务内部仍然串行：search -> summary -> note update；
    - worker 线程不直接 yield SSE，而是把事件放入 Queue，由主线程统一输出。

    举例：
    Planner 拆出 4 个研究任务后，TaskExecutor 会开最多 task_max_workers
    个 worker 并发检索和总结，从而缩短总耗时，同时用 event_lock 保证事件序号稳定。
    """
    event_builder: ResearchEventBuilder = None
    stage_logger: ResearchStageLogger = None

    def __init__(
            self,
            config: Config,
            logger: Logger,
            search_service: SearchService,
            note_service: NoteService | None,
            summary_service: SummaryService,
    ):
        """注入任务执行所需服务。

        TaskExecutor 不自己创建 SearchService / SummaryService，方便测试时替换成
        fake service，也让 DeepResearchAgent 统一管理依赖。
        """
        self.config = config
        self.logger = logger
        self.search_service = search_service
        self.note_service = note_service
        self.summary_service = summary_service

    def bind(
            self,
            event_builder: ResearchEventBuilder,
            stage_logger: ResearchStageLogger
    ):
        """绑定本次 run 的事件构造器和日志器。

        event_builder / stage_logger 都和单次 run 的 emitter/state 绑定，
        所以这里在每次 run 创建 TaskExecutor 后再 bind，避免并发请求互相串状态。
        """
        self.event_builder = event_builder
        self.stage_logger = stage_logger

    def execute_tasks_stream(
            self,
            state: ResearchState,
            emitter: EventEmitter
    ) -> Iterator[dict[str, Any]]:
        """并发执行任务列表。
        并发边界：Ø
        - 多个 TodoItem 可以并发执行；
        - 单个 TodoItem 内部仍然串行执行：search -> summary；
        - reporter / evaluator 不在这里执行，等所有任务结束后再由 run_stream 继续。
        当前并发模型：
        - 外层任务并发；
        - 每个任务内部流程简单稳定；
        - SSE 事件由主线程统一 yield，避免 worker 线程直接操作响应流。
        """
        event_queue: Queue[dict[str, Any]] = Queue()
        event_lock = Lock()
        state_lock = Lock()

        max_workers = min(
            self.config.task_max_workers,
            len(state.tasks),
        ) or 1
        started_at = time.perf_counter()
        self.stage_logger.tasks_started(max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._task_worker,
                    state=state,
                    task=task,
                    emitter=emitter,
                    event_queue=event_queue,
                    state_lock=state_lock,
                    event_lock=event_lock,
                )
                for task in state.tasks
            ]

            yield from self._consume_task_event(
                event_queue=event_queue,
                total=len(futures),
            )

            # future.result() 的作用：
            # 1. 确保线程池里的任务真正结束；
            # 2. 如果 worker 外层还有未捕获异常，这里会重新抛出，方便后端日志暴露问题。
            for future in futures:
                future.result()

        self.stage_logger.tasks_done(started_at)

    def _task_worker(
            self,
            state: ResearchState,
            task: TodoItem,
            emitter: EventEmitter,
            event_queue: Queue[dict[str, Any]],
            event_lock: Lock,
            state_lock: Lock,
    ):
        """线程池里的 worker。
        worker 不直接 yield 事件，只把事件放进 event_queue。
        主线程会从 event_queue 里取事件并返回给前端。
        """
        # ContextVar 不会自动复制到新线程，因此 worker 显式恢复 run/task 关联。
        # 这层上下文只影响 Usage 标签，不改变 search -> summary 执行顺序。
        with usage_run_scope(emitter.run_id), usage_task_scope(task.id):
            try:
                self._execute_single_task_stream(
                    state=state,
                    task=task,
                    emitter=emitter,
                    event_queue=event_queue,
                    event_lock=event_lock
                )
            except Exception as exc:
                self._handle_task_error(
                    state=state,
                    task=task,
                    exc=exc,
                    emitter=emitter,
                    event_queue=event_queue,
                    event_lock=event_lock,
                    state_lock=state_lock
                )
            finally:
                # 内部控制事件，只用于主线程统计完成数，不发给前端。
                event_queue.put({
                    "type": "__task_done__",
                    "task_id": task.id,
                })

    def _execute_single_task_stream(
            self,
            state: ResearchState,
            task: TodoItem,
            emitter: EventEmitter,
            event_queue: Queue[dict[str, Any]],
            event_lock: Lock,
    ):
        """串行执行单个任务。
        注意：
        - 这里不要再开线程；
        - search 完成后再 summary；
        - summary 使用 SummaryService 内部的独立 summary agent，避免任务历史串扰。
        """
        started_at = time.perf_counter()
        self.stage_logger.single_task_started(
            task.id, task.title, task.query
        )
        task.status = "searching"
        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_status_started(emitter, task)
        )

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_started(emitter, task)
        )

        search_started_at = time.perf_counter()
        self.stage_logger.task_search_started(
            task.id, task.query,
        )
        search_result = self.search_service.run_search(
            task=task,
            backend=state.backend,
            max_results=self.config.search_max_results,
            # Tavily 支持 raw_content；其它后端继续使用摘要，避免无效全文请求。
            fetch_full_page=(
                    self.config.fetch_full_page
                    and state.backend == "tavily"
            ),
            max_tokens_per_source=self.config.max_tokens_per_source,
            enable_multi_query_search=self.config.enable_multi_query_search,
            query_variant_count=self.config.search_query_variant_count,
        )
        self.apply_search_result(search_result, task)

        self.stage_logger.task_search_done(
            id=task.id,
            search_started_at=search_started_at,
            search_results=task.search_results,
            notices=task.notices,
            search_backend_from_result=self._search_backend_from_result(search_result)
        )

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_sources_done(
                emitter,
                task,
                search_result.observation,
            )
        )

        # 更新笔记来源
        source_note = (
            self.note_service.update_note_sources(
                task,
                run_id=emitter.run_id,
            )
            if self.note_service
            else None
        )
        if source_note and self.note_service:
            payload = self.note_service.build_event_payload(
                source_note,
                action="update",
                label="search 更新来源",
            )
            self._enqueue_event(
                event_queue=event_queue,
                event_lock=event_lock,
                build_event=lambda: self.event_builder.task_sources_note_updated(
                    emitter=emitter,
                    task=task,
                    payload=payload
                ),
            )

        task.status = "summarizing"
        summary_started_at = time.perf_counter()
        self.stage_logger.task_summary_started(
            task.id, task.title, task.search_results
        )
        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_summary_started(emitter, task)
        )

        summary_stream, get_summary = self.summary_service.stream_summary(search_result)
        try:
            for chunk in summary_stream:
                self._enqueue_event(
                    event_queue=event_queue,
                    event_lock=event_lock,
                    build_event=lambda: self.event_builder.task_summary_delta(emitter, task, chunk)
                )
        finally:
            task.summary = get_summary() or ""
            task.status = "completed"

        self.stage_logger.task_summary_done(
            id=task.id,
            summary=task.summary,
            summary_started_at=summary_started_at,
        )

        # summary 流式 chunk 只负责追加内容，任务状态由 task_status 统一收口。
        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_status_completed(emitter, task)
        )

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_summary_done(emitter, task)
        )
        self.stage_logger.single_task_done(
            task.id, task.status, started_at
        )

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_done(emitter, task)
        )

        summary_note = (
            self.note_service.update_note_summary(
                task,
                run_id=emitter.run_id,
            )
            if self.note_service
            else None
        )
        if summary_note and self.note_service:
            note_payload = self.note_service.build_event_payload(
                summary_note,
                action="update",
                label="summary 更新总结",
            )
            self._enqueue_event(
                event_queue=event_queue,
                event_lock=event_lock,
                build_event=lambda: self.event_builder.task_summary_note_updated(emitter, task, note_payload)
            )

    def _consume_task_event(
            self,
            event_queue: Queue[dict[str, Any]],
            total: int,
    ) -> Iterator[dict[str, Any]]:
        """主线程消费 worker 事件。
        worker 每完成一个任务都会放入 TASK_DONE_EVENT。
        收到 total 个完成信号后，说明所有任务都结束了。
        """
        finished = 0
        while finished < total:
            event = event_queue.get()
            if event.get("type") == "__task_done__":
                finished += 1
                continue

            yield event

    def _handle_task_error(
            self,
            state: ResearchState,
            task: TodoItem,
            exc: Exception,
            emitter: EventEmitter,
            event_queue: Queue[dict[str, Any]],
            event_lock: Lock,
            state_lock: Lock,
    ) -> None:
        """统一处理单个任务异常。"""
        self.stage_logger.task_failed_exception(
            task.id,
            task.title,
        )
        task.status = "failed"
        if self.note_service:
            self.note_service.update_task_status(
                task,
                run_id=emitter.run_id,
            )

        with state_lock:
            state.errors.append({
                "stage": "task",
                "task_id": task.id,
                "title": task.title,
                "message": str(exc),
            })

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_status_failed(emitter, task, exc),
        )

        self._enqueue_event(
            event_queue=event_queue,
            event_lock=event_lock,
            build_event=lambda: self.event_builder.task_failed(emitter, task, exc)
        )

    # 入队
    def _enqueue_event(
            self,
            event_queue: Queue[dict[str, Any]],
            event_lock: Lock,
            build_event: Callable[[], dict[str, Any]],
    ):
        """线程安全地创建事件并放进队列。
        EventEmitter 会递增 seq。
        多个 worker 并发时，必须用 event_lock 包住 emit，
        否则可能出现事件序号竞争。
        """
        with event_lock:
            event = build_event()
        event_queue.put(event)

    def apply_search_result(
            self,
            search_result: SearchResult,
            task: TodoItem
    ):
        """把 SearchService 的返回结果写回 TodoItem。
        SearchResult.search_results_text：
        - 给 SummaryService 使用的长研究上下文。

        task.source_summary：
        - 给前端“最新来源”展示的短来源摘要。
        """
        results = search_result.results
        if not isinstance(results, dict):
            task.search_results = []
            task.source_summary = "搜索结果格式异常，未能解析来源列表"
            task.notices = ["搜索结果格式异常，未能解析来源列表"]
            return

        task.search_results = results.get("results") or []
        # 短来源摘要：给前端展示。
        task.source_summary = self.search_service.build_sources_summary(results)
        task.notices = results.get("notices") or []

    @staticmethod
    def _search_backend_from_result(search_result: SearchResult) -> str:
        """Best-effort 获取搜索最终使用的 backend，用于日志排查。"""
        results = search_result.results
        if isinstance(results, dict):
            return str(results.get("backend") or "unknown")
        return "unknown"
