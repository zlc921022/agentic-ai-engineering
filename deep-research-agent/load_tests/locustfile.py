"""Deep Research SSE 并发压测脚本。

Locust 默认只统计 HTTP 响应头返回时间，而 Deep Research 的核心指标是整条 SSE
工作流完成时间。因此这里额外上报 ``SSE /api/research/stream [workflow]``：
从发出请求开始，一直到 workflow_done/workflow_failed 或连接异常为止。

这个文件只充当外部 HTTP 客户端，不导入、修改或绕过业务 Agent。
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from locust import HttpUser, between, task
from locust.exception import StopUser
import gevent


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TOPICS_FILE = PROJECT_DIR / "benchmarks" / "cases.json"
TERMINAL_EVENTS = {"workflow_done", "workflow_failed", "api_error"}


def load_topics() -> list[str]:
    single_topic = os.getenv("LOAD_TEST_TOPIC", "").strip()
    if single_topic:
        return [single_topic]
    path = Path(os.getenv("LOAD_TEST_TOPICS_FILE", str(DEFAULT_TOPICS_FILE)))
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    topics = [
        str(item.get("topic") or "").strip()
        for item in raw_cases
        if isinstance(item, dict) and str(item.get("topic") or "").strip()
    ]
    if not topics:
        raise ValueError(f"压测问题集为空：{path}")
    return topics


def iter_sse_data(lines: Iterable[str | bytes]) -> Iterator[dict[str, Any]]:
    """轻量解析 SSE data 字段，心跳和非 JSON 消息会被忽略。"""
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r")
        if line == "":
            if data_lines:
                try:
                    data = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    data = None
                if isinstance(data, dict):
                    yield data
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)


class DeepResearchUser(HttpUser):
    """模拟一个持续提交研究问题并等待完整 SSE 结果的用户。"""

    wait_time = between(
        float(os.getenv("LOAD_TEST_WAIT_MIN_SECONDS", "1")),
        float(os.getenv("LOAD_TEST_WAIT_MAX_SECONDS", "3")),
    )

    def on_start(self) -> None:
        self.topics = load_topics()
        self.backend = os.getenv("LOAD_TEST_BACKEND", "duckduckgo")
        self.once_per_user = (
            os.getenv("LOAD_TEST_ONCE_PER_USER", "false").lower()
            in {"1", "true", "yes", "on"}
        )
        self._research_completed = False
        # 健康检查失败时让 Locust 立即记录，而不是静默开始大量研究请求。
        with self.client.get(
            "/healthz",
            name="/healthz",
            catch_response=True,
            timeout=10,
        ) as response:
            if response.status_code != 200:
                response.failure(f"healthz status={response.status_code}")

    @task
    def research(self) -> None:
        if self._research_completed:
            raise StopUser()
        topic = random.choice(self.topics)
        started_at = time.perf_counter()
        event_count = 0
        trace_id = ""
        terminal_type = ""
        exception: Exception | None = None

        try:
            # [connect] 由 Locust 记录建连/响应头耗时；下方再单独上报完整工作流。
            with self.client.get(
                "/api/research/stream",
                params={"topic": topic, "backend": self.backend},
                headers={"Accept": "text/event-stream"},
                stream=True,
                name="/api/research/stream [connect]",
                catch_response=True,
                timeout=(
                    10,
                    float(os.getenv("LOAD_TEST_READ_TIMEOUT_SECONDS", "1200")),
                ),
            ) as response:
                if response.status_code != 200:
                    response.failure(f"status={response.status_code}")
                    raise RuntimeError(f"HTTP {response.status_code}")

                for event in iter_sse_data(
                    response.iter_lines(decode_unicode=True)
                ):
                    event_count += 1
                    if event.get("run_id"):
                        trace_id = str(event["run_id"])
                    event_type = str(event.get("type") or "")
                    if event_type in TERMINAL_EVENTS:
                        terminal_type = event_type
                        break

                if terminal_type == "workflow_done":
                    response.success()
                else:
                    response.failure(
                        f"terminal={terminal_type or 'connection_closed'} "
                        f"trace_id={trace_id or '-'}"
                    )
                    exception = RuntimeError(
                        f"terminal={terminal_type or 'connection_closed'}"
                    )
        except Exception as exc:
            exception = exc

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        # 这个自定义请求统计才是 P50/P95/P99 和失败率的主要观察对象。
        self.environment.events.request.fire(
            request_type="SSE",
            name="/api/research/stream [workflow]",
            response_time=elapsed_ms,
            response_length=event_count,
            response=None,
            context={
                "trace_id": trace_id,
                "terminal_type": terminal_type,
                "backend": self.backend,
            },
            exception=exception,
            start_time=time.time() - elapsed_ms / 1000,
            url="/api/research/stream",
        )
        # 成本受控模式下，每个虚拟用户只执行一次完整研究。适合用 1/2/4 用户
        # 做并发阶梯测试，避免持续压测反复调用真实 LLM。
        self._research_completed = True
        if self.once_per_user:
            completed = int(
                getattr(self.environment, "_one_shot_completed_users", 0)
            ) + 1
            setattr(
                self.environment,
                "_one_shot_completed_users",
                completed,
            )
            runner = self.environment.runner
            target_users = int(
                getattr(runner, "target_user_count", 0)
                or getattr(self.environment.parsed_options, "num_users", 1)
            )
            # 最后一个用户完成后主动结束 Headless 测试，避免等待完整 -t。
            if runner is not None and completed >= target_users:
                # 留出一小段时间让 Locust CSV/HTML Writer 刷新最后一条请求。
                gevent.spawn_later(2.0, runner.quit)
            raise StopUser()
