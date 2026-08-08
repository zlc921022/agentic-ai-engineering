import json
import os
import logging
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.workflow.agent import DeepResearchAgent
from backend.core.config import Config
from backend.domain.models import SearchResult, TodoItem
from backend.notes.note_service import NoteService
from backend.workflow.research_event_builder import ResearchEventBuilder
from backend.workflow.research_stage_logger import ResearchStageLogger
from backend.workflow.result_builder import ResultBuilder
from backend.services.search_service import SearchService
from backend.services.report_reflection_service import ReflectionDecision
from backend.workflow.task_executor import TaskExecutor


class EventNoteFlowTest(unittest.TestCase):
    def test_config_reads_environment_variables(self):
        """Config.from_env 应读取运行参数，并正确解析 bool/int/path。"""
        with TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_BASE_URL": "https://example.com/v1",
                    "CHAT_MODEL": "test-model",
                    "DEFAULT_SEARCH_BACKEND": "tavily",
                    "SEARCH_MAX_RESULTS": "7",
                    "SEARCH_TIMEOUT_SECONDS": "12",
                    "ENABLE_MULTI_QUERY_SEARCH": "false",
                    "SEARCH_QUERY_VARIANT_COUNT": "2",
                    "FETCH_FULL_PAGE": "false",
                    "MAX_TOKENS_PER_SOURCE": "900",
                    "TASK_MAX_WORKERS": "2",
                    "WORKFLOW_TIMEOUT_SECONDS": "120",
                    "SSE_HEARTBEAT_SECONDS": "3",
                    "LLM_STREAM_IDLE_TIMEOUT_SECONDS": "20",
                    "LLM_INPUT_PRICE_PER_MILLION": "2.5",
                    "LLM_OUTPUT_PRICE_PER_MILLION": "8",
                    "LLM_PRICE_CURRENCY": "cny",
                    "NOTES_ENABLED": "true",
                    "NOTES_WORKSPACE": tmp,
                },
                clear=True,
            ):
                config = Config.from_env()

        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.chat_model, "test-model")
        self.assertEqual(config.default_search_backend, "tavily")
        self.assertEqual(config.search_max_results, 7)
        self.assertEqual(config.search_timeout_seconds, 12)
        self.assertFalse(config.enable_multi_query_search)
        self.assertEqual(config.search_query_variant_count, 2)
        self.assertFalse(config.fetch_full_page)
        self.assertEqual(config.max_tokens_per_source, 900)
        self.assertEqual(config.task_max_workers, 2)
        self.assertEqual(config.workflow_timeout_seconds, 120)
        self.assertEqual(config.sse_heartbeat_seconds, 3)
        self.assertEqual(config.llm_stream_idle_timeout_seconds, 20)
        self.assertEqual(config.llm_input_price_per_million, 2.5)
        self.assertEqual(config.llm_output_price_per_million, 8)
        self.assertEqual(config.llm_price_currency, "CNY")
        self.assertTrue(config.notes_enabled)
        self.assertEqual(config.notes_workspace, Path(tmp))

    def test_config_allows_explicit_overrides(self):
        """显式 override 应高于环境变量，便于测试和请求级配置扩展。"""
        with patch.dict(
            os.environ,
            {
                "CHAT_MODEL": "env-model",
                "TASK_MAX_WORKERS": "4",
            },
            clear=True,
        ):
            config = Config.from_env(
                chat_model="override-model",
                task_max_workers=1,
            )

        self.assertEqual(config.chat_model, "override-model")
        self.assertEqual(config.task_max_workers, 1)

    def test_note_service_writes_task_note_sections(self):
        """NoteService 应该把任务概览、来源和总结写进同一个任务笔记。"""
        with TemporaryDirectory() as tmp:
            service = NoteService(workspace=tmp)
            task = TodoItem(
                id=1,
                title="数据质量",
                intent="分析数据质量问题",
                query="RAG data quality hallucination",
            )
            run_id = "run-note-service-test"
            service.start_run(run_id, "企业知识库 RAG 幻觉治理")

            service.create_task_note(
                task,
                run_id=run_id,
            )

            task.source_summary = "来源ID: T1-S1\n标题: 测试来源"
            task.search_results = [{"source_id": "T1-S1"}]
            service.update_note_sources(task, run_id=run_id)

            task.summary = "这是任务总结"
            task.status = "completed"
            service.update_note_summary(task, run_id=run_id)

            self.assertIsNotNone(task.note_id)
            self.assertIsNotNone(task.note_path)

            note_text = Path(task.note_path).read_text(encoding="utf-8")
            self.assertIn("## 任务概览", note_text)
            self.assertIn("## 最新来源", note_text)
            self.assertIn("来源ID: T1-S1", note_text)
            self.assertIn("## 任务总结", note_text)
            self.assertIn("这是任务总结", note_text)

            index = service.index.read()
            self.assertEqual(index["latest_run_id"], run_id)
            self.assertEqual(len(index["runs"]), 1)
            task_note = index["runs"][0]["task_notes"][0]
            self.assertEqual(task_note["status"], "completed")
            self.assertEqual(task_note["source_count"], 1)
            self.assertEqual(task_note["summary_chars"], len(task.summary))

    def test_run_stream_emits_note_events_and_final_result(self):
        """run_stream 在 fake 服务下应该产出稳定事件，并把 Note 元数据写回结果。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)

            events = list(
                agent.run_stream(
                    topic="企业知识库 RAG 幻觉治理",
                    backend="duckduckgo",
                )
            )
            event_types = [event["type"] for event in events]

            # 全局主流程事件：这些事件名会被前端工作台直接消费。
            self.assertIn("workflow_started", event_types)
            self.assertIn("planner_done", event_types)
            self.assertIn("task_sources_done", event_types)
            self.assertIn("task_summary_done", event_types)
            self.assertIn("report_done", event_types)
            self.assertIn("evaluator_done", event_types)
            self.assertEqual("workflow_done", event_types[-1])

            source_events = [
                event
                for event in events
                if event["type"] == "task_sources_done"
            ]
            self.assertEqual(len(source_events), 2)
            self.assertTrue(
                all(
                    event["payload"]["search_observation"]["retry_triggered"]
                    is False
                    for event in source_events
                )
            )

            # EventEmitter 的 seq 应该稳定递增，便于前端排序和排查。
            seqs = [event["seq"] for event in events]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(seqs, list(range(1, len(events) + 1)))

            note_events = [event for event in events if event["type"] == "note_event"]
            labels = [event["payload"]["label"] for event in note_events]

            self.assertEqual(labels.count("planner 创建任务笔记"), 2)
            self.assertEqual(labels.count("search 更新来源"), 2)
            self.assertEqual(labels.count("summary 更新总结"), 2)
            self.assertEqual(labels.count("report 创建报告笔记"), 1)

            for event in note_events:
                payload = event["payload"]
                self.assertTrue(payload["note_id"])
                self.assertTrue(payload["note_path"])
                self.assertTrue(Path(payload["note_path"]).exists())
                self.assertIn("content_preview", payload)

            # 每个任务自己的 note 应该至少包含：规划概览、来源、总结。
            task_note_paths = {
                event["payload"]["note_path"]
                for event in note_events
                if event["task_id"] is not None
            }
            self.assertEqual(len(task_note_paths), 2)

            for note_path in task_note_paths:
                note_text = Path(note_path).read_text(encoding="utf-8")
                self.assertIn("## 任务概览", note_text)
                self.assertIn("## 最新来源", note_text)
                self.assertIn("## 任务总结", note_text)

            workflow_done = events[-1]
            result = workflow_done["payload"]["result"]

            self.assertEqual(result["topic"], "企业知识库 RAG 幻觉治理")
            self.assertEqual(result["backend"], "duckduckgo")
            self.assertEqual(result["report"], "# 最终报告\n研究完成")
            self.assertEqual(result["evaluator"]["overall_score"], 95)
            self.assertTrue(result["llm_usage"]["available"])
            self.assertEqual(result["llm_usage"]["total_tokens"], 300)
            self.assertEqual(len(result["tasks"]), 2)
            self.assertEqual(len(result["traces"]), 2)

            for task in result["tasks"]:
                self.assertEqual(task["status"], "completed")
                self.assertTrue(task["summary"])
                self.assertTrue(task["note_id"])
                self.assertTrue(task["note_path"])
                # source_summary 是给前端展示的短来源摘要，不应该塞入长正文。
                self.assertIn("来源类型", task["source_summary"])
                self.assertNotIn("正文内容：", task["source_summary"])

            index = json.loads(
                (Path(tmp) / "index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(index["latest_run_id"], workflow_done["run_id"])
            self.assertEqual(len(index["runs"]), 1)
            indexed_run = index["runs"][0]
            self.assertEqual(indexed_run["status"], "completed")
            self.assertEqual(len(indexed_run["task_notes"]), 2)
            self.assertEqual(indexed_run["report_note"]["evaluator_score"], 95)
            self.assertEqual(indexed_run["report_note"]["warning_count"], 0)

    def test_usage_cleanup_failure_does_not_break_workflow_done(self):
        """自定义 Client 清理 Usage 失败时，业务事件仍应正常结束。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)

            def fail_cleanup(_run_id):
                raise RuntimeError("cleanup failed")

            agent.llm.clear_usage = fail_cleanup
            events = list(
                agent.run_stream(
                    topic="可观测性异常不能影响业务",
                    backend="duckduckgo",
                )
            )

            self.assertEqual(events[-1]["type"], "workflow_done")
            self.assertEqual(
                events[-1]["payload"]["result"]["report"],
                "# 最终报告\n研究完成",
            )

    def test_run_stream_works_when_notes_are_disabled(self):
        """关闭 Note 后不应产生 note_event，也不能影响报告主流程。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)
            agent.config = Config.from_env(
                notes_enabled=False,
                task_max_workers=2,
                search_max_results=5,
                fetch_full_page=False,
                max_tokens_per_source=1000,
            )
            agent.note_service = None
            self._refresh_fake_agent_helpers(agent)

            events = list(agent.run_stream("关闭 Note 测试", backend="duckduckgo"))
            event_types = [event["type"] for event in events]

            self.assertNotIn("note_event", event_types)
            self.assertIn("report_done", event_types)
            self.assertEqual("workflow_done", event_types[-1])

    def test_run_stream_skips_report_when_all_tasks_fail(self):
        """所有任务失败时，不应让 reporter 生成看似正常的最终报告。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)

            def failing_search(task: TodoItem, backend: str = "hybrid", **kwargs):
                raise RuntimeError(f"搜索失败 task={task.id}")

            agent.search_service = SimpleNamespace(
                run_search=failing_search,
                build_sources_summary=SearchService.build_sources_summary,
            )
            self._refresh_fake_agent_helpers(agent)

            events = list(agent.run_stream("全部失败测试", backend="duckduckgo"))
            event_types = [event["type"] for event in events]

            self.assertIn("task_failed", event_types)
            self.assertIn("report_failed", event_types)
            self.assertIn("workflow_failed", event_types)
            self.assertNotIn("report_done", event_types)
            self.assertNotIn("workflow_done", event_types)
            self.assertEqual("workflow_failed", events[-1]["type"])

            result = events[-1]["payload"]["result"]
            self.assertIn("# 研究流程未完成", result["report"])
            self.assertTrue(all(task["status"] == "failed" for task in result["tasks"]))
            self.assertTrue(all(trace["stage"] == "failed" for trace in result["traces"]))

    def test_run_stream_reports_completed_tasks_with_failure_warning(self):
        """部分任务失败时，reporter 只接收成功任务，并在报告中追加失败说明。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)
            reported_task_ids: list[int] = []

            def partially_failing_search(
                    task: TodoItem,
                    backend: str = "hybrid",
                    **kwargs,
            ) -> SearchResult:
                if task.id == 2:
                    raise RuntimeError("检索召回失败")
                return self._fake_search(task, backend=backend, **kwargs)

            def recording_report(topic: str, tasks: list[TodoItem]):
                reported_task_ids.extend(task.id for task in tasks)
                return self._fake_report(topic, tasks)

            agent.search_service = SimpleNamespace(
                run_search=partially_failing_search,
                build_sources_summary=SearchService.build_sources_summary,
            )
            agent.reporter = SimpleNamespace(stream_report=recording_report)
            self._refresh_fake_agent_helpers(agent)

            events = list(agent.run_stream("部分失败测试", backend="duckduckgo"))
            event_types = [event["type"] for event in events]

            self.assertIn("task_failed", event_types)
            self.assertIn("report_done", event_types)
            self.assertEqual("workflow_done", event_types[-1])
            self.assertEqual([1], reported_task_ids)

            result = events[-1]["payload"]["result"]
            task_status = {
                task["id"]: task["status"]
                for task in result["tasks"]
            }
            trace_stage = {
                trace["task_index"]: trace["stage"]
                for trace in result["traces"]
            }

            self.assertEqual("completed", task_status[1])
            self.assertEqual("failed", task_status[2])
            self.assertEqual("completed", trace_stage[1])
            self.assertEqual("failed", trace_stage[2])
            self.assertIn("## 执行限制", result["report"])
            self.assertIn("任务 02", result["report"])
            self.assertIn("检索召回失败", result["report"])

    def test_summary_stream_timeout_becomes_task_and_workflow_failed(self):
        """任务总结 LLM 流式超时时，应转成任务失败事件并最终终止 workflow。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)

            def timeout_summary(search_result: SearchResult):
                def stream():
                    raise TimeoutError("LLM 流式响应超时")
                    yield ""

                return stream(), lambda: ""

            agent.summary_service = SimpleNamespace(stream_summary=timeout_summary)
            self._refresh_fake_agent_helpers(agent)

            events = list(agent.run_stream("summary 超时测试", backend="duckduckgo"))
            event_types = [event["type"] for event in events]

            self.assertIn("task_failed", event_types)
            self.assertIn("workflow_failed", event_types)
            self.assertNotIn("workflow_done", event_types)
            self.assertEqual("workflow_failed", events[-1]["type"])

            failed_status_events = [
                event
                for event in events
                if event["type"] == "task_status" and event["status"] == "failed"
            ]
            self.assertEqual(len(failed_status_events), 2)
            for event in failed_status_events:
                self.assertEqual(event["error"]["message"], "LLM 流式响应超时")
                self.assertEqual(event["error"]["type"], "TimeoutError")

            result = events[-1]["payload"]["result"]
            self.assertTrue(all(task["status"] == "failed" for task in result["tasks"]))
            self.assertIn("LLM 流式响应超时", json.dumps(result, ensure_ascii=False))

    def test_report_stream_timeout_becomes_report_and_workflow_failed(self):
        """最终报告 LLM 流式超时时，应转成 report_failed 和 workflow_failed。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)

            def timeout_report(topic: str, tasks: list[TodoItem]):
                def stream():
                    raise TimeoutError("LLM 流式响应超时")
                    yield ""

                return stream(), lambda: ""

            agent.reporter = SimpleNamespace(stream_report=timeout_report)
            self._refresh_fake_agent_helpers(agent)

            events = list(agent.run_stream("report 超时测试", backend="duckduckgo"))
            event_types = [event["type"] for event in events]

            self.assertIn("task_summary_done", event_types)
            self.assertIn("report_failed", event_types)
            self.assertIn("workflow_failed", event_types)
            self.assertNotIn("workflow_done", event_types)
            self.assertEqual("workflow_failed", events[-1]["type"])

            report_failed = next(
                event for event in events if event["type"] == "report_failed"
            )
            self.assertEqual(report_failed["error"]["message"], "LLM 流式响应超时")

            result = events[-1]["payload"]["result"]
            self.assertIn("# 研究流程未完成", result["report"])
            self.assertIn("LLM 流式响应超时", json.dumps(result, ensure_ascii=False))

    def test_agent_passes_configured_search_parameters(self):
        """Agent 应把搜索配置传给 SearchService，而不是继续使用硬编码。"""
        with TemporaryDirectory() as tmp:
            agent = self._build_fake_agent(tmp)
            agent.config = Config.from_env(
                task_max_workers=1,
                search_max_results=3,
                enable_multi_query_search=False,
                search_query_variant_count=1,
                fetch_full_page=True,
                max_tokens_per_source=777,
            )
            calls: list[dict[str, object]] = []

            def recording_search(
                    task: TodoItem,
                    backend: str = "hybrid",
                    **kwargs,
            ) -> SearchResult:
                calls.append({
                    "backend": backend,
                    **kwargs,
                })
                return self._fake_search(task, backend=backend, **kwargs)

            agent.search_service = SimpleNamespace(
                run_search=recording_search,
                build_sources_summary=SearchService.build_sources_summary,
            )
            self._refresh_fake_agent_helpers(agent)

            list(agent.run_stream("搜索配置测试", backend="tavily"))

            self.assertEqual(len(calls), 2)
            for call in calls:
                self.assertEqual(call["backend"], "tavily")
                self.assertEqual(call["max_results"], 3)
                self.assertFalse(call["enable_multi_query_search"])
                self.assertEqual(call["query_variant_count"], 1)
                self.assertTrue(call["fetch_full_page"])
                self.assertEqual(call["max_tokens_per_source"], 777)

    def test_search_context_separates_ui_summary_and_model_context(self):
        """搜索结果应拆成：短来源摘要给 UI，长研究上下文给 summarizer。"""
        search_result = {
            "backend": "duckduckgo",
            "notices": ["测试提示"],
            "results": [
                {
                    "source_id": "T1-S1",
                    "title": "RAG 数据质量来源",
                    "url": "https://example.com/rag",
                    "source_type": "academic",
                    "score": 90,
                    "reasons": ["test"],
                    "content": "这是一段用于总结模型的较长正文内容。" * 20,
                }
            ],
        }

        sources_summary = SearchService.build_sources_summary(search_result)
        research_context = SearchService.build_research_context(
            search_result,
            max_tokens_per_source=20,
        )

        self.assertIn("[T1-S1]", sources_summary)
        self.assertIn("来源类型", sources_summary)
        self.assertNotIn("正文内容：", sources_summary)

        self.assertIn("## 来源 [T1-S1]", research_context)
        self.assertIn("正文内容：", research_context)
        self.assertIn("[truncated]", research_context)

    def _build_fake_agent(self, note_workspace: str) -> DeepResearchAgent:
        """构造不依赖真实 LLM / 搜索网络的 DeepResearchAgent。

        这里不用 DeepResearchAgent(...) 正常初始化，是为了避开 SearchTool、
        QwenChatClient、ToolRegistry 等真实依赖。测试只关心 orchestrator
        事件和 Note 写入，所以手动注入最小 fake service 更稳定。
        """
        agent = DeepResearchAgent.__new__(DeepResearchAgent)
        agent.config = Config.from_env(
            task_max_workers=2,
            search_max_results=5,
            fetch_full_page=False,
            max_tokens_per_source=1000,
        )
        agent.logger = logging.getLogger("test_backend_events_note")
        agent.llm = SimpleNamespace(
            usage_summary=lambda _run_id: {
                "available": True,
                "request_count": 3,
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
                "by_stage": {},
                "cost": {
                    "calculated": False,
                    "estimated": None,
                    "currency": "CNY",
                },
            },
            clear_usage=lambda _run_id: None,
        )
        agent.note_service = NoteService(workspace=note_workspace)

        agent.planer = SimpleNamespace(run_plan=self._fake_plan)
        agent.search_service = SimpleNamespace(
            run_search=self._fake_search,
            build_sources_summary=SearchService.build_sources_summary,
        )
        agent.summary_service = SimpleNamespace(stream_summary=self._fake_summary)
        agent.reporter = SimpleNamespace(stream_report=self._fake_report)
        agent.evaluate = lambda report_result, errors, topic="", tasks=None: {
            "overall_score": 95,
            "warnings": [],
            "judge": {
                "enabled": False,
                "status": "disabled",
            },
        }
        agent.report_reflection_service = SimpleNamespace(
            decide=lambda evaluator: ReflectionDecision(
                should_reflect=False,
                triggers=[],
                reasons=["测试默认跳过反思"],
            ),
            revise_report=lambda *args, **kwargs: "",
        )
        self._refresh_fake_agent_helpers(agent)

        return agent

    @staticmethod
    def _refresh_fake_agent_helpers(agent: DeepResearchAgent):
        """同步 __new__ 构造出的 fake agent 所需的拆分协作对象。"""
        agent.result_builder = ResultBuilder()
        agent.event_builder = ResearchEventBuilder(agent.result_builder)
        agent.stage_logger = ResearchStageLogger(agent.logger)
        agent.task_executor = TaskExecutor(
            config=agent.config,
            logger=agent.logger,
            search_service=agent.search_service,
            summary_service=agent.summary_service,
            note_service=agent.note_service,
        )

    @staticmethod
    def _fake_plan(state):
        return [
            TodoItem(
                id=1,
                title="数据质量",
                intent="分析企业知识库数据质量问题",
                query="RAG data quality hallucination",
            ),
            TodoItem(
                id=2,
                title="检索召回",
                intent="分析检索召回和重排序策略",
                query="RAG retrieval recall rerank",
            ),
        ]

    @staticmethod
    def _fake_search(task: TodoItem, backend: str = "hybrid", **kwargs) -> SearchResult:
        return SearchResult(
            task_id=task.id,
            title=task.title,
            intent=task.intent,
            query=task.query,
            results={
                "backend": backend,
                "notices": [],
                "results": [
                    {
                        "source_id": f"T{task.id}-S1",
                        "title": f"{task.title} 来源",
                        "url": f"https://example.com/{task.id}",
                        "source_type": "academic",
                        "score": 90,
                        "reasons": ["test"],
                        "content": f"{task.title} 的完整搜索正文，用于测试 summarizer 长上下文输入。" * 20,
                    }
                ],
            },
            search_results_text=SearchService.build_research_context(
                {
                    "backend": backend,
                    "notices": [],
                    "results": [
                        {
                            "source_id": f"T{task.id}-S1",
                            "title": f"{task.title} 来源",
                            "url": f"https://example.com/{task.id}",
                            "source_type": "academic",
                            "score": 90,
                            "reasons": ["test"],
                            "content": f"{task.title} 的完整搜索正文，用于测试 summarizer 长上下文输入。" * 20,
                        }
                    ],
                },
                max_tokens_per_source=1500,
            ),
            observation={
                "retry_triggered": False,
                "function_calling_attempted": False,
                "tool_call_count": 0,
                "fallback_used": False,
            },
        )

    @staticmethod
    def _fake_summary(search_result: SearchResult):
        assert "正文内容：" in search_result.search_results_text
        chunks = [
            "### 任务总结\n",
            f"{search_result.title} 总结内容",
        ]
        received: list[str] = []

        def stream():
            for chunk in chunks:
                received.append(chunk)
                yield chunk

        return stream(), lambda: "".join(received)

    @staticmethod
    def _fake_report(topic: str, tasks: list[TodoItem]):
        chunks = ["# 最终报告\n", "研究完成"]
        received: list[str] = []

        def stream():
            for chunk in chunks:
                received.append(chunk)
                yield chunk

        return stream(), lambda: "".join(received)


if __name__ == "__main__":
    unittest.main()
