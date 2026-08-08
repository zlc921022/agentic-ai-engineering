import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse


class ReportEvaluatorService:
    """对最终研究报告做规则质检。

    这是确定性的 hard rule evaluator，不调用 LLM。
    它关注机器可验证的问题：
    - 报告是否有证据表；
    - 正文引用是否能在证据表和参考文献中找到；
    - 是否混用了旧式 [1] 引用；
    - weak 来源是否支撑了过强结论或具体数字；
    - 一手来源比例、弱来源比例、域名集中度等质量指标。

    举例：
    如果正文写了 [T9-S9]，但证据表没有这个来源，
    check_citation_integrity() 会给出硬错误，最终影响 overall_score。
    """

    # 先定位方括号，再从括号内部提取来源 ID。这样同时兼容：
    # [T1-S1] 和 [T1-S1, T1-S2, T2-S3]。
    CITATION_GROUP_PATTERN = re.compile(r"\[([^\[\]]+)\]")
    SOURCE_ID_PATTERN = re.compile(r"\bT\d+-S\d+\b")
    SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    # 旧格式只考虑常见的 [1] ~ [999]。四位数字更可能是来源标题中的年份，
    # 例如 “Advanced RAG Techniques [2026]”，不应该因此扣引用分。
    OLD_CITATION_PATTERN = re.compile(r"\[[1-9]\d{0,2}\]")

    STRONG_WORDS = [
        "绝大多数",
        "普遍",
        "已证实",
        "研究表明",
        "数据显示",
        "明确证明",
        "必然",
        "一定",
    ]

    HEDGE_WORDS = [
        "来源声称",
        "该来源声称",
        "该文章声称",
        "该博客声称",
        "该文章提到",
        "该来源提到",
        "部分来源认为",
        "行业观察指出",
        "未提供原始",
        "未提供实验",
        "未说明",
        "缺乏实证",
        "应谨慎",
        "非实证",
    ]

    NUMBER_PATTERN = re.compile(
        r"(\d+(\.\d+)?\s?%|\d+\s?–\s?\d+\s?%|\d+\s?-\s?\d+\s?%|\d+(\.\d+)?\s?(倍|分钟|年|个|项|人|次|美元|元))"
    )
    PRIMARY_SOURCE_TYPES = {"academic", "official_doc"}

    def run(self, report: str) -> dict[str, Any]:
        """执行完整规则质检并返回评分和告警。"""
        body, references, _ = self.split_report_sections(report)
        evidence_sources = self.parse_evidence_table(report)
        body_citations = self.extract_citations(body)
        reference_citations = self.extract_citations(references)
        old_citations = self.extract_old_citations(body)

        hard_warnings = []
        quality_warnings = []

        hard_warnings.extend(
            self.check_evidence_table(report, evidence_sources)
        )
        integrity_warnings = self.check_citation_integrity(
            body_citations,
            reference_citations,
            old_citations,
            evidence_sources,
        )
        # 正文引用不存在、参考文献缺失属于硬错误；证据表有未使用来源更像质量提醒。
        for warning in integrity_warnings:
            if warning.startswith("证据表中存在正文未使用的来源"):
                quality_warnings.append(warning)
            else:
                hard_warnings.append(warning)

        quality_warnings.extend(
            self.check_weak_source_claims(body, evidence_sources)
        )
        warnings = hard_warnings + quality_warnings

        citation_score = self.score_citations(
            body_citations,
            reference_citations,
            old_citations,
            evidence_sources,
        )
        evidence_score = self.score_evidence_table(report, evidence_sources)
        source_quality_score = self.score_source_quality(warnings)
        citation_metrics = self.citation_metrics(
            body_citations,
            evidence_sources,
        )
        source_metrics = self.source_quality_metrics(evidence_sources)

        overall_score = round(
            citation_score * 0.35
            + evidence_score * 0.30
            + source_quality_score * 0.35
        )

        return {
            "overall_score": overall_score,
            "citation_score": citation_score,
            "evidence_score": evidence_score,
            "source_quality_score": source_quality_score,
            # 引用数量只统计正文，不让参考文献和证据表替正文“凑数”。
            "citations_count": len(body_citations),
            "unique_citations_count": len(set(body_citations)),
            "reference_sources_count": len(set(reference_citations)),
            "evidence_sources_count": len(evidence_sources),
            "citation_precision": citation_metrics["citation_precision"],
            "citation_recall": citation_metrics["citation_recall"],
            "primary_source_ratio": source_metrics["primary_source_ratio"],
            "weak_source_ratio": source_metrics["weak_source_ratio"],
            "unique_domain_count": source_metrics["unique_domain_count"],
            "max_domain_concentration": source_metrics["max_domain_concentration"],
            "hard_error_count": len(hard_warnings),
            "quality_warning_count": len(quality_warnings),
            "warning_count": len(warnings),
            "warnings": warnings,
        }

    def split_report_sections(self, report: str) -> tuple[str, str, str]:
        """拆分正文、参考文献和证据表。

        正文截止到最先出现的“参考文献”或“证据表”标题；参考文献通常位于
        证据表之前。缺失某个章节时返回空字符串，交给现有检查逻辑处理。
        """
        matches = list(self.SECTION_PATTERN.finditer(report))
        reference_match = next(
            (
                match
                for match in matches
                if match.group(1).strip() == "参考文献"
            ),
            None,
        )
        evidence_match = next(
            (
                match
                for match in matches
                if match.group(1).strip() == "证据表"
            ),
            None,
        )

        section_starts = [
            match.start()
            for match in (reference_match, evidence_match)
            if match is not None
        ]
        body_end = min(section_starts) if section_starts else len(report)
        body = report[:body_end].strip()

        references = ""
        if reference_match is not None:
            reference_end = (
                evidence_match.start()
                if evidence_match is not None
                and evidence_match.start() > reference_match.start()
                else len(report)
            )
            references = report[reference_match.end():reference_end].strip()

        evidence = (
            report[evidence_match.end():].strip()
            if evidence_match is not None
            else ""
        )
        return body, references, evidence

    def parse_evidence_table(self, report: str) -> dict[str, dict[str, str]]:
        """从 Markdown 证据表解析来源信息。

        返回结构以 source_id 为 key，方便后续快速判断正文引用是否存在。
        """
        if "## 证据表" not in report:
            return {}

        evidence_part = report.split("## 证据表", 1)[1]
        lines = evidence_part.splitlines()

        table_lines = [
            line.strip()
            for line in lines
            if line.strip().startswith("|") and line.strip().endswith("|")
        ]

        if len(table_lines) < 3:
            return {}

        header = self.split_table_row(table_lines[0])
        sources: dict[str, dict[str, str]] = {}

        for line in table_lines[2:]:
            if "---" in line:
                continue

            cells = self.split_table_row(line)
            if len(cells) != len(header):
                continue

            row = dict(zip(header, cells))
            source_id = row.get("来源ID", "").strip()
            if not source_id:
                continue

            sources[source_id] = {
                "task": row.get("任务", ""),
                "title": row.get("标题", ""),
                "source_type": row.get("类型", ""),
                "score": row.get("评分", ""),
                "confidence": row.get("可信度", ""),
                "url": row.get("链接", ""),
            }

        return sources

    @staticmethod
    def split_table_row(line: str) -> list[str]:
        """拆分 Markdown 表格行。"""
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    def extract_citations(self, text: str) -> list[str]:
        """从文本中提取 T1-S1 格式引用。"""
        citations: list[str] = []
        for group in self.CITATION_GROUP_PATTERN.findall(text):
            citations.extend(self.SOURCE_ID_PATTERN.findall(group))
        return citations

    def extract_old_citations(self, report: str) -> list[str]:
        """提取旧式 [1] 引用编号，只检查正文区域。"""
        # 只检查报告正文。参考文献标题和证据表是外部来源的原始元数据，
        # 其中可能合法包含 [2026]、[12] 等文本，不代表报告采用了旧式引用。
        section_positions = [
            position
            for heading in ("## 参考文献", "## 证据表")
            if (position := report.find(heading)) >= 0
        ]
        body_end = min(section_positions) if section_positions else len(report)
        return self.OLD_CITATION_PATTERN.findall(report[:body_end])

    def check_evidence_table(
        self,
        report: str,
        evidence_sources: dict[str, dict[str, str]],
    ) -> list[str]:
        """检查证据表是否存在且能解析出有效来源。"""
        warnings = []

        if "## 证据表" not in report:
            warnings.append("缺少 ## 证据表。")
            return warnings

        if not evidence_sources:
            warnings.append("证据表存在，但没有解析到有效来源。")

        return warnings

    def check_citation_integrity(
        self,
        body_citations: list[str],
        reference_citations: list[str],
        old_citations: list[str],
        evidence_sources: dict[str, dict[str, str]],
    ) -> list[str]:
        """检查正文引用、参考文献和证据表之间是否一致。"""
        warnings = []

        if old_citations:
            warnings.append(f"发现旧式引用编号：{sorted(set(old_citations))}，应使用 [T1-S1] 格式。")

        evidence_ids = set(evidence_sources.keys())
        body_ids = set(body_citations)
        reference_ids = set(reference_citations)

        missing_in_evidence = sorted(body_ids - evidence_ids)
        if missing_in_evidence:
            warnings.append(f"正文存在未出现在证据表的引用：{missing_in_evidence}")

        missing_in_references = sorted(body_ids - reference_ids)
        if missing_in_references:
            warnings.append(f"正文引用未列入参考文献：{missing_in_references}")

        unused_sources = sorted(evidence_ids - body_ids)
        if unused_sources:
            warnings.append(f"证据表中存在正文未使用的来源：{unused_sources}")

        return warnings

    def check_weak_source_claims(
        self,
        report: str,
        evidence_sources: dict[str, dict[str, str]],
    ) -> list[str]:
        """检查 weak 来源是否支撑了过强、过具体的结论。"""
        warnings = []
        sentences = self.split_sentences(report)

        for sentence in sentences:
            citation_ids = self.extract_citations(sentence)
            if not citation_ids:
                continue

            source_infos = [
                evidence_sources.get(source_id)
                for source_id in citation_ids
                if evidence_sources.get(source_id)
            ]

            if not source_infos:
                continue

            only_weak = all(
                source.get("confidence") == "weak"
                for source in source_infos
            )

            if not only_weak:
                continue

            has_number = bool(self.NUMBER_PATTERN.search(sentence))
            has_hedge = any(word in sentence for word in self.HEDGE_WORDS)
            has_strong_word = any(word in sentence for word in self.STRONG_WORDS)

            if has_number and not has_hedge:
                warnings.append(
                    f"weak 来源支撑的数字缺少限定语：{sentence[:120]}"
                )

            if has_strong_word:
                warnings.append(
                    f"weak 来源支撑的结论使用了强确定性措辞：{sentence[:120]}"
                )

        return warnings

    @staticmethod
    def split_sentences(report: str) -> list[str]:
        """粗略切分句子，供 weak 来源断言检查使用。"""
        parts = re.split(r"(?<=[。！？.!?])\s+|\n+", report)
        return [part.strip() for part in parts if part.strip()]

    def score_citations(
        self,
        body_citations: list[str],
        reference_citations: list[str],
        old_citations: list[str],
        evidence_sources: dict[str, dict[str, str]],
    ) -> int:
        """计算引用完整性分数。"""
        score = 100

        if not body_citations:
            score -= 40

        if old_citations:
            score -= 25

        body_ids = set(body_citations)
        reference_ids = set(reference_citations)
        evidence_ids = set(evidence_sources.keys())

        if body_ids - evidence_ids:
            score -= 25

        if body_ids - reference_ids:
            score -= 15

        return max(score, 0)

    def score_evidence_table(
        self,
        report: str,
        evidence_sources: dict[str, dict[str, str]],
    ) -> int:
        """计算证据表结构分数。"""
        score = 100

        if "## 证据表" not in report:
            score -= 60

        if not evidence_sources:
            score -= 40

        return max(score, 0)

    @staticmethod
    def score_source_quality(warnings: list[str]) -> int:
        """根据来源质量告警计算来源质量分。"""
        score = 100

        for warning in warnings:
            if "weak 来源支撑的数字缺少限定语" in warning:
                score -= 15
            elif "weak 来源支撑的结论使用了强确定性措辞" in warning:
                score -= 15

        return max(score, 0)

    def citation_metrics(
        self,
        body_citations: list[str],
        evidence_sources: dict[str, dict[str, str]],
    ) -> dict[str, float]:
        """计算引用命中率，帮助区分“引用错了”和“来源没被用”。"""
        body_ids = set(body_citations)
        evidence_ids = set(evidence_sources.keys())
        matched_ids = body_ids & evidence_ids

        return {
            # 正文引用中，有多少能在证据表找到。
            "citation_precision": self.ratio(len(matched_ids), len(body_ids)),
            # 证据表来源中，有多少真正被正文使用。
            "citation_recall": self.ratio(len(matched_ids), len(evidence_ids)),
        }

    def source_quality_metrics(
        self,
        evidence_sources: dict[str, dict[str, str]],
    ) -> dict[str, float | int]:
        """从证据表提取来源结构指标，避免只看一个来源质量分。"""
        sources = list(evidence_sources.values())
        source_count = len(sources)
        primary_count = sum(
            1
            for source in sources
            if str(source.get("source_type") or "").lower()
            in self.PRIMARY_SOURCE_TYPES
        )
        weak_count = sum(
            1
            for source in sources
            if str(source.get("confidence") or "").lower() == "weak"
        )
        domains = [
            domain
            for source in sources
            if (domain := self.normalized_domain(str(source.get("url") or "")))
        ]
        domain_counts = Counter(domains)
        max_domain_count = max(domain_counts.values()) if domain_counts else 0

        return {
            "primary_source_ratio": self.ratio(primary_count, source_count),
            "weak_source_ratio": self.ratio(weak_count, source_count),
            "unique_domain_count": len(domain_counts),
            "max_domain_concentration": self.ratio(max_domain_count, source_count),
        }

    @staticmethod
    def ratio(numerator: int, denominator: int) -> float:
        """安全计算比例，分母为 0 时返回 0。"""
        return round(numerator / denominator, 4) if denominator else 0.0

    @staticmethod
    def normalized_domain(url: str) -> str:
        """标准化域名，去掉 www. 和端口信息。"""
        domain = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
        return domain[4:] if domain.startswith("www.") else domain
