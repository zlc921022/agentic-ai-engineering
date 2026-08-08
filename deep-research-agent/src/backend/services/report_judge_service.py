import json
import re
from typing import Any

from backend.domain.models import TodoItem
from backend.llm.prompts import ResearchPrompts
from backend.llm.simple_agent import SimpleAgent
from backend.services.report_service import ReportService
from backend.tools.json_util import clean_json_text

JUDGE_MAX_TOKENS = 2048


class ReportJudgeService:
    """LLM-as-a-Judge 报告语义质检服务。

    ReportEvaluatorService 负责确定性规则检查；ReportJudgeService 负责补充
    机器规则不容易判断的语义维度，例如：
    - 是否覆盖用户主题；
    - 逻辑是否连贯；
    - 工程建议是否可落地；
    - 风险意识是否充分。

    举例：
    一篇报告引用格式完全正确，规则质检可能给高分；
    但如果内容空泛、没有工程建议，LLM Judge 可以给出 warn / fail 和修订建议。
    """

    def __init__(self, agent: SimpleAgent):
        """注入 judge 专用 SimpleAgent。"""
        self.agent = agent

    def run(
            self,
            topic: str,
            report: str,
            tasks: list[TodoItem],
            rule_evaluator: dict[str, Any],
    ):
        """执行一次语义质检，并返回标准化后的 judge 结果。"""
        self.agent.clear_messages()
        prompt = self._build_judge_prompt(
            topic,
            report,
            tasks,
            rule_evaluator
        )
        judge_response = self.agent.run(
            "请按要求输出报告语义质检 JSON。",
            system_prompt=prompt,
            max_tokens=JUDGE_MAX_TOKENS
        )
        result = self._parse_json(judge_response)
        return self._normalize_result(result)

    def _build_judge_prompt(self, topic, report, tasks, rule_evaluator):
        """组装 Judge prompt，把报告、任务总结、规则质检结果一起交给模型。"""
        return ResearchPrompts.REPORT_JUDGE.format(
            research_topic=topic,
            task_summaries=ReportService.build_task_summaries(tasks),
            rule_evaluator=json.dumps(
                self._compact_rule_evaluator(rule_evaluator),
                ensure_ascii=False,
                indent=2,
            ),
            source_catalog=ReportService.build_evidence_table(tasks),
            report=report
        )

    @staticmethod
    def _compact_rule_evaluator(evaluator: dict[str, Any]) -> dict[str, Any]:
        """压缩规则质检结果，避免 Judge prompt 过长。"""
        return {
            "overall_score": evaluator.get("overall_score"),
            "citation_precision": evaluator.get("citation_precision"),
            "citation_recall": evaluator.get("citation_recall"),
            "primary_source_ratio": evaluator.get("primary_source_ratio"),
            "weak_source_ratio": evaluator.get("weak_source_ratio"),
            "hard_error_count": evaluator.get("hard_error_count"),
            "warning_count": evaluator.get("warning_count"),
            "warnings": (evaluator.get("warnings") or [])[:12],
        }

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """解析 Judge 返回 JSON，兼容模型包裹了额外文本的情况。"""
        text = (raw or "").strip()
        if not text:
            raise ValueError("judge 没有返回内容")
        try:
            return json.loads(clean_json_text(text))
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("judge 返回内容不是 JSON")
            return json.loads(match.group(0))

    def _normalize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """
        LLM 生成结果
        {
          "score": 0,
          "verdict": "pass",
          "dimensions": {
            "topic_coverage": 0,
            "logical_consistency": 0,
            "evidence_usage": 0,
            "actionability": 0,
            "risk_awareness": 0
          },
          "warnings": [],
          "revision_advice": []
        }
        """
        score = self._int_between(result.get("score"), 0, 100)
        dimensions = result.get("dimensions")
        if not isinstance(dimensions, dict):
            dimensions = {}

        normalized_dimensions = {
            "topic_coverage": self._int_between(dimensions.get("topic_coverage"), 0, 100),
            "logical_consistency": self._int_between(dimensions.get("logical_consistency"), 0, 100),
            "evidence_usage": self._int_between(dimensions.get("evidence_usage"), 0, 100),
            "actionability": self._int_between(dimensions.get("actionability"), 0, 100),
            "risk_awareness": self._int_between(dimensions.get("risk_awareness"), 0, 100),
        }

        verdict = str(result.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "warn", "fail"}:
            verdict = self._infer_verdict(score)

        return {
            "enabled": True,
            "score": score,
            "verdict": verdict,
            "dimensions": normalized_dimensions,
            "warnings": self._string_list(result.get("warnings"), limit=8),
            "revision_advice": self._string_list(result.get("revision_advice"), limit=8),
        }

    @staticmethod
    def _infer_verdict(score: int) -> str:
        """当模型没有给出合法 verdict 时，根据分数推断。"""
        if score >= 90:
            return "pass"
        if score >= 80:
            return "warn"
        return "fail"

    @staticmethod
    def _int_between(value: Any, minimum: int, maximum: int) -> int:
        """把模型返回的分数安全归一到指定区间。"""
        try:
            parsed = int(round(float(value)))
        except (TypeError, ValueError):
            return minimum
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _string_list(value: Any, limit: int) -> list[str]:
        """把模型返回的列表字段清洗成字符串列表，并限制数量。"""
        if not isinstance(value, list):
            return []
        items = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
            if len(items) >= limit:
                break
        return items
