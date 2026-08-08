import logging
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.core.config import Config
from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState, SearchResult, TodoItem
from backend.workflow.research_event_builder import ResearchEventBuilder
from backend.workflow.result_builder import ResultBuilder
from backend.workflow.task_executor import TaskExecutor


class NoopStageLogger:
    """测试用 stage logger，吞掉所有日志方法。"""

    def __getattr__(self, name: str) -> Callable[..., None]:
        def noop(*args: Any, **kwargs: Any) -> None:
            return None

        return noop


class FakeSearchService:
    """返回固定来源，避免并发事件流测试依赖真实搜索。"""

    def __init__(self, failing_task_id: int | None = None):
        self.failing_task_id = failing_task_id

    def run_search(self, task: TodoItem, **kwargs: Any) -> SearchResult:
        if task.id == self.failing_task_id:
            raise RuntimeError(f"search failed for task {task.id}")

        results = {
            "backend": kwargs.get("backend", "duckduckgo"),
            "notices": [f"fake search done task={task.id}"],
            "results": [
                {
                    "source_id": f"T{task.id}-S1",
                    "title": f"source for task {task.id}",
                    "url": f"https://example.com/task-{task.id}",
                    "content": f"content for task {task.id}",
                    "source_type": "official_doc",
                    "score": 90,
                }
            ],
        }
        return SearchResult(
            task_id=task.id,
            title=task.title,
            intent=task.intent,
            query=task.query,
            results=results,
            search_results_text=f"context for task {task.id}",
        )

    @staticmethod
    def build_sources_summary(search_result: dict[str, Any]) -> str:
        results = search_result.get("results") or []
        return "\n".join(item.get("title", "") for item in results)


class FakeSummaryService:
    """流式返回两个 chunk，用来验证 summary_delta 事件。"""

    def stream_summary(self, search_result: SearchResult):
        chunks = [
            f"summary-{search_result.task_id}-part-1",
            f"summary-{search_result.task_id}-part-2",
        ]
        emitted: list[str] = []

        def stream():
            for chunk in chunks:
                time.sleep(0.001)
                emitted.append(chunk)
                yield chunk

        def get_summary() -> str:
            return "".join(emitted)

        return stream(), get_summary


class TaskExecutorEventStreamTest(unittest.TestCase):
    def build_executor(
            self,
            state: ResearchState,
            search_service: FakeSearchService,
    ) -> tuple[TaskExecutor, EventEmitter]:
        config = Config(
            task_max_workers=3,
            notes_enabled=False,
            enable_multi_query_search=False,
            enable_search_quality_retry=False,
        )
        emitter = EventEmitter(run_id="task-executor-test")
        event_builder = ResearchEventBuilder(ResultBuilder())
        event_builder.register(emitter, state)

        executor = TaskExecutor(
            config=config,
            logger=logging.getLogger(__name__),
            search_service=search_service,  # type: ignore[arg-type]
            note_service=None,
            summary_service=FakeSummaryService(),  # type: ignore[arg-type]
        )
        executor.bind(event_builder, NoopStageLogger())  # type: ignore[arg-type]
        return executor, emitter

    @staticmethod
    def build_state() -> ResearchState:
        return ResearchState(
            topic="并发事件流测试",
            backend="duckduckgo",
            tasks=[
                TodoItem(id=1, title="任务 1", intent="意图 1", query="query 1"),
                TodoItem(id=2, title="任务 2", intent="意图 2", query="query 2"),
                TodoItem(id=3, title="任务 3", intent="意图 3", query="query 3"),
            ],
        )

    @staticmethod
    def find_event_index(
            events: list[dict[str, Any]],
            predicate: Callable[[dict[str, Any]], bool],
    ) -> int:
        for index, event in enumerate(events):
            if predicate(event):
                return index
        raise AssertionError("expected event not found")

    def assert_task_event_order(
            self,
            events: list[dict[str, Any]],
            task_id: int,
    ) -> None:
        task_events = [event for event in events if event.get("task_id") == task_id]
        event_types = [event["type"] for event in task_events]

        self.assertIn("task_started", event_types)
        self.assertIn("task_sources_done", event_types)
        self.assertIn("task_summary_started", event_types)
        self.assertIn("llm_delta", event_types)
        self.assertIn("task_summary_done", event_types)
        self.assertIn("task_done", event_types)

        in_progress_status = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_status"
            and event["status"] == "in_progress",
        )
        started = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_started",
        )
        sources_done = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_sources_done",
        )
        summary_started = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_summary_started",
        )
        first_delta = self.find_event_index(
            task_events,
            lambda event: event["type"] == "llm_delta",
        )
        completed_status = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_status"
            and event["status"] == "completed",
        )
        summary_done = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_summary_done",
        )
        task_done = self.find_event_index(
            task_events,
            lambda event: event["type"] == "task_done",
        )

        self.assertLess(in_progress_status, started)
        self.assertLess(started, sources_done)
        self.assertLess(sources_done, summary_started)
        self.assertLess(summary_started, first_delta)
        self.assertLess(first_delta, completed_status)
        self.assertLess(completed_status, summary_done)
        self.assertLess(summary_done, task_done)

        deltas = [event for event in task_events if event["type"] == "llm_delta"]
        self.assertEqual(2, len(deltas))

    def test_parallel_tasks_keep_per_task_event_order(self):
        state = self.build_state()
        executor, emitter = self.build_executor(state, FakeSearchService())

        events = list(executor.execute_tasks_stream(state, emitter))

        self.assertTrue(all(task.status == "completed" for task in state.tasks))
        self.assertEqual([], state.errors)
        self.assertFalse(any(event.get("type") == "__task_done__" for event in events))

        seqs = [event["seq"] for event in events]
        self.assertEqual(len(seqs), len(set(seqs)))

        for task_id in [1, 2, 3]:
            self.assert_task_event_order(events, task_id)

    def test_failed_task_does_not_block_other_tasks(self):
        state = self.build_state()
        executor, emitter = self.build_executor(
            state,
            FakeSearchService(failing_task_id=2),
        )

        events = list(executor.execute_tasks_stream(state, emitter))

        task_status = {task.id: task.status for task in state.tasks}
        self.assertEqual("completed", task_status[1])
        self.assertEqual("failed", task_status[2])
        self.assertEqual("completed", task_status[3])

        self.assertEqual(1, len(state.errors))
        self.assertEqual(2, state.errors[0]["task_id"])
        self.assertIn("search failed for task 2", state.errors[0]["message"])

        event_types = [event["type"] for event in events]
        self.assertIn("task_failed", event_types)
        self.assertFalse(any(event.get("type") == "__task_done__" for event in events))

        failed_task_events = [
            event for event in events if event.get("task_id") == 2
        ]
        self.assertTrue(
            any(
                event["type"] == "task_status" and event["status"] == "failed"
                for event in failed_task_events
            )
        )
        self.assertTrue(
            any(event["type"] == "task_failed" for event in failed_task_events)
        )

        self.assert_task_event_order(events, 1)
        self.assert_task_event_order(events, 3)


if __name__ == "__main__":
    unittest.main()
