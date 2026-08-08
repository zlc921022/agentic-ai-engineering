import re
import time
from typing import Any, Callable, Iterator

from backend.core.app_logger import get_logger
from backend.domain.models import TodoItem
from backend.llm.prompts import ResearchPrompts
from backend.llm.simple_agent import SimpleAgent


REPORT_MAX_TOKENS = 4096

# 提取正文中的 T1-S1、T2-S3 等来源 ID。
SOURCE_ID_PATTERN = re.compile(r"\bT\d+-S\d+\b")

# 如果模型不听话，自己生成了参考文献或证据表，
# 程序会把这些内容删除，然后重新生成。
APPENDIX_HEADING_PATTERN = re.compile(
    r"^##\s+(参考文献|证据表)\s*$",
    re.MULTILINE,
)


class ReportService:
    """最终报告生成服务。

    这个类负责把多个已完成任务的总结合并成最终研究报告。
    设计上刻意让 LLM 只写“正文”，参考文献和证据表由 Python 稳定生成：
    - 避免模型编造来源；
    - 保证 source_id 和证据表能被 evaluator 精确校验；
    - 让前端证据表、质检器和报告正文使用同一套来源 ID。

    举例：
    Reporter 正文里引用 [T1-S2]、[T3-S1] 后，
    assemble_report() 会自动只为这些被引用的来源生成参考文献和证据表。
    """

    def __init__(
            self,
            agent: SimpleAgent,
    ):
        """注入 reporter 专用 SimpleAgent。"""
        self.agent = agent
        self.logger = get_logger(__name__)

    def run_report(self, topic, tasks: list[TodoItem]) -> str:
        """非流式生成最终报告。

        主流程目前使用 stream_report() 给前端展示增量输出；
        这个方法保留给测试或未来离线批处理使用。
        """
        started_at = time.perf_counter()
        prompt = self.build_report_prompt(topic, tasks)
        evidence_table = self.build_evidence_table(tasks)
        self.logger.info(
            "report llm started topic=%s task_count=%s completed_tasks=%s prompt_chars=%s evidence_rows=%s max_tokens=%s",
            topic,
            len(tasks),
            len([task for task in tasks if task.status == "completed"]),
            len(prompt),
            self._table_data_rows(evidence_table),
            REPORT_MAX_TOKENS,
        )
        raw_report = self.agent.run(
            topic,
            system_prompt=prompt,
            max_tokens=REPORT_MAX_TOKENS,
        )
        report = self.assemble_report(raw_report, tasks)

        self.logger.info(
            "report llm done topic=%s report_chars=%s elapsed=%.2fs",
            topic,
            len(report or ""),
            time.perf_counter() - started_at,
        )

        return report

    def stream_report(
            self,
            topic: str,
            tasks: list[TodoItem],
    ) -> tuple[Iterator[str], Callable[[], str]]:
        """流式生成最终报告。
        说明：
        - 复用 SimpleAgent.stream_run() 做真正 token 流式，前端支持 reporter delta；
        - 不把 system_prompt 作为 kwargs 传给 stream_run，避免被继续透传到底层 llm.stream；
        - 做法是先把完整报告要求放到 reporter agent 的 system_prompt，再把研究主题作为 input。
        """
        prompt = self.build_report_prompt(topic, tasks)
        evidence_table = self.build_evidence_table(tasks)
        started_at = time.perf_counter()
        self.agent.system_prompt = prompt
        self.logger.info(
            "report stream started topic=%s task_count=%s completed_tasks=%s prompt_chars=%s evidence_rows=%s max_tokens=%s",
            topic,
            len(tasks),
            len([task for task in tasks if task.status == "completed"]),
            len(prompt),
            self._table_data_rows(evidence_table),
            REPORT_MAX_TOKENS,
        )

        chunks: list[str] = []
        chunk_count = 0

        def generator() -> Iterator[str]:
            """逐块转发 reporter 输出，同时缓存完整报告正文。"""
            nonlocal chunk_count
            failed = False
            try:
                for chunk in self.agent.stream_run(
                    topic,
                    max_tokens=REPORT_MAX_TOKENS,
                ):
                    if not chunk:
                        continue

                    chunk_count += 1
                    chunks.append(chunk)
                    yield chunk
            except Exception:
                failed = True
                self.logger.exception(
                    "report stream failed topic=%s elapsed=%.2fs",
                    topic,
                    time.perf_counter() - started_at,
                )
                raise
            finally:
                report_chars = len("".join(chunks))
                self.logger.info(
                    "report stream %s topic=%s chunks=%s report_chars=%s elapsed=%.2fs",
                    "failed" if failed else "done",
                    topic,
                    chunk_count,
                    report_chars,
                    time.perf_counter() - started_at,
                )

        def get_report() -> str:
            """返回附录已经由程序重新生成的完整报告。"""
            raw_report = "".join(chunks).strip()
            return self.assemble_report(raw_report, tasks)

        return generator(), get_report

    def build_report_prompt(
            self,
            topic: str,
            tasks: list[TodoItem],
    ) -> str:
        """构造 Reporter 使用的提示词。

        Reporter 能看到全部可用来源，但只负责生成正文。
        参考文献和证据表由 Python 在生成结束后统一组装。
        """
        task_summaries = self.build_task_summaries(tasks)
        source_catalog = self.build_evidence_table(tasks)
        return ResearchPrompts.REPORT.format(
            research_topic=topic,
            task_summaries=task_summaries,
            source_catalog=source_catalog,
        )

    @staticmethod
    def build_task_summaries(tasks: list[TodoItem]) -> str:
        """把所有任务总结拼成 Reporter prompt 的输入材料。"""
        return "\n\n".join(
            f"## 任务 {task.id}: {task.title}\n"
            f"- 意图：{task.intent}\n"
            f"- 查询：{task.query}\n\n"
            f"{task.summary or '暂无总结'}"
            for task in tasks
        )

    @classmethod
    def strip_generated_appendices(cls, report: str) -> str:
        """删除模型自己生成的参考文献和证据表。

        即使 Prompt 已经明确禁止，模型偶尔仍可能输出附录。
        因此程序在组装最终报告之前再做一次兜底清理。
        """
        report = report.strip()
        match = APPENDIX_HEADING_PATTERN.search(report)
        if match is None:
            return report
        return report[:match.start()].rstrip()

    @classmethod
    def extract_used_source_ids(cls, report_body: str) -> list[str]:
        """按正文首次出现顺序提取来源 ID，并自动去重。"""
        source_ids: list[str] = []
        seen: set[str] = set()
        for source_id in SOURCE_ID_PATTERN.findall(report_body):
            if source_id in seen:
                continue
            seen.add(source_id)
            source_ids.append(source_id)
        return source_ids

    @staticmethod
    def build_source_index(
            tasks: list[TodoItem],
    ) -> dict[str, dict[str, Any]]:
        """建立 source_id 到原始搜索结果的映射。"""
        source_index: dict[str, dict[str, Any]] = {}

        for task in tasks:
            for source in task.search_results or []:
                if not isinstance(source, dict):
                    continue

                source_id = str(source.get("source_id") or "").strip()
                if not source_id:
                    continue

                source_index[source_id] = {
                    **source,
                    # 使用内部字段，避免覆盖来源原来的数据。
                    "_task_title": task.title or "",
                }

        return source_index

    @staticmethod
    def clean_inline_text(value: Any) -> str:
        """清理需要放入 Markdown 单行或表格中的文本。"""
        return (
            str(value or "")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("|", " ")
            .strip()
        )

    @classmethod
    def build_references(
            cls,
            tasks: list[TodoItem],
            source_ids: list[str],
    ) -> str:
        """只为正文实际引用过的有效来源生成参考文献。"""
        source_index = cls.build_source_index(tasks)
        lines: list[str] = []

        for source_id in source_ids:
            source = source_index.get(source_id)

            # 未知 ID 不伪造来源，留给 Evaluator 报错。
            if source is None:
                continue

            title = cls.clean_inline_text(source.get("title")) or "未命名来源"
            url = str(source.get("url") or "").strip()

            lines.append(f"[{source_id}] {title} - {url}")

        return "\n".join(lines)

    @staticmethod
    def source_confidence(source_type: str) -> str:
        """根据来源类型计算证据表中的可信度。"""
        if source_type in {"academic", "official_doc"}:
            return "strong"

        if source_type == "company_tech":
            return "medium"

        return "weak"

    @classmethod
    def build_evidence_table(
            cls,
            tasks: list[TodoItem],
            source_ids: list[str] | None = None,
    ) -> str:
        """生成来源目录或最终证据表。

        source_ids=None：
            返回全部来源，提供给 Reporter 选择引用。

        source_ids 有值：
            只返回正文实际引用过的来源，用于最终报告。
        """
        source_index = cls.build_source_index(tasks)

        # dict 会保留插入顺序，因此全部来源仍按照任务和搜索顺序排列。
        ordered_ids = (
            list(source_index.keys())
            if source_ids is None
            else source_ids
        )

        rows = [
            "| 来源ID | 任务 | 标题 | 类型 | 评分 | 可信度 | 链接 |",
            "|---|---|---|---|---:|---|---|",
        ]

        for source_id in ordered_ids:
            source = source_index.get(source_id)

            # 正文可能引用模型编造的 T9-S9。
            # 这里不生成假来源，让 Evaluator 识别这个问题。
            if source is None:
                continue

            task_title = cls.clean_inline_text(source.get("_task_title"))
            title = cls.clean_inline_text(source.get("title"))
            source_type = (
                cls.clean_inline_text(source.get("source_type"))
                or "unknown"
            )
            score = source.get("score", "")
            confidence = cls.source_confidence(source_type)

            url = (
                str(source.get("url") or "")
                .replace("\n", "")
                .replace("\r", "")
                .replace("|", "%7C")
                .strip()
            )

            rows.append(
                f"| {source_id} | {task_title} | {title} | "
                f"{source_type} | {score} | {confidence} | {url} |"
            )

        # 没有来源时只保留表头。
        # Evaluator 会正确判断为“没有解析到有效来源”。
        return "\n".join(rows)

    @classmethod
    def assemble_report(
            cls,
            raw_report: str,
            tasks: list[TodoItem],
    ) -> str:
        """把 LLM 正文组装成最终研究报告。

        数据流：
        LLM 原始输出
        -> 删除模型生成的附录
        -> 提取正文引用
        -> 自动生成参考文献
        -> 自动生成证据表
        """
        report_body = cls.strip_generated_appendices(raw_report)
        used_source_ids = cls.extract_used_source_ids(report_body)

        references = cls.build_references(
            tasks,
            used_source_ids,
        )
        evidence_table = cls.build_evidence_table(
            tasks,
            source_ids=used_source_ids,
        )

        if not references:
            references = "正文未使用可识别的来源。"

        return "\n\n".join([
            report_body,
            "## 参考文献",
            references,
            "## 证据表",
            evidence_table,
        ]).strip()

    @staticmethod
    def _table_data_rows(table: str) -> int:
        """统计证据表数据行数，不计算表头和分隔行。"""
        rows = [
            line
            for line in table.splitlines()
            if line.strip().startswith("|") and line.strip().endswith("|")
        ]
        return max(len(rows) - 2, 0)
