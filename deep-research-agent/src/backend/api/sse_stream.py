"""SSE 事件流适配器。

这个模块只处理 HTTP SSE 传输层问题：
- 把 DeepResearchAgent 的 dict 事件包装成浏览器 EventSource 能识别的格式；
- 长时间没有业务事件时输出 `: ping\n\n` 心跳；
- 给整次 workflow 做总超时兜底；
- 把 API 层异常包装成统一 research_event。

举例：
FastAPI endpoint 创建 DeepResearchAgent 后，不再自己管理 queue / thread / timeout，
而是把 agent 交给 ResearchSseStreamer.stream()，由这里持续产出 SSE 字符串。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Iterator

from backend.core.config import Config
from backend.domain.event_models import ResearchEvent


HEARTBEAT = object()


class ResearchSseStreamer:
    """DeepResearchAgent 到 SSE 响应的传输层适配器。

    这个类不理解 planner/search/summary/reporter 的业务细节，只关心“事件怎么稳定传给前端”。

    核心结构：
    1. producer 线程执行 agent.run_stream()，把业务事件放进 queue；
    2. 当前 SSE generator 从 queue 消费事件并 yield 给浏览器；
    3. queue 暂时没事件时发送 SSE comment 心跳；
    4. 总耗时超过 WORKFLOW_TIMEOUT_SECONDS 时发送 workflow_failed。

    这样即使中间搜索或 LLM 很久没有业务事件，前端连接也不会长期静默，
    用户也能在总超时后看到明确失败原因。
    """

    def __init__(self, *, agent: Any, config: Config, logger: Any) -> None:
        """保存单次请求需要的 agent、配置和 logger。

        每个 HTTP 请求都会创建新的 ResearchSseStreamer，因此这里保存 seq 状态是安全的。
        如果未来 agent/streamer 变成单例，需要把这些状态下沉到 per-request context。
        """
        self.agent = agent
        self.config = config
        self.logger = logger
        self._seq = 0
        self._seq_lock = threading.Lock()

    def stream(
            self,
            *,
            topic: str,
            backend: str,
            warnings: list[str] | None = None,
    ) -> Iterator[str]:
        """产出完整 SSE 字符串流。

        warnings 用于先向前端提示配置问题，比如缺少搜索 API Key。
        随后启动 producer 线程执行真正研究流程。
        """
        warnings = warnings or []
        if warnings:
            self.logger.info(
                "research config warnings topic=%s backend=%s warnings=%s",
                topic,
                backend,
                warnings,
            )
            yield self._sse(
                self._api_event(
                    "config_warning",
                    stage="config",
                    status="info",
                    message="配置存在告警",
                    payload={"warnings": warnings},
                )
            )

        finished = object()
        event_queue: queue.Queue[Any] = queue.Queue()
        stop_requested = threading.Event()
        started_at = time.monotonic()
        workflow_timeout_seconds, heartbeat_seconds = self._timing_config()

        producer = threading.Thread(
            target=self._produce_agent_events,
            kwargs={
                "topic": topic,
                "backend": backend,
                "event_queue": event_queue,
                "finished": finished,
                "stop_requested": stop_requested,
            },
            name="research-sse-producer",
            daemon=True,
        )
        producer.start()

        while True:
            remaining = self._workflow_remaining_seconds(
                started_at=started_at,
                timeout_seconds=workflow_timeout_seconds,
            )
            if remaining <= 0:
                stop_requested.set()
                yield self._workflow_timeout_sse(
                    topic=topic,
                    backend=backend,
                    timeout_seconds=workflow_timeout_seconds,
                )
                return

            item = self._next_item_or_heartbeat(
                event_queue=event_queue,
                heartbeat_seconds=heartbeat_seconds,
                remaining_seconds=remaining,
            )
            if item is HEARTBEAT:
                yield self._heartbeat_sse()
                continue

            if item is finished:
                return

            if not isinstance(item, dict):
                continue

            yield self._sse(item)

            if item.get("type") in {
                "workflow_done",
                "workflow_failed",
                "api_error",
            }:
                stop_requested.set()
                return

    def _timing_config(self) -> tuple[float, float]:
        """读取并兜底 SSE 心跳和 workflow 总超时配置。

        Config 正常会保证正整数；这里再防御一次，方便测试 fake config 或未来扩展。
        """
        workflow_timeout_seconds = float(self.config.workflow_timeout_seconds)
        heartbeat_seconds = float(self.config.sse_heartbeat_seconds)
        if workflow_timeout_seconds <= 0:
            workflow_timeout_seconds = 900
        if heartbeat_seconds <= 0:
            heartbeat_seconds = 15
        return workflow_timeout_seconds, heartbeat_seconds

    @staticmethod
    def _workflow_remaining_seconds(
            *,
            started_at: float,
            timeout_seconds: float,
    ) -> float:
        """计算整次研究流程距离总超时还剩多少秒。"""
        elapsed = time.monotonic() - started_at
        return timeout_seconds - elapsed

    @staticmethod
    def _next_item_or_heartbeat(
            *,
            event_queue: queue.Queue[Any],
            heartbeat_seconds: float,
            remaining_seconds: float,
    ) -> Any:
        """等待下一条业务事件；等待超时则返回 HEARTBEAT 哨兵。

        等待时间取 min(心跳间隔, workflow 剩余时间)，这样不会因为心跳等待
        越过 workflow 总超时边界。
        """
        try:
            return event_queue.get(timeout=min(heartbeat_seconds, remaining_seconds))
        except queue.Empty:
            return HEARTBEAT

    @staticmethod
    def _heartbeat_sse() -> str:
        """生成 SSE comment 心跳。

        原生 EventSource 会忽略以冒号开头的 comment 行，前端业务层不会感知，
        但浏览器和中间代理能看到连接仍有数据流动。
        """
        return ": ping\n\n"

    def _workflow_timeout_sse(
            self,
            *,
            topic: str,
            backend: str,
            timeout_seconds: float,
    ) -> str:
        """记录 workflow 超时日志，并返回 workflow_failed SSE。"""
        self.logger.warning(
            "research workflow timeout topic=%s backend=%s timeout=%.2fs",
            topic,
            backend,
            timeout_seconds,
        )
        return self._sse(
            self._workflow_timeout_event(
                timeout_seconds=timeout_seconds,
            )
        )

    def _sse(self, event: dict[str, Any]) -> str:
        """把单个事件 dict 包装成浏览器 EventSource 格式。"""
        event_id = event.get("seq") or ""
        return (
            f"id: {event_id}\n"
            "event: research_event\n"
            f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        )

    def _api_event(
            self,
            event_type: str,
            *,
            stage: str,
            status: str,
            message: str,
            payload: dict[str, Any] | None = None,
            error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造 API/SSE 层自身事件，例如 config_warning / api_error。"""
        # api_error 可能在 producer 线程里构造，workflow timeout 在 SSE 线程里构造；
        # 加锁保证 API 层自建事件的 seq 单调递增，不出现并发覆盖。
        with self._seq_lock:
            self._seq += 1
            event_seq = self._seq

        return ResearchEvent(
            run_id="",
            seq=event_seq,
            type=event_type,
            stage=stage,
            status=status,
            message=message,
            step=0,
            payload=payload or {},
            error=error,
        ).to_dict()

    def _workflow_timeout_event(self, *, timeout_seconds: float) -> dict[str, Any]:
        """构造整次研究流程超时事件。

        这个事件由 API 层发出，不走 ResearchEventBuilder，因为它不是某个 Agent
        阶段的业务事件，而是 HTTP/SSE 层的 watchdog 兜底。
        """
        return self._api_event(
            "workflow_failed",
            stage="workflow",
            status="failed",
            message="研究流程执行超时",
            payload={
                "result": {},
                "timeout_seconds": timeout_seconds,
            },
            error={
                "message": "研究流程执行超时",
                "type": "WorkflowTimeout",
            },
        )

    def _produce_agent_events(
            self,
            *,
            topic: str,
            backend: str,
            event_queue: queue.Queue[Any],
            finished: object,
            stop_requested: threading.Event,
    ) -> None:
        """后台执行研究流程，把业务事件写入队列。

        当前 MVP 不强杀后台线程。超时后 SSE 会结束并提示前端失败，
        后台依赖搜索/LLM 自身 timeout 尽快退出；真正的取消机制后续再做。
        """
        try:
            for event in self.agent.run_stream(topic=topic, backend=backend):
                if stop_requested.is_set():
                    break
                event_queue.put(event)
        except Exception as exc:
            self.logger.exception(
                "research stream failed topic=%s backend=%s",
                topic,
                backend,
            )
            event_queue.put(
                self._api_event(
                    "api_error",
                    stage="api",
                    status="failed",
                    message="研究接口执行失败",
                    error={
                        "message": str(exc),
                        "type": exc.__class__.__name__,
                    },
                )
            )
        finally:
            event_queue.put(finished)
