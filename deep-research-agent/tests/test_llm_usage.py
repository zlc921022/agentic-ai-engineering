import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.core.config import Config
from backend.llm.client import QwenChatClient
from backend.llm.usage import (
    UsageCollector,
    usage_run_scope,
    usage_stage_scope,
    usage_task_scope,
)


class LlmUsageTest(unittest.TestCase):
    def test_complete_keeps_text_return_and_records_usage(self):
        """读取 usage 后，complete() 仍只返回原来的字符串。"""

        class FakeCompletions:
            def create(self, **_kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="planner result")
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=120,
                        completion_tokens=30,
                        total_tokens=150,
                    ),
                )

        client = self._client(FakeCompletions())
        with usage_run_scope("run-1"), usage_stage_scope("planner"):
            result = client.complete("plan")

        summary = client.usage_summary("run-1")

        self.assertEqual(result, "planner result")
        self.assertTrue(summary["available"])
        self.assertEqual(summary["total_tokens"], 150)
        self.assertEqual(summary["by_stage"]["planner"]["request_count"], 1)

    def test_stream_reads_usage_only_tail_chunk_without_changing_content(self):
        """流式收尾 chunk 没有 choices 时，也应读取 usage 且不产生正文。"""
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return iter([
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="研究")
                            )
                        ],
                        usage=None,
                    ),
                    SimpleNamespace(
                        choices=[],
                        usage=SimpleNamespace(
                            prompt_tokens=200,
                            completion_tokens=50,
                            total_tokens=250,
                        ),
                    ),
                ])

        client = self._client(FakeCompletions())
        with usage_run_scope("run-stream"), usage_stage_scope("reporter"):
            chunks = list(client.stream("report"))

        summary = client.usage_summary("run-stream")

        self.assertEqual(chunks, ["研究"])
        self.assertEqual(
            captured["stream_options"],
            {"include_usage": True},
        )
        self.assertEqual(summary["total_tokens"], 250)
        self.assertEqual(summary["by_stage"]["reporter"]["completion_tokens"], 50)

    def test_collector_isolates_parallel_runs_and_tasks(self):
        """并发 Summary 的 run_id/task_id 不能互相覆盖。"""
        collector = UsageCollector()

        def record(run_id: str, task_id: int) -> None:
            with (
                usage_run_scope(run_id),
                usage_stage_scope(f"summary_task_{task_id}"),
                usage_task_scope(task_id),
            ):
                collector.record(
                    model="fake-model",
                    usage={
                        "prompt_tokens": 10 * task_id,
                        "completion_tokens": task_id,
                        "total_tokens": 11 * task_id,
                    },
                )

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(record, "run-a", 1),
                executor.submit(record, "run-a", 2),
                executor.submit(record, "run-b", 3),
                executor.submit(record, "run-b", 4),
            ]
            for future in futures:
                future.result()

        run_a = collector.summarize("run-a")
        run_b = collector.summarize("run-b")

        self.assertEqual(run_a["total_tokens"], 33)
        self.assertEqual(run_b["total_tokens"], 77)
        self.assertEqual(
            sorted(record["task_id"] for record in collector.records("run-a")),
            [1, 2],
        )

    def test_cost_is_only_calculated_when_prices_are_configured(self):
        collector = UsageCollector()
        with usage_run_scope("run-cost"), usage_stage_scope("reporter"):
            collector.record(
                model="fake-model",
                usage={
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 500_000,
                    "total_tokens": 1_500_000,
                },
            )

        without_price = collector.summarize("run-cost")
        with_price = collector.summarize(
            "run-cost",
            input_price_per_million=2.0,
            output_price_per_million=6.0,
        )

        self.assertFalse(without_price["cost"]["calculated"])
        self.assertIsNone(without_price["cost"]["estimated"])
        self.assertEqual(with_price["cost"]["estimated"], 5.0)

    def test_usage_failure_does_not_change_model_result_or_cleanup(self):
        """采集与清理同时失败时，模型正文仍应正常返回。"""

        class FakeCompletions:
            def create(self, **_kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="正常业务结果")
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                    ),
                )

        class FailingCollector:
            def record(self, **_kwargs):
                raise RuntimeError("usage record failed")

            def clear(self, _run_id):
                raise RuntimeError("usage clear failed")

        client = self._client(FakeCompletions())
        client.usage_collector = FailingCollector()

        with usage_run_scope("run-fail-open"):
            result = client.complete("test")
        # clear_usage 也必须吞掉异常，不能污染已经完成的 SSE。
        client.clear_usage("run-fail-open")

        self.assertEqual(result, "正常业务结果")

    @staticmethod
    def _client(completions) -> QwenChatClient:
        client = QwenChatClient.__new__(QwenChatClient)
        client.config = Config.from_env(
            api_key="fake-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            chat_model="fake-model",
        )
        client.usage_collector = UsageCollector()
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        return client


if __name__ == "__main__":
    unittest.main()
