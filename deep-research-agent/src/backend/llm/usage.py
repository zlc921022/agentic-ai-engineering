"""LLM Token Usage 的轻量运行时采集。

这个模块只记录模型已经返回的 usage，不参与任何模型选择、重试或业务判断。
当前 Deep Research 会并发执行多个 Summary，因此不能使用 ``last_usage`` 这类
共享变量；这里用 ContextVar 隔离 run / stage / task，再用锁保护汇总记录。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Iterator


_CURRENT_RUN_ID: ContextVar[str] = ContextVar("llm_usage_run_id", default="")
_CURRENT_STAGE: ContextVar[str] = ContextVar("llm_usage_stage", default="unknown")
_CURRENT_TASK_ID: ContextVar[int | None] = ContextVar(
    "llm_usage_task_id",
    default=None,
)


@contextmanager
def usage_run_scope(run_id: str) -> Iterator[None]:
    """把当前线程/协程中的模型调用归属到一次研究运行。"""
    token = _CURRENT_RUN_ID.set(str(run_id or ""))
    try:
        yield
    finally:
        _CURRENT_RUN_ID.reset(token)


@contextmanager
def usage_stage_scope(stage: str) -> Iterator[None]:
    """标记当前 LLM 调用属于 planner、summary、reporter 等阶段。"""
    token = _CURRENT_STAGE.set(str(stage or "unknown"))
    try:
        yield
    finally:
        _CURRENT_STAGE.reset(token)


@contextmanager
def usage_task_scope(task_id: int | None) -> Iterator[None]:
    """在线程池 worker 中保留 TodoItem ID，避免并发 Summary 串指标。"""
    token = _CURRENT_TASK_ID.set(task_id)
    try:
        yield
    finally:
        _CURRENT_TASK_ID.reset(token)


@dataclass(frozen=True, slots=True)
class TokenUsageRecord:
    """一次模型请求返回的标准化 Token 数据。"""

    run_id: str
    stage: str
    task_id: int | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0


class UsageCollector:
    """线程安全地保存并汇总同一个 QwenChatClient 的 Usage 记录。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, list[TokenUsageRecord]] = {}

    def record(self, *, model: str, usage: Any) -> None:
        """读取 SDK usage 对象；供应商未返回 usage 时安全跳过。"""
        run_id = _CURRENT_RUN_ID.get()
        normalized = self._normalize_usage(usage)
        if not run_id or normalized is None:
            return

        record = TokenUsageRecord(
            run_id=run_id,
            stage=_CURRENT_STAGE.get(),
            task_id=_CURRENT_TASK_ID.get(),
            model=str(model or ""),
            **normalized,
        )
        with self._lock:
            self._records.setdefault(run_id, []).append(record)

    def summarize(
        self,
        run_id: str,
        *,
        input_price_per_million: float = 0.0,
        output_price_per_million: float = 0.0,
        currency: str = "CNY",
    ) -> dict[str, Any]:
        """按 run 和 stage 汇总 Token，并按可选价格计算估算成本。"""
        with self._lock:
            records = list(self._records.get(run_id, []))

        by_stage: dict[str, dict[str, Any]] = {}
        for record in records:
            stage = by_stage.setdefault(
                record.stage,
                {
                    "request_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cached_tokens": 0,
                    "reasoning_tokens": 0,
                    "task_ids": set(),
                },
            )
            stage["request_count"] += 1
            stage["prompt_tokens"] += record.prompt_tokens
            stage["completion_tokens"] += record.completion_tokens
            stage["total_tokens"] += record.total_tokens
            stage["cached_tokens"] += record.cached_tokens
            stage["reasoning_tokens"] += record.reasoning_tokens
            if record.task_id is not None:
                stage["task_ids"].add(record.task_id)

        stage_rows: dict[str, dict[str, Any]] = {}
        for stage_name, values in sorted(by_stage.items()):
            stage_rows[stage_name] = {
                **{
                    key: value
                    for key, value in values.items()
                    if key != "task_ids"
                },
                "task_ids": sorted(values["task_ids"]),
            }

        prompt_tokens = sum(record.prompt_tokens for record in records)
        completion_tokens = sum(record.completion_tokens for record in records)
        prices_configured = (
            input_price_per_million > 0
            or output_price_per_million > 0
        )
        estimated_cost = (
            prompt_tokens / 1_000_000 * input_price_per_million
            + completion_tokens / 1_000_000 * output_price_per_million
        )

        return {
            "available": bool(records),
            "request_count": len(records),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": sum(record.total_tokens for record in records),
            "cached_tokens": sum(record.cached_tokens for record in records),
            "reasoning_tokens": sum(record.reasoning_tokens for record in records),
            "models": sorted({record.model for record in records if record.model}),
            "by_stage": stage_rows,
            "cost": {
                "calculated": prices_configured,
                "estimated": round(estimated_cost, 8) if prices_configured else None,
                "currency": str(currency or "CNY").upper(),
                "input_price_per_million": input_price_per_million,
                "output_price_per_million": output_price_per_million,
            },
        }

    def clear(self, run_id: str) -> None:
        """最终结果已经生成后释放单次运行记录，避免常驻进程持续增长。"""
        with self._lock:
            self._records.pop(run_id, None)

    def records(self, run_id: str) -> list[dict[str, Any]]:
        """主要供单元测试检查并发归属，不进入业务返回。"""
        with self._lock:
            return [
                asdict(record)
                for record in self._records.get(run_id, [])
            ]

    @classmethod
    def _normalize_usage(cls, usage: Any) -> dict[str, int] | None:
        if usage is None:
            return None

        prompt_tokens = cls._integer(
            cls._value(usage, "prompt_tokens", "input_tokens")
        )
        completion_tokens = cls._integer(
            cls._value(usage, "completion_tokens", "output_tokens")
        )
        total_tokens = cls._integer(cls._value(usage, "total_tokens"))
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        prompt_details = cls._value(usage, "prompt_tokens_details")
        completion_details = cls._value(usage, "completion_tokens_details")
        normalized = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cls._integer(
                cls._value(prompt_details, "cached_tokens")
            ),
            "reasoning_tokens": cls._integer(
                cls._value(completion_details, "reasoning_tokens")
            ),
        }
        # 有些兼容服务会返回空 usage 对象；不把它误计成一次 0 Token 请求。
        return normalized if any(normalized.values()) else None

    @staticmethod
    def _value(source: Any, *names: str) -> Any:
        if source is None:
            return None
        for name in names:
            if isinstance(source, dict) and name in source:
                return source[name]
            value = getattr(source, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0
