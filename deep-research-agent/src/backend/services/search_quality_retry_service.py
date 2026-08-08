from dataclasses import dataclass
from typing import Protocol, Any

from backend.domain.models import TodoItem


@dataclass(frozen=True)
class SearchRetryDecision:
    """补检索决策结果。

    should_retry 表示是否真的需要再次检索；
    reasons 记录触发原因，便于运行记录和日志解释；
    retry_queries 是准备补搜的查询词。
    """
    should_retry: bool
    reasons: list[str]
    retry_queries: list[str]


class SearchQueryRewriter(Protocol):
    """Query rewrite 策略接口。

    当前实现是确定性规则改写；以后如果要接入 LLM query rewrite，
    只需要实现这个协议并注入 SearchQualityRetryService。
    """

    def rewrite(self, task: TodoItem, reasons: list[str]) -> list[str]:
        """根据任务和质量问题生成补检索 query。"""


class DeterministicSearchQueryRewriter:
    """确定性 query rewrite，MVP 阶段不引入额外 LLM 调用。"""

    MAX_RETRY_QUERIES = 2

    def rewrite(self, task: TodoItem, reasons: list[str]) -> list[str]:
        """基于原 query / title / intent 生成少量更偏高质量来源的 query。"""
        cleaned_query = self._clean(task.query)
        cleaned_title = self._clean(task.title)
        cleaned_intent = self._clean(task.intent)

        base = cleaned_query or cleaned_title
        if not base:
            return []

        candidates = [
            f"{base} academic paper arxiv benchmark official documentation",
            f"{base} technical report best practices limitations failure cases",
            f"{cleaned_title} {cleaned_intent} case study evaluation production",
        ]

        return self._unique(candidates)[:self.MAX_RETRY_QUERIES]

    @staticmethod
    def _clean(value: str | None) -> str:
        """清理多余空白，避免拼出的 query 太乱。"""
        return " ".join(str(value or "").split())

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        """按原顺序去重。"""
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.split())
            if normalized and normalized not in seen:
                unique.append(normalized)
                seen.add(normalized)
        return unique


class SearchQualityRetryService:
    """根据来源质量决定是否触发补检索。

    这里只负责策略判断和 query rewrite，不直接调用搜索后端。
    """

    RETRY_MIN_RESULTS = 3
    RETRY_MIN_HIGH_QUALITY_SOURCES = 2
    RETRY_MAX_WEAK_RATIO = 0.6
    HIGH_QUALITY_SOURCE_TYPES = {"academic", "official_doc", "company_tech"}

    def __init__(self, query_rewriter: SearchQueryRewriter | None = None):
        """注入 query_rewriter；默认使用确定性改写器。"""
        self.query_rewriter = query_rewriter or DeterministicSearchQueryRewriter()

    def decide(
            self,
            task: TodoItem,
            filtered_result: dict[str, Any],
    ) -> SearchRetryDecision:
        """根据首次过滤后的来源质量判断是否补检索。

        触发条件包括：
        - 有效来源数量太少；
        - 高质量来源数量不足；
        - 弱来源比例过高。
        """
        if not isinstance(filtered_result, dict):
            return self._build_decision(task, ["搜索结果格式异常"])

        results = filtered_result.get("results") or []
        if not results:
            return self._build_decision(task, ["没有可用来源"])

        high_quality_count = sum(
            1
            for item in results
            if self.is_high_quality_source(item)
        )
        weak_count = sum(
            1
            for item in results
            if self.is_weak_source(item)
        )
        weak_ratio = weak_count / len(results) if results else 1.0

        reasons: list[str] = []

        if len(results) < self.RETRY_MIN_RESULTS:
            reasons.append(f"有效来源不足：{len(results)} < {self.RETRY_MIN_RESULTS}")

        if high_quality_count < self.RETRY_MIN_HIGH_QUALITY_SOURCES:
            reasons.append(
                f"高质量来源不足：{high_quality_count} < {self.RETRY_MIN_HIGH_QUALITY_SOURCES}"
            )

        if weak_ratio > self.RETRY_MAX_WEAK_RATIO:
            reasons.append(
                f"弱来源比例过高：{weak_ratio:.0%} > {self.RETRY_MAX_WEAK_RATIO:.0%}"
            )

        return self._build_decision(task, reasons)

    def _build_decision(
            self,
            task: TodoItem,
            reasons: list[str],
    ) -> SearchRetryDecision:
        """把触发原因转换成最终补检索决策。"""
        retry_queries = self.query_rewriter.rewrite(task, reasons) if reasons else []
        return SearchRetryDecision(
            should_retry=bool(reasons and retry_queries),
            reasons=reasons,
            retry_queries=retry_queries,
        )

    def is_high_quality_source(self, item: dict[str, Any]) -> bool:
        """判断来源是否可以视为高质量来源。"""
        source_type = str(item.get("source_type") or "").lower()
        score = self._safe_int(item.get("score"))
        return (
                source_type in self.HIGH_QUALITY_SOURCE_TYPES
                or score >= 80
        )

    @staticmethod
    def is_weak_source(item: dict[str, Any]) -> bool:
        """判断来源是否偏弱。"""
        score = SearchQualityRetryService._safe_int(item.get("score"))
        source_type = str(item.get("source_type") or "").lower()
        return (
                score < 60
                or source_type in {"community", "unknown"}
        )

    @staticmethod
    def build_retry_notice(reasons: list[str]) -> str:
        """构造给前端运行记录展示的补检索说明。"""
        return "触发补检索：" + "；".join(reasons)

    @staticmethod
    def _safe_int(value: Any) -> int:
        """安全转换分数，异常时返回 0。"""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
