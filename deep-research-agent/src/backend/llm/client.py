from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx
from langchain_community.embeddings import DashScopeEmbeddings
from openai import OpenAI

from backend.core.app_logger import get_logger
from backend.core.config import Config
from backend.llm.usage import UsageCollector


client_logger = get_logger(__name__)


@dataclass(frozen=True)
class NativeToolCall:
    """把 OpenAI SDK 的 tool call 对象转换成项目内部的稳定结构。"""

    id: str
    name: str
    arguments: str


@dataclass
class NativeChatResponse:
    """原生 Function Calling 调用结果。

    上层 Agent 不直接依赖 OpenAI SDK 对象，避免 SDK 升级后字段访问散落在项目里。
    assistant_message 会原样追加到下一轮 messages，保证 tool_call_id 链路完整。
    """

    content: str = ""
    tool_calls: list[NativeToolCall] = field(default_factory=list)
    assistant_message: dict[str, Any] = field(default_factory=dict)


class QwenChatClient:
    """OpenAI-compatible Qwen/DashScope 聊天模型客户端。

    项目里的 SimpleAgent 不直接依赖具体 SDK，而是依赖这个薄封装。
    这样以后切换 base_url、model 或兼容其它 OpenAI 协议模型时，
    主要改 Config 和这个 client 即可。
    """

    def __init__(self, config: Config):
        """根据配置创建 OpenAI-compatible client。"""
        self.config = config
        self.usage_collector = UsageCollector()
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.llm_timeout_seconds,
        )

    def complete(self,
                 prompt: str,
                 *,
                 temperature: float = 1.0,
                 top_p: float = 0.9,
                 max_tokens: int = 2048) -> str:
        """非流式生成文本。"""
        resp = self.client.chat.completions.create(
            model=self.config.chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        self._record_usage(getattr(resp, "usage", None))
        return resp.choices[0].message.content or ""

    def chat(
            self,
            messages: list[dict[str, Any]],
            *,
            tools: list[dict[str, Any]] | None = None,
            tool_choice: str | dict[str, Any] | None = None,
            temperature: float = 0.1,
            top_p: float = 0.9,
            max_tokens: int = 2048,
            force_non_thinking: bool = False,
    ) -> NativeChatResponse:
        """使用原生 messages / tools 协议调用模型。

        ``complete()`` 和 ``stream()`` 继续服务 Planner、Summary、Reporter；
        只有 FunctionCallingAgent 使用这里，避免为了工具调用破坏现有生成链路。

        DashScope 的思考模式不支持用对象形式的 ``tool_choice`` 强制指定工具。
        Function Calling 补检索需要稳定地产生指定 tool_call，因此该场景通过
        ``extra_body`` 关闭思考模式。其他 OpenAI-compatible 服务不透传这个
        DashScope 私有参数，避免影响通用兼容性。
        """
        request: dict[str, Any] = {
            "model": self.config.chat_model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if tools:
            request["tools"] = tools
        if tool_choice is not None:
            request["tool_choice"] = tool_choice
        if force_non_thinking and self._uses_dashscope():
            request["extra_body"] = {"enable_thinking": False}

        response = self.client.chat.completions.create(**request)
        self._record_usage(getattr(response, "usage", None))
        message = response.choices[0].message
        content = message.content or ""
        raw_tool_calls = getattr(message, "tool_calls", None) or []

        tool_calls: list[NativeToolCall] = []
        assistant_tool_calls: list[dict[str, Any]] = []
        for raw_call in raw_tool_calls:
            function = getattr(raw_call, "function", None)
            name = str(getattr(function, "name", "") or "")
            arguments = str(getattr(function, "arguments", "") or "")
            call_id = str(getattr(raw_call, "id", "") or "")
            if not name or not call_id:
                continue

            tool_calls.append(
                NativeToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )
            # 下一轮必须把模型原先提出的 tool_calls 一起带回，并保持 call id 不变。
            assistant_tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            })

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls

        return NativeChatResponse(
            content=content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )

    def _uses_dashscope(self) -> bool:
        """判断当前客户端是否连接阿里云百炼的 OpenAI 兼容接口。"""
        return "dashscope.aliyuncs.com" in str(self.config.base_url).lower()

    def stream(self,
               prompt: str,
               *,
               temperature: float = 1.0,
               top_p: float = 0.9,
               max_tokens: int = 2048) -> Iterable[str]:
        """流式生成文本，逐 chunk yield content。"""
        # OpenAI client 的全局 timeout 更像“请求级兜底”；
        # stream=True 时，连接可能建立成功但长时间没有新 chunk。
        # read timeout 专门覆盖这种“流式空转”，避免 summary/report 一直等不到后续 token。
        stream_timeout = httpx.Timeout(
            timeout=self.config.llm_timeout_seconds,
            connect=10,
            read=self.config.llm_stream_idle_timeout_seconds,
            write=10,
            pool=10,
        )
        request: dict[str, Any] = {
            "model": self.config.chat_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": True,
            "timeout": stream_timeout,
        }
        # DashScope 的 OpenAI-compatible 流只有显式开启 include_usage，
        # 才会在收尾 chunk 返回真实 Token。其它供应商保持原请求不变，
        # 避免不支持 stream_options 时影响现有生成流程。
        if self._uses_dashscope():
            request["stream_options"] = {"include_usage": True}

        try:
            resp = self.client.chat.completions.create(**request)
            usage_recorded = False
            for chunk in resp:
                # usage 通常位于没有 choices 的最后一个 chunk，必须先读取再
                # 进入正文解析；记录后仍保持原有 yield 字符串契约不变。
                usage = getattr(chunk, "usage", None)
                if usage is not None and not usage_recorded:
                    self._record_usage(usage)
                    usage_recorded = True

                # DashScope/Qwen 的 OpenAI-compatible stream 可能返回没有 choices 的收尾 chunk。
                # 如果直接 chunk.choices[0]，总结内容明明已经流完，也会在最后抛异常，
                # 外层 worker 就会把任务误标记成 failed。
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue

                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue

                # reasoning_content 不混入正文；前端任务总结只展示 content。
                text = getattr(delta, "content", None)
                if text:
                    yield text
        except Exception as exc:
            if self._is_timeout_error(exc):
                raise TimeoutError("LLM 流式响应超时") from exc
            raise

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """判断底层 SDK 异常是否属于请求超时或流式读取超时。"""
        name = exc.__class__.__name__.lower()
        message = str(exc).lower()
        return "timeout" in name or "timed out" in message

    def usage_summary(self, run_id: str) -> dict[str, Any]:
        """读取一次研究运行的 Token 汇总；不改变任何模型调用返回值。"""
        return self._collector().summarize(
            run_id,
            input_price_per_million=self.config.llm_input_price_per_million,
            output_price_per_million=self.config.llm_output_price_per_million,
            currency=self.config.llm_price_currency,
        )

    def clear_usage(self, run_id: str) -> None:
        """最终 SSE 已构建后释放采集记录；清理失败不能影响业务流。"""
        try:
            self._collector().clear(run_id)
        except Exception:
            # 可观测性必须 Fail-Open：最多丢失一次内存清理，不能让已经完成的
            # workflow 在 SSE 收尾阶段被误判为失败。
            client_logger.exception(
                "llm usage clear failed run_id=%s",
                run_id,
            )

    def _record_usage(self, usage: Any) -> None:
        """旁路记录模型 Usage；任何采集异常都不得改变原模型返回值。"""
        try:
            self._collector().record(
                model=self.config.chat_model,
                usage=usage,
            )
        except Exception:
            # 这里位于模型响应和业务返回值之间。如果把异常继续向外抛，
            # 会出现“模型已成功、仅统计失败，却把 Planner/Summary 判失败”。
            client_logger.exception(
                "llm usage record failed model=%s",
                self.config.chat_model,
            )

    def _collector(self) -> UsageCollector:
        # 少量旧测试通过 __new__ 构造 client，没有执行 __init__。
        # 这里延迟补齐 collector，保持这些测试和外部注入方式兼容。
        collector = getattr(self, "usage_collector", None)
        if collector is None:
            collector = UsageCollector()
            self.usage_collector = collector
        return collector


class DashScopeEmbeddingClient:
    """DashScope Embedding 客户端。

    当前深度研究主流程还没接入长期记忆/向量库，但保留这个封装，
    方便后续做向量检索或笔记知识库。
    """

    def __init__(self, config: Config):
        """初始化 DashScopeEmbeddings。"""
        self.config = config
        self.embedding = DashScopeEmbeddings(
            model=config.embedding_model,
            dashscope_api_key=config.api_key,
        )

    def embed_documents(self, texts):
        """批量生成文档向量。"""
        return self.embedding.embed_documents(texts)

    def embed_query(self, text):
        """生成单个查询向量。"""
        return self.embedding.embed_query(text)

    def get_embedding_function(self):
        """兼容需要 embedding function 对象的调用方。"""
        return self
