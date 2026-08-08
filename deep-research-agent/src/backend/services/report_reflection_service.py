import json
from dataclasses import dataclass
from typing import Any

from backend.core.app_logger import get_logger
from backend.domain.models import TodoItem
from backend.llm.prompts import ResearchPrompts
from backend.llm.simple_agent import SimpleAgent
from backend.services.report_service import REPORT_MAX_TOKENS, ReportService


@dataclass
class ReflectionDecision:
    """报告反思决策结果。

    should_reflect 表示是否触发修正；
    triggers 是机器可读触发码；
    reasons 是给运行记录和 prompt 使用的人类可读原因。
    """
    should_reflect: bool
    triggers: list[str]
    reasons: list[str]


SNAPSHOT_KEYS = [
    "overall_score",
    "citation_precision",
    "citation_recall",
    "hard_error_count",
    "weak_source_ratio",
    "warning_count",
]


class ReportReflectionService:
    """质检驱动的报告反思修正服务。

    这个服务实现的是 MVP 版反思闭环：最多修正一次报告。
    它不重新检索，也不重新总结任务，只根据已有任务总结、证据表、
    当前报告和 evaluator / judge 反馈，要求 LLM 生成修正版报告。

    举例：
    如果初检发现 citation_precision < 90%，或者 LLM Judge 认为工程建议太空，
    decide() 会触发反思，revise_report() 会要求 reporter 修正引用和建议。
    """

    def __init__(self, agent: SimpleAgent):
        """注入 reflection 专用 SimpleAgent。"""
        self.agent = agent
        self.logger = get_logger(__name__)

    def revise_report(
            self,
            topic: str,
            tasks: list[TodoItem],
            current_report: str,
            evaluator: dict[str, Any],
            triggers: list[str],
    ):
        """根据质检反馈生成修正版报告。

        返回值会再次经过 ReportService.assemble_report()，
        因此参考文献和证据表仍由程序统一生成，避免反思阶段破坏来源契约。
        """
        self.agent.clear_messages()
        revision_prompt = self.build_revision_prompt(
            topic=topic,
            tasks=tasks,
            current_report=current_report,
            evaluator=evaluator,
            triggers=triggers,
        )
        raw_report = self.agent.run(
            "请根据质检意见修正最终研究报告。",
            system_prompt=revision_prompt,
            max_tokens=REPORT_MAX_TOKENS,
        )
        return ReportService.assemble_report(raw_report, tasks)

    def build_revision_prompt(
            self,
            topic: str,
            tasks: list[TodoItem],
            current_report: str,
            evaluator: dict[str, Any],
            triggers: list[str],
    ):
        """构造报告修正 prompt。"""
        return ResearchPrompts.REPORT_REVISION.format(
            research_topic=topic,
            task_summaries=ReportService.build_task_summaries(tasks),
            source_catalog=ReportService.build_evidence_table(tasks),
            current_report=current_report,
            triggers="\n".join(f"- {trigger}" for trigger in triggers) or "- 无",
            evaluator_feedback=self.format_evaluator_feedback(evaluator)
        )

    @staticmethod
    def format_evaluator_feedback(evaluator: dict[str, Any]) -> str:
        """压缩 evaluator 反馈，作为反思 prompt 的结构化输入。"""
        warnings = evaluator.get("warnings") or []
        compact = {
            "overall_score": evaluator.get("overall_score"),
            "citation_precision": evaluator.get("citation_precision"),
            "citation_recall": evaluator.get("citation_recall"),
            "primary_source_ratio": evaluator.get("primary_source_ratio"),
            "weak_source_ratio": evaluator.get("weak_source_ratio"),
            "hard_error_count": evaluator.get("hard_error_count"),
            "warning_count": evaluator.get("warning_count"),
            "judge": evaluator.get("judge"),
            "hybrid_score": evaluator.get("hybrid_score"),
            "warnings": warnings[:12],
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)

    @staticmethod
    def snapshot_evaluator(evaluator: dict[str, Any]) -> dict[str, Any]:
        """提取反思前/后的关键质检指标快照。"""
        return {key: evaluator.get(key) for key in SNAPSHOT_KEYS}

    def decide(self, evaluator: dict[str, Any]) -> ReflectionDecision:
        """根据规则质检和 LLM Judge 结果判断是否反思。"""
        if not evaluator:
            return ReflectionDecision(False, [], ["evaluator 结果为空，跳过反思"])

        triggers: list[str] = []
        reasons: list[str] = []
        overall_score = self._number(evaluator.get("overall_score"))
        hard_error_count = self._number(evaluator.get("hard_error_count"))
        citation_precision = self._number(evaluator.get("citation_precision"))
        citation_recall = self._number(evaluator.get("citation_recall"))
        weak_source_ratio = self._number(evaluator.get("weak_source_ratio"))

        if overall_score < 90:
            triggers.append("overall_score_low")
            reasons.append(f"综合评分低于 90：{overall_score:g}")

        if hard_error_count > 0:
            triggers.append("hard_error")
            reasons.append(f"存在硬错误：{hard_error_count:g} 个")

        if citation_precision < 0.9:
            triggers.append("citation_precision_low")
            reasons.append(f"引用准确率低于 90%：{citation_precision:.0%}")

        if citation_recall < 0.8:
            triggers.append("citation_recall_low")
            reasons.append(f"引用召回率低于 80%：{citation_recall:.0%}")

        if weak_source_ratio > 0.5:
            triggers.append("weak_source_ratio_high")
            reasons.append(f"弱来源比例高于 50%：{weak_source_ratio:.0%}")

        judge = evaluator.get("judge")
        if isinstance(judge, dict) and judge.get("enabled"):
            judge_verdict = str(judge.get("verdict") or "").lower()
            judge_score = self._number(judge.get("score") or 0)
            judge_revision_advice = judge.get("revision_advice") or []
            if judge_verdict == "fail":
                triggers.append("judge_failed")
                reasons.append(f"LLM Judge 判定失败：{judge_score:g}")
            elif judge_score < 85:
                triggers.append("judge_score_low")
                reasons.append(f"LLM Judge 评分低于 85：{judge_score:g}")
            elif judge_verdict == "warn" and judge_revision_advice:
                triggers.append("judge_warned")
                reasons.append("LLM Judge 给出语义修正建议")

        return ReflectionDecision(
            should_reflect=bool(triggers),
            triggers=triggers,
            reasons=reasons,
        )

    @staticmethod
    def _number(value: Any) -> float:
        """安全转换数字，无法转换时返回 0。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
