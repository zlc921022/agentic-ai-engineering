import json
import time
from typing import Any, List

from backend.core.app_logger import get_logger
from backend.domain.models import ResearchState, TodoItem
from backend.llm.prompts import ResearchPrompts
from backend.llm.simple_agent import SimpleAgent
from backend.tools.json_util import clean_json_text


class PlanerService:
    """研究规划服务：把用户主题拆成可执行的子研究任务。

    这个类只关心“怎么生成计划”，不关心任务如何执行。
    Planner 的输出必须是 JSON 数组，后续会被转换成 TodoItem。

    举例：
    输入主题“AI Agent 在生产环境中如何评测和调试？”
    可能拆成：
    - 核心评测指标
    - 轨迹分析与调试
    - 成本控制
    - 安全合规
    """

    def __init__(
            self,
            agent: SimpleAgent,
    ):
        """注入 planner 专用 SimpleAgent。"""
        self.agent = agent
        self.logger = get_logger(__name__)

    def run_plan(self, state: ResearchState) -> list[TodoItem]:
        """调用 LLM 生成研究计划，并转换成 TodoItem 列表。

        这里会兜底处理 title / intent / query 缺失的情况，保证 planner
        偶尔输出不完整 JSON 时，后续流程仍然拿到结构化任务。
        """
        # 生成计划
        started_at = time.perf_counter()
        prompt = ResearchPrompts.PLANNER.format(topic=state.topic)
        self.logger.info(
            "planner llm started topic=%s prompt_chars=%s",
            state.topic,
            len(prompt),
        )
        plan = self.agent.run(
            state.topic,
            system_prompt=prompt,
        )
        self.logger.info(
            "Planner raw output (truncated): %s",
            self._truncate(plan),
        )

        tasks: List[TodoItem] = []
        plans = self.parse_plan(plan)

        for idx, item in enumerate(plans, start=1):
            title = str(item.get("title") or f"任务{idx}").strip()
            intent = str(item.get("intent") or "聚焦主题的关键问题").strip()
            query = str(item.get("query") or state.topic).strip()
            tasks.append(
                TodoItem(
                    id=idx,
                    title=title,
                    intent=intent,
                    query=query or state.topic,
                )
            )
        self.logger.info(
            "Planner produced %s tasks: %s elapsed=%.2fs",
            len(tasks),
            [task.title for task in tasks],
            time.perf_counter() - started_at,
        )
        return tasks

    def parse_plan(self, plan: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        把 planner 输出解析成任务列表。
        [
          {
            "title": "什么是多模态模型",
            "intent": "了解多模态模型的基础概念，为后续研究打下基础",
            "query": "multimodal model definition concept 2024"
          },
        ]
        """
        if isinstance(plan, list):
            return plan

        if not isinstance(plan, str) or not plan.strip():
            return []

        try:
            data = json.loads(clean_json_text(plan))
        except (json.decoder.JSONDecodeError, TypeError):
            return []

        if not isinstance(data, list):
            return []

        # 保证列表里面每个对象都是dict
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _truncate(text: Any, limit: int = 1200) -> str:
        """日志里只保留 planner 输出前半段，避免 app.log 被完整 JSON 刷屏。"""
        value = str(text or "")
        if len(value) <= limit:
            return value
        return value[:limit] + "...(truncated)"
