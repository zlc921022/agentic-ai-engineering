"""Advanced RAG 课程能力的通用数据结构。

这个文件只放“结果对象”，不放业务逻辑。
这样评估模块、检索模块、服务层都可以复用同一套结构，避免到处传 dict。
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class TriadMetricResult:
    """RAG Triad 单个指标的评估结果。

    score 统一使用 0-1 区间：
    - 1.0 表示非常好
    - 0.0 表示完全不满足

    reason 保留模型给出的中文解释，方便你在 UI 或面试复盘里说明
    “为什么这个回答被判好/不好”。
    """

    name: str
    score: float
    reason: str


@dataclass
class RAGTriadReport:
    """RAG Triad 总报告。

    课程里的三元组是：
    1. Answer Relevance：答案是否回答了问题
    2. Context Relevance：检索上下文是否和问题相关
    3. Groundedness：答案是否被上下文支撑
    """

    answer_relevance: TriadMetricResult
    context_relevance: TriadMetricResult
    groundedness: TriadMetricResult
    context_items: List[TriadMetricResult] = field(default_factory=list)

    @property
    def average_score(self) -> float:
        """三个核心指标的平均分，方便做快速横向对比。"""
        return round(
            (
                self.answer_relevance.score
                + self.context_relevance.score
                + self.groundedness.score
            )
            / 3,
            4,
        )

    def to_text(self) -> str:
        """转成适合 Gradio 调试框展示的文本。"""
        lines = [
            "RAG Triad 评估：",
            f"- 平均分: {self.average_score:.2f}",
            (
                f"- Answer Relevance: {self.answer_relevance.score:.2f} "
                f"({self.answer_relevance.reason})"
            ),
            (
                f"- Context Relevance: {self.context_relevance.score:.2f} "
                f"({self.context_relevance.reason})"
            ),
            (
                f"- Groundedness: {self.groundedness.score:.2f} "
                f"({self.groundedness.reason})"
            ),
        ]
        if self.context_items:
            lines.append("- Context 明细:")
            for item in self.context_items:
                lines.append(f"  - {item.name}: {item.score:.2f} ({item.reason})")
        return "\n".join(lines)
