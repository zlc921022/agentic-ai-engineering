import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse, urlunparse

LOW_QUALITY_KEYWORDS = [
    "top 10",
    "top ",
    "complete guide",
    "ultimate guide",
    "definitive guide",
    "best",
    "best tools",
    "alternatives",
    "2026 guide",
    "services",
    "solutions",
    "hire",
]

MARKETING_HINTS = [
    "book a demo",
    "request a demo",
    "contact sales",
    "custom software development",
    "hire vetted",
    "data annotation services",
    "expert talent network",
    "our services",
]

MARKETING_PATH_HINTS = [
    "/pricing",
    "/contact",
    "/demo",
    "/book-demo",
    "/request-demo",
    "/services",
    "/solutions",
    "/hire",
    "/alternatives",
]

STOP_WORDS = {
    "what", "is", "the", "a", "an", "of", "and", "or", "in", "to", "for",
    "with", "on", "by", "ai", "2025", "2026"
}


GENERAL_METHOD_HINTS = {
    "architecture", "architectures", "fusion", "technique", "techniques",
    "method", "methods", "model", "models", "representation", "alignment"
}

APPLICATION_HINTS = {
    "application", "applications", "use", "uses", "case", "cases",
    "real-world", "healthcare", "medical", "education", "finance"
}

VERTICAL_HINTS = {
    "alzheimer", "disease", "diagnosis", "clinical", "healthcare", "medical",
    "education", "student", "teaching", "finance", "retail", "automotive"
}

ACADEMIC_DOMAINS = {
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "nih.gov",
    "neurips.cc",
    "thecvf.com",
}

OFFICIAL_DOC_DOMAINS = {
    "developers.openai.com",
    "platform.openai.com",
    "docs.cloud.google.com",
    "cloud.google.com",
    "docs.aws.amazon.com",
    "learn.microsoft.com",
    "docs.anthropic.com",
    "docs.github.com",
    "docs.databricks.com",
    "kubernetes.io",
}

COMPANY_TECH_DOMAINS = {
    "ibm.com",
    "mckinsey.com",
    "nvidia.com",
    "pinecone.io",
    "langchain.com",
    "llamaindex.ai",
    "anthropic.com",
    "openai.com",
    "arize.com",
    "wandb.ai",
    "weaviate.io",
    "qdrant.tech",
}

COMMUNITY_DOMAINS = {
    "reddit.com",
    "linkedin.com",
    "medium.com",
    "towardsdatascience.com",
    "dev.to",
    "substack.com",
    "hashnode.dev",
}


@dataclass(frozen=True)
class SourceQualityConfig:
    """来源质量评分规则配置。

    规则仍然由 SourceQualityService 执行；这里集中放可调阈值、权重和词表。
    """
    keep_results: int = 5
    max_per_domain: int = 2
    min_score: int = 40
    base_score: int = 50

    academic_bonus: int = 25
    official_doc_bonus: int = 25
    company_tech_bonus: int = 12
    community_penalty: int = 25

    low_quality_title_penalty: int = 12
    marketing_path_penalty: int = 12
    short_content_penalty: int = 20
    rich_content_bonus: int = 8
    original_source_bonus: int = 10
    marketing_content_penalty: int = 15
    vertical_case_penalty: int = 15

    short_content_chars: int = 80
    rich_content_chars: int = 300
    max_relevance_bonus: int = 25
    relevance_hit_bonus: int = 5
    no_relevance_penalty: int = 25

    low_quality_keywords: tuple[str, ...] = tuple(LOW_QUALITY_KEYWORDS)
    marketing_hints: tuple[str, ...] = tuple(MARKETING_HINTS)
    marketing_path_hints: tuple[str, ...] = tuple(MARKETING_PATH_HINTS)
    stop_words: frozenset[str] = frozenset(STOP_WORDS)

    general_method_hints: frozenset[str] = frozenset(GENERAL_METHOD_HINTS)
    application_hints: frozenset[str] = frozenset(APPLICATION_HINTS)
    vertical_hints: frozenset[str] = frozenset(VERTICAL_HINTS)

    academic_domains: frozenset[str] = frozenset(ACADEMIC_DOMAINS)
    official_doc_domains: frozenset[str] = frozenset(OFFICIAL_DOC_DOMAINS)
    company_tech_domains: frozenset[str] = frozenset(COMPANY_TECH_DOMAINS)
    community_domains: frozenset[str] = frozenset(COMMUNITY_DOMAINS)


