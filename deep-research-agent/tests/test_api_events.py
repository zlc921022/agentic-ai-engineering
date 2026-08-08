import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import backend.api.app as api_main


EVENT_KEYS = {
    "run_id",
    "seq",
    "type",
    "stage",
    "status",
    "message",
    "step",
    "task_id",
    "payload",
    "error",
    "timestamp",
}


class FakeConfig:
    default_search_backend = "duckduckgo"
    chat_model = "fake-model"
    base_url = "https://example.test/v1"
    fetch_full_page = False
    max_tokens_per_source = 100
    search_max_results = 3
    search_timeout_seconds = 30
    llm_stream_idle_timeout_seconds = 90
    task_max_workers = 1
    workflow_timeout_seconds = 1
    sse_heartbeat_seconds = 1
    notes_enabled = False

    def __init__(
            self,
            warnings: list[str] | None = None,
            workflow_timeout_seconds: float = 1,
            sse_heartbeat_seconds: float = 1,
    ) -> None:
        self._warnings = warnings or []
        self.workflow_timeout_seconds = workflow_timeout_seconds
        self.sse_heartbeat_seconds = sse_heartbeat_seconds

    def ensure_dirs(self) -> None:
        return None

    def validation_warnings(self, backend: str | None = None) -> list[str]:
        return list(self._warnings)


class FakeAgent:
    def __init__(self, *args, events=None, error: Exception | None = None, **kwargs) -> None:
        self.events = events or []
        self.error = error

    def run_stream(self, topic: str, backend: str | None = None):
        if self.error:
            raise self.error

        yield from self.events


def parse_sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.strip().split("\n\n"):
        data_lines = [
            line.removeprefix("data: ")
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


class ApiResearchEventsTest(unittest.TestCase):
    def test_config_warning_uses_research_event_contract(self):
        workflow_event = {
            "run_id": "run-1",
            "seq": 1,
            "type": "workflow_done",
            "stage": "workflow",
            "status": "completed",
            "message": "done",
            "step": 6,
            "task_id": None,
            "payload": {"result": {}},
            "error": None,
            "timestamp": 1.0,
        }

        with patch.object(
            api_main.Config,
            "from_env",
            return_value=FakeConfig(warnings=["缺少 OPENAI_API_KEY"]),
        ), patch.object(
            api_main,
            "QwenChatClient",
            return_value=object(),
        ), patch.object(
            api_main,
            "ToolRegistry",
            return_value=object(),
        ), patch.object(
            api_main,
            "DeepResearchAgent",
            return_value=FakeAgent(events=[workflow_event]),
        ):
            client = TestClient(api_main.create_app())
            response = client.get(
                "/api/research/stream",
                params={"topic": "RAG 测试", "backend": "duckduckgo"},
            )

        self.assertEqual(response.status_code, 200)
        events = parse_sse_events(response.text)

        warning = events[0]
        self.assertEqual(set(warning.keys()), EVENT_KEYS)
        self.assertEqual(warning["run_id"], "")
        self.assertEqual(warning["seq"], 1)
        self.assertEqual(warning["type"], "config_warning")
        self.assertEqual(warning["stage"], "config")
        self.assertEqual(warning["status"], "info")
        self.assertEqual(warning["message"], "配置存在告警")
        self.assertEqual(warning["step"], 0)
        self.assertIsNone(warning["task_id"])
        self.assertEqual(warning["payload"], {"warnings": ["缺少 OPENAI_API_KEY"]})
        self.assertIsNone(warning["error"])
        self.assertIsInstance(warning["timestamp"], float)

        self.assertEqual(events[1], workflow_event)

    def test_api_error_uses_research_event_contract(self):
        with patch.object(
            api_main.Config,
            "from_env",
            return_value=FakeConfig(),
        ), patch.object(
            api_main,
            "QwenChatClient",
            return_value=object(),
        ), patch.object(
            api_main,
            "ToolRegistry",
            return_value=object(),
        ), patch.object(
            api_main,
            "DeepResearchAgent",
            return_value=FakeAgent(error=RuntimeError("stream boom")),
        ):
            client = TestClient(api_main.create_app())
            response = client.get(
                "/api/research/stream",
                params={"topic": "RAG 测试", "backend": "duckduckgo"},
            )

        self.assertEqual(response.status_code, 200)
        events = parse_sse_events(response.text)
        self.assertEqual(len(events), 1)

        api_error = events[0]
        self.assertEqual(set(api_error.keys()), EVENT_KEYS)
        self.assertEqual(api_error["run_id"], "")
        self.assertEqual(api_error["seq"], 1)
        self.assertEqual(api_error["type"], "api_error")
        self.assertEqual(api_error["stage"], "api")
        self.assertEqual(api_error["status"], "failed")
        self.assertEqual(api_error["message"], "研究接口执行失败")
        self.assertEqual(api_error["step"], 0)
        self.assertIsNone(api_error["task_id"])
        self.assertEqual(api_error["payload"], {})
        self.assertEqual(
            api_error["error"],
            {
                "message": "stream boom",
                "type": "RuntimeError",
            },
        )
        self.assertIsInstance(api_error["timestamp"], float)

    def test_stream_outputs_heartbeat_and_workflow_timeout(self):
        class SlowAgent:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def run_stream(self, topic: str, backend: str | None = None):
                time.sleep(0.3)
                if False:
                    yield {}

        with patch.object(
            api_main.Config,
            "from_env",
            return_value=FakeConfig(
                workflow_timeout_seconds=0.12,
                sse_heartbeat_seconds=0.03,
            ),
        ), patch.object(
            api_main,
            "QwenChatClient",
            return_value=object(),
        ), patch.object(
            api_main,
            "ToolRegistry",
            return_value=object(),
        ), patch.object(
            api_main,
            "DeepResearchAgent",
            return_value=SlowAgent(),
        ):
            client = TestClient(api_main.create_app())
            response = client.get(
                "/api/research/stream",
                params={"topic": "RAG 测试", "backend": "duckduckgo"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(": ping\n\n", response.text)

        events = parse_sse_events(response.text)
        self.assertEqual(events[-1]["type"], "workflow_failed")
        self.assertEqual(events[-1]["stage"], "workflow")
        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(events[-1]["message"], "研究流程执行超时")
        self.assertEqual(events[-1]["error"]["type"], "WorkflowTimeout")
        self.assertEqual(events[-1]["payload"]["result"], {})


if __name__ == "__main__":
    unittest.main()
