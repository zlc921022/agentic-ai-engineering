import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.core.config import Config
from backend.llm.client import QwenChatClient


class LlmClientTimeoutTest(unittest.TestCase):
    def test_chat_normalizes_native_tool_calls(self):
        """client 应把 SDK tool_calls 转换成项目内部消息结构。"""
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                tool_call = SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(
                        name="supplemental_search",
                        arguments='{"query":"agent failure cases"}',
                    ),
                )
                message = SimpleNamespace(content=None, tool_calls=[tool_call])
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message)]
                )

        client = QwenChatClient.__new__(QwenChatClient)
        client.config = Config.from_env(api_key="fake-key")
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        schemas = [{
            "type": "function",
            "function": {
                "name": "supplemental_search",
                "parameters": {"type": "object"},
            },
        }]

        response = client.chat(
            [{"role": "user", "content": "补充搜索"}],
            tools=schemas,
            tool_choice={
                "type": "function",
                "function": {"name": "supplemental_search"},
            },
            force_non_thinking=True,
        )

        self.assertEqual(response.tool_calls[0].id, "call_1")
        self.assertEqual(response.tool_calls[0].name, "supplemental_search")
        self.assertEqual(
            response.assistant_message["tool_calls"][0]["id"],
            "call_1",
        )
        self.assertEqual(captured["tools"], schemas)
        self.assertEqual(
            captured["extra_body"],
            {"enable_thinking": False},
        )

    def test_chat_does_not_send_dashscope_parameter_to_other_providers(self):
        """非 DashScope 服务不应收到 enable_thinking 私有参数。"""
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                message = SimpleNamespace(content="ok", tool_calls=[])
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message)]
                )

        client = QwenChatClient.__new__(QwenChatClient)
        client.config = Config.from_env(
            api_key="fake-key",
            base_url="https://api.openai.com/v1",
        )
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        client.chat(
            [{"role": "user", "content": "补充搜索"}],
            force_non_thinking=True,
        )

        self.assertNotIn("extra_body", captured)

    def test_stream_uses_idle_read_timeout(self):
        """stream=True 时应使用独立 read timeout 覆盖长时间无 chunk 的场景。"""
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return iter([])

        client = QwenChatClient.__new__(QwenChatClient)
        client.config = Config.from_env(
            api_key="fake-key",
            llm_timeout_seconds=30,
            llm_stream_idle_timeout_seconds=7,
        )
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        list(client.stream("hello"))

        self.assertEqual(captured["timeout"].as_dict()["read"], 7)

    def test_stream_timeout_error_message_is_clear(self):
        """底层 SDK 超时时，应抛出前端和日志都容易理解的中文错误。"""

        class TimeoutChunks:
            def __iter__(self):
                raise TimeoutError("read timed out")

        class FakeCompletions:
            def create(self, **kwargs):
                return TimeoutChunks()

        client = QwenChatClient.__new__(QwenChatClient)
        client.config = Config.from_env(
            api_key="fake-key",
            llm_timeout_seconds=30,
            llm_stream_idle_timeout_seconds=7,
        )
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with self.assertRaisesRegex(TimeoutError, "LLM 流式响应超时"):
            list(client.stream("hello"))


if __name__ == "__main__":
    unittest.main()