class SourceQualityService:
    """来源质量评分与筛选服务。

    这个服务是搜索质量治理的核心规则层：它不发起搜索，只处理搜索后端返回的
    原始结果，并给每条来源打分、去重、控制域名集中度。

    评分逻辑是可解释的规则 MVP：
    - academic / official_doc 加权；
    - community / 营销页 / 内容过短降权；
    - 与 query 关键词匹配越多，相关性越高；
    - 同一域名默认最多保留 max_per_domain 条，避免来源单一。

    举例：
    搜索结果里同时有 arxiv 论文、官方文档、Medium 博客和营销榜单，
    SourceQualityService 会优先保留论文和官方文档，并把低质量标题写入 reasons。
    """

    def __init__(
            self,
            keep_results: int | None = None,
            max_per_domain: int | None = None,
            config: SourceQualityConfig | None = None,
    ):
        """初始化评分配置。

        keep_results / max_per_domain 支持局部覆盖，便于不同搜索场景复用同一套规则。
        """
        config = config or SourceQualityConfig()
        if keep_results is not None:
            config = replace(config, keep_results=keep_results)
        if max_per_domain is not None:
            config = replace(config, max_per_domain=max_per_domain)

        self.config = config
        # 兼容旧调用方可能读取实例属性的情况。
        self.keep_results = config.keep_results
        self.max_per_domain = config.max_per_domain

    def process_result(self, query: str, search_results: str | dict[str, Any]) -> dict[Any, Any]:
        """处理一次搜索返回的原始结果。

        输入结构示例：
        {
           "backend": "duckduckgo",
            "results": [
                 {"title": "...", "url": "...", "content": "..."}
            ],
            "notices": []
        }

        输出会保留 backend / notices，并把 results 替换为已去重、已评分、
        已过滤和已控制域名集中度的来源列表。
        """
        if isinstance(search_results, str):
            return {}

        results = search_results.get("results", [])
        cleaned = self.dequed_result(results)
        scored = [self.score_item(query, item) for item in cleaned]
        filtered = [
            item for item in scored
            if item.get("score", 0) >= self.config.min_score
        ]
        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        selected, skipped_by_domain = self.select_diverse_results(filtered)

        notices = search_results.get("notices", [])
        notices.append(
            f"来源质量过滤：原始 {len(results)} 条，去重后 {len(cleaned)} 条，过滤后 {len(filtered)} 条，"
            f"最终保留 {len(selected)} 条"
        )
        if skipped_by_domain:
            notices.append(
                f"来源多样性控制：同一域名优先最多保留 {self.config.max_per_domain} 条，"
                f"跳过或延后 {skipped_by_domain} 条同域名结果"
            )

        return {
            "backend": search_results.get("backend", "unknown"),
            "notices": notices,
            "results": selected
        }

    def select_diverse_results(
        self,
        scored_results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """优先控制域名集中度；候选不足时再回填，避免来源数量过少。"""
        selected: list[dict[str, Any]] = []
        delayed: list[dict[str, Any]] = []
        domain_counts: Counter[str] = Counter()

        for item in scored_results:
            domain = str(item.get("domain") or "")
            if domain and domain_counts[domain] >= self.config.max_per_domain:
                delayed.append(item)
                continue

            selected.append(item)
            if domain:
                domain_counts[domain] += 1
            if len(selected) >= self.config.keep_results:
                return selected, len(delayed)

        # 搜索结果不够分散时，宁愿回填一些同域名结果，也不要让任务没有足够材料。
        for item in delayed:
            selected.append(item)
            if len(selected) >= self.config.keep_results:
                break

        return selected, len(delayed)

    def dequed_result(self, search_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按规范化 URL 和标题去重。"""
        url_set = set()
        title_set = set()
        dequed_results = []

        for result in search_results:
            url = self.normalize_url(result.get("url") or "")
            title = self.normalize_title(result.get("title") or "")
            if not url or not title:
                continue
            if url in url_set:
                continue
            if title in title_set:
                continue

            url_set.add(url)
            title_set.add(title)
            dequed_results.append({**result, "url": url})

        return dequed_results

    def score_item(self, query : str, item: dict[str, Any]) -> dict[str, Any]:
        """给单条搜索结果打分并写入 reasons。

        reasons 是可解释性信息，会进入证据表/调试信息，方便判断某个来源
        为什么被认为是 academic、company_tech、community 或 unknown。
        """
        url = item.get("url") or ""
        title = item.get("title") or ""
        content = self.clean_content(item.get("content") or "")
        content_lower = content.lower()
        title_lower = title.lower()
        domain = self.get_domain(url)
        path_lower = urlparse(url).path.lower()

        score = self.config.base_score
        reasons = [f"基础分 {self.config.base_score}"]

        source_type = self.get_source_type(domain)

        if source_type == "academic":
            score += self.config.academic_bonus
            reasons.append("学术/官方来源")
        elif source_type == "official_doc":
            score += self.config.official_doc_bonus
            reasons.append("学术/官方来源")
        elif source_type == "company_tech":
            score += self.config.company_tech_bonus
            reasons.append("企业技术来源")
        elif source_type == "community":
            score -= self.config.community_penalty
            reasons.append("社区/个人内容平台降权")

        if any(keyword in title_lower for keyword in self.config.low_quality_keywords):
            score -= self.config.low_quality_title_penalty
            reasons.append("标题疑似营销/榜单内容")

        if any(hint in path_lower for hint in self.config.marketing_path_hints):
            score -= self.config.marketing_path_penalty
            reasons.append("URL 路径疑似营销/转化页面")

        if len(content) < self.config.short_content_chars:
            score -= self.config.short_content_penalty
            reasons.append("摘要过短")
        if len(content) > self.config.rich_content_chars:
            score += self.config.rich_content_bonus
            reasons.append("摘要信息较充分")

        if self.is_original_like_source(url, domain, source_type):
            score += self.config.original_source_bonus
            reasons.append("原始/一手资料加权")

        if any((hint in content_lower or hint in title_lower) for hint in self.config.marketing_hints):
            score -= self.config.marketing_content_penalty
            reasons.append("疑似营销/服务页面降权")

        # 新增“通用技术问题 vs 垂直案例”降权
        query_tokens = self.tokenize(query)
        full_text_lower = f"{title_lower} {content_lower}"
        is_general_method_query = bool(query_tokens & self.config.general_method_hints)
        is_application_query = bool(query_tokens & self.config.application_hints)
        is_vertical_case = any(word in full_text_lower for word in self.config.vertical_hints)

        if is_general_method_query and not is_application_query and is_vertical_case:
            score -= self.config.vertical_case_penalty
            reasons.append("查询偏通用技术，垂直行业案例降权")

        score = max(0, min(100, score))

        rel_score, rel_reasons = self.relevance_score(query, title, content)
        score += rel_score
        score = max(0, min(100, score))
        reasons.extend(rel_reasons)

        return {
            **item,
            "content": content,
            "score": score,
            "reasons": reasons,
            "source_type": source_type,
            "domain": domain,
        }


    def relevance_score(self, query: str, title: str, content: str) -> tuple[int, list[str]]:
        """根据 query 与标题/正文的关键词交集计算相关性加减分。"""
        query_words = self.tokenize(query)
        text_words = self.tokenize(title + " " + content)
        hit_words = query_words & text_words

        score = 0
        reasons = []

        if hit_words:
            score += min(
                len(hit_words) * self.config.relevance_hit_bonus,
                self.config.max_relevance_bonus,
            )
            reasons.append(f"命中查询词: {', '.join(sorted(hit_words))}")
        else:
            score -= self.config.no_relevance_penalty
            reasons.append("与查询词相关性较弱")

        return score, reasons

    def tokenize(self, text: str) -> set[str]:
        """把英文文本切成关键词集合，并过滤停用词。"""
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
        return {word for word in words if word not in self.config.stop_words}

    @staticmethod
    def normalize_url(url: str) -> str:
        """规范化 URL，去掉无意义 query/fragment，便于去重。"""
        if not url:
            return ""
        parsed_url = urlparse(url)
        # 特殊处理下 youtube 链接
        if "youtube.com" in parsed_url.netloc and parsed_url.path == "/watch":
            cleaned = parsed_url._replace(
                scheme=parsed_url.scheme.lower(),
                netloc=parsed_url.netloc.lower(),
                fragment="",
            )
            return str(urlunparse(cleaned)).rstrip("/")

        cleaned = parsed_url._replace(
            scheme=parsed_url.scheme.lower(),
            netloc=parsed_url.netloc.lower(),
            fragment="",
            query="",
        )
        return str(urlunparse(cleaned)).rstrip("/")

    @staticmethod
    def normalize_title(title: str) -> str:
        """规范化标题，用于标题去重。"""
        return "".join(title.lower().split())[:120]

    @staticmethod
    def get_domain(url) -> str:
        """从 URL 中提取域名，并去掉 www. 前缀。"""
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def get_source_type(self, domain: str) -> str:
        """根据域名规则判断来源类型。"""
        if domain.endswith(".edu") or domain.endswith(".gov"):
            return "academic"

        if self.domain_matches(domain, self.config.academic_domains):
            return "academic"

        if self.domain_matches(domain, self.config.official_doc_domains):
            return "official_doc"

        if self.domain_matches(domain, self.config.company_tech_domains):
            return "company_tech"

        if self.domain_matches(domain, self.config.community_domains):
            return "community"

        return "unknown"

    @classmethod
    def is_original_like_source(
        cls,
        url: str,
        domain: str,
        source_type: str,
    ) -> bool:
        """论文、官方文档、政府/高校站点通常比转载和营销页更接近一手资料。"""
        url_lower = url.lower()
        return (
            source_type in {"academic", "official_doc"}
            or domain.endswith(".edu")
            or domain.endswith(".gov")
            or url_lower.endswith(".pdf")
            or ".pdf" in url_lower
        )

    @staticmethod
    def clean_content(content: str) -> str:
        """清理 Markdown 链接、图片和多余空白，得到适合评分的正文摘要。"""
        if not content:
            return ""
        text = content
        # 去掉 Markdown 图片：![xxx](url)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        # 去掉 Markdown 链接，但保留文字：[title](url) -> title
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # 去掉空链接：[](url)
        text = re.sub(r"\[\]\([^)]+\)", " ", text)
        # 合并多余空白
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def domain_matches(domain: str, candidates: set[str]) -> bool:
        """判断域名是否命中候选域名或其子域名。"""
        return any(domain == item or domain.endswith("." + item) for item in candidates)
