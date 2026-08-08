import time
from typing import Any

from backend.core.app_logger import get_logger
from backend.core.config import Config
from backend.domain.models import TodoItem, SearchResult
from backend.llm.function_calling_agent import (
    FunctionCallingAgent,
    FunctionCallingRunResult,
)
from backend.search.search_tool import SearchTool
from backend.services.search_quality_retry_service import SearchQualityRetryService
from backend.services.source_quality import SourceQualityService
from backend.tools.supplemental_search_tool import SupplementalSearchContext


class SearchService:
    """搜索编排服务：把 TodoItem 转换成可供总结模型使用的 SearchResult。

    这个类不是具体搜索引擎适配器，它负责搜索链路的“业务编排”：
    1. 根据 planner query 生成多个搜索变体；
    2. 调用 SearchTool 执行搜索；
    3. 用 SourceQualityService 去重、排序、筛选高质量来源；
    4. 如果来源质量不足，触发一次 SearchQualityRetryService 补检索；
    5. 给来源打上 T1-S1 这种稳定 source_id；
    6. 同时产出“前端短摘要”和“总结模型长上下文”。

    举例：
    task.query = "AI Agent evaluation production"
    SearchService 可能额外搜索 official documentation / academic paper / failure cases，
    最终保留 5 个更可靠来源给 SummaryService。
    """

    DEFAULT_MAX_TOKENS_PER_SOURCE = 1000

    def __init__(
            self,
            search_tool: SearchTool,
            config: Config | None = None,
            retry_service: SearchQualityRetryService | None = None,
            function_calling_agent: FunctionCallingAgent | None = None,
    ) -> None:
        """注入搜索工具、配置和补检索策略。"""
        self.search_tool = search_tool
        self.source_quality = SourceQualityService()
        self.logger = get_logger(__name__)
        self.config = config
        self.retry_service = retry_service or SearchQualityRetryService()
        # Function Calling 是可选补检索策略。未注入、关闭配置或执行失败时，
        # SearchService 会继续使用原来的确定性 retry query，保证旧流程可用。
        self.function_calling_agent = function_calling_agent

    def run_search(
            self,
            task: TodoItem,
            backend: str = "hybrid",
            max_results: int = 5,
            mode: str = "structured",
            fetch_full_page: bool = False,
            max_tokens_per_source: int = DEFAULT_MAX_TOKENS_PER_SOURCE,
            enable_multi_query_search: bool = True,
            query_variant_count: int = 3,
    ) -> SearchResult:
        """执行单个研究任务的完整搜索链路。

        返回的 SearchResult 有两个重点字段：
        - results：结构化来源列表，给前端证据表和后续报告使用；
        - search_results_text：拼好的长研究上下文，直接喂给 SummaryService。
        """

        task_index = task.id
        title = task.title
        intent = task.intent
        query = task.query
        requested_max_results = max(max_results * 2, 8)
        query_variants = self.build_query_variants(
            query,
            enabled=enable_multi_query_search,
            variant_count=query_variant_count,
        )
        # observation 只记录已经发生的搜索行为，不参与任何质量决策。
        observation: dict[str, Any] = {
            "initial_query_count": len(query_variants),
            "retry_enabled": bool(
                self.config is not None
                and self.config.enable_search_quality_retry
            ),
            "retry_triggered": False,
            "retry_mode": None,
            "function_calling_attempted": False,
            "tool_call_count": 0,
            "tool_parameter_valid_count": 0,
            "tool_execution_success_count": 0,
            "supplemental_search_success": False,
            "rule_retry_used": False,
            "fallback_used": False,
            "fallback_reason": None,
            "tool_error_codes": [],
            "tool_duration_ms": [],
            "observation_error": None,
        }
        started_at = time.perf_counter()
        self.logger.info(
            "search started task_id=%s title=%s backend=%s query=%s query_variants=%s raw_max_results=%s mode=%s",
            task_index,
            title,
            backend,
            query,
            len(query_variants),
            requested_max_results,
            mode,
        )
        search_results = self.run_query_variants(
            queries=query_variants,
            backend=backend,
            requested_max_results=requested_max_results,
            mode=mode,
            fetch_full_page=fetch_full_page,
            max_tokens_per_source=max_tokens_per_source,
            original_title=title,
        )

        raw_count = self._result_count(search_results)
        observation["initial_result_count"] = raw_count
        # 最终保留数量仍由 max_results 控制；默认是 5，但可以通过 SEARCH_MAX_RESULTS 调整。
        source_quality = SourceQualityService(keep_results=max(max_results, 1))
        filtered_result = source_quality.process_result(query, search_results)
        observation["initial_filtered_result_count"] = self._result_count(
            filtered_result
        )

        filtered_result = self.apply_search_quality_retry(
            task=task,
            backend=backend,
            mode=mode,
            fetch_full_page=fetch_full_page,
            max_tokens_per_source=max_tokens_per_source,
            requested_max_results=requested_max_results,
            source_quality=source_quality,
            first_search_results=search_results,
            filtered_result=filtered_result,
            observation=observation,
        )

        self.attach_source_ids(task_index, filtered_result)
        filtered_count = self._result_count(filtered_result)
        observation["final_result_count"] = filtered_count
        observation["search_duration_ms"] = max(
            0,
            round((time.perf_counter() - started_at) * 1000),
        )
        notices = filtered_result.get("notices", []) if isinstance(filtered_result, dict) else []
        resolved_backend = (
            filtered_result.get("backend", "unknown")
            if isinstance(filtered_result, dict)
            else "unknown"
        )
        source_ids = [
            item.get("source_id")
            for item in filtered_result.get("results", [])
            if isinstance(item, dict)
        ] if isinstance(filtered_result, dict) else []

        self.logger.info(
            "search done task_id=%s backend=%s resolved_backend=%s raw_results=%s filtered_results=%s notices=%s source_ids=%s elapsed=%.2fs",
            task_index,
            backend,
            resolved_backend,
            raw_count,
            filtered_count,
            len(notices),
            source_ids,
            time.perf_counter() - started_at,
        )

        sources_summary = self.build_sources_summary(filtered_result)
        research_context = self.build_research_context(
            filtered_result,
            max_tokens_per_source=max_tokens_per_source,
        )
        self.logger.info(
            "search context built task_id=%s sources_summary_chars=%s research_context_chars=%s max_tokens_per_source=%s",
            task_index,
            len(sources_summary),
            len(research_context),
            max_tokens_per_source,
        )

        return SearchResult(
            task_id=task.id,
            title=title,
            intent=intent,
            query=query,
            results=filtered_result,
            # 重要：
            # search_results_text 不再是给前端看的短来源摘要，
            # 而是给 SummaryService 的“研究上下文”。
            search_results_text=research_context,
            observation=observation,
        )

    @staticmethod
    def build_sources_summary(search_result: str | dict[str, Any]) -> str:
        """构造给前端展示的短来源摘要。
        注意：
        - 这里不要塞大段正文；
        - 只展示 source_id / title / url / score / source_type；
        - 详细正文交给 build_research_context() 喂给 summarizer。
        """
        if not isinstance(search_result, dict):
            return ""

        results = search_result.get("results") or []
        if not results:
            return "暂无来源"

        lines: list[str] = []
        for item in results:
            if not isinstance(item, dict):
                continue

            source_id = item.get("source_id") or ""
            title = item.get("title") or ""
            url = item.get("url") or ""
            source_type = item.get("source_type") or "unknown"
            search_query = item.get("search_query") or ""
            score = item.get("score")

            prefix = f"[{source_id}] " if source_id else ""
            meta = f"来源类型: {source_type}"
            if score is not None:
                meta += f"，评分: {score}"
            if search_query:
                meta += f"，检索词: {search_query}"

            lines.append(f"* {prefix}{title} - {url}\n  {meta}")

        notices = search_result.get("notices") or []
        if notices:
            lines.append("")
            lines.append("系统提示：")
            for notice in notices:
                if notice:
                    lines.append(f"- {notice}")

        return "\n".join(lines).strip()

    @staticmethod
    def build_research_context(
            search_result: str | dict[str, Any],
            max_tokens_per_source: int = DEFAULT_MAX_TOKENS_PER_SOURCE,
    ) -> str:
        """构造给 summarizer 使用的研究上下文。
        这个方法为总结模型准备独立的长研究上下文：
        - 每个来源保留 source_id、标题、URL、来源类型、评分；
        - 每个来源保留较完整 content；
        - 对单个来源做长度限制，避免 prompt 爆炸；
        - 不直接给前端展示，主要用于总结质量。
        """
        if not isinstance(search_result, dict):
            return str(search_result or "")

        results = search_result.get("results") or []
        if not results:
            notices = search_result.get("notices") or []
            if notices:
                return "未检索到有效来源。\n\n" + "\n".join(f"- {notice}" for notice in notices)
            return "未检索到有效来源。"

        lines: list[str] = [
            f"搜索后端：{search_result.get('backend', 'unknown')}",
            "",
            "以下是当前任务的检索上下文。请优先基于这些来源提炼结论，不要编造来源中没有的信息。",
            "",
        ]

        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue

            source_id = item.get("source_id") or f"S{index}"
            title = item.get("title") or ""
            url = item.get("url") or ""
            source_type = item.get("source_type") or "unknown"
            search_query = item.get("search_query") or ""
            score = item.get("score")
            reasons = item.get("reasons") or []
            content = item.get("content") or ""

            content = SearchService._limit_text_by_tokens(
                content,
                max_tokens_per_source,
            )

            lines.extend([
                f"## 来源 [{source_id}] {title}",
                "",
                f"- URL: {url}",
                f"- 来源类型: {source_type}",
            ])

            if search_query:
                lines.append(f"- 命中的检索词: {search_query}")

            if score is not None:
                lines.append(f"- 来源质量评分: {score}/100")

            if reasons:
                lines.append(f"- 来源质量判断: {'; '.join(str(reason) for reason in reasons)}")

            lines.extend([
                "",
                "正文内容：",
                content or "暂无正文摘要",
                "",
            ])

        notices = search_result.get("notices") or []
        if notices:
            lines.append("## 系统提示")
            for notice in notices:
                if notice:
                    lines.append(f"- {notice}")

        return "\n".join(lines).strip()

    @staticmethod
    def _limit_text_by_tokens(text: str, token_limit: int) -> str:
        """用粗略 1 token ≈ 4 字符限制单来源正文长度。"""
        if not text:
            return ""

        char_limit = max(token_limit, 1) * 4
        if len(text) <= char_limit:
            return text

        return text[:char_limit] + "... [truncated]"

    def attach_source_ids(self, task_index: int, filtered_result: dict[str, Any]):
        """给筛选后的来源分配稳定 source_id。

        格式为 T{任务编号}-S{来源编号}，例如 T2-S3。
        这些 ID 会贯穿任务总结、最终报告、证据表和质检器。
        """
        if not isinstance(filtered_result, dict):
            return
        results = filtered_result.get("results", [])
        for source_idx, item in enumerate(results, start=1):
            item["source_id"] = f"T{task_index}-S{source_idx}"

    @staticmethod
    def _result_count(value: str | dict[str, Any]) -> int:
        """安全统计搜索结果数量，便于日志排查搜索质量过滤前后差异。"""
        if not isinstance(value, dict):
            return 0
        results = value.get("results") or []
        return len(results) if isinstance(results, list) else 0

    def run_query_variants(
            self,
            *,
            queries: list[str],
            backend: str,
            requested_max_results: int,
            mode: str,
            fetch_full_page: bool,
            max_tokens_per_source: int,
            original_title: str,
    ) -> dict[str, Any]:
        """依次执行多个搜索 query，并把结果合并成 source_quality 可处理的结构。

        这里故意保持“顺序执行”，不引入搜索并发：
        - 改动小；
        - DuckDuckGo 更不容易被瞬时并发打爆；
        - 日志顺序更容易排查。
        """
        merged_results: list[dict[str, Any]] = []
        notices: list[str] = []
        resolved_backends: list[str] = []

        for search_query in queries:
            try:
                search_results = self.search_tool.run(
                    {
                        "input": search_query,
                        "max_results": requested_max_results,
                        "mode": mode,
                        "backend": backend,
                        "fetch_full_page": fetch_full_page,
                        "max_tokens_per_source": max_tokens_per_source,
                    }
                )
            except Exception as exc:
                self.logger.exception(
                    "search failed task=%s query=%s",
                    original_title,
                    search_query,
                )
                notices.append(f"搜索阶段异常 query={search_query}：{exc}")
                continue

            if not isinstance(search_results, dict):
                notices.append(f"搜索结果格式异常 query={search_query}。")
                continue

            resolved_backends.append(str(search_results.get("backend") or backend))
            raw_notices = search_results.get("notices") or []
            if isinstance(raw_notices, list):
                notices.extend(str(notice) for notice in raw_notices if notice)

            raw_results = search_results.get("results") or []
            if not isinstance(raw_results, list):
                notices.append(f"搜索结果 results 字段异常 query={search_query}。")
                continue

            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                # 记录来源来自哪个 query，方便 Note / 调试时看多查询是否真的带来更好来源。
                merged_results.append({**item, "search_query": search_query})

        search_mode_label = "多查询检索" if len(queries) > 1 else "单查询检索"
        notices.insert(
            0,
            f"{search_mode_label}：{len(queries)} 个 query，合并 {len(merged_results)} 条原始结果",
        )
        return {
            "backend": self.merge_backend_labels(resolved_backends, backend),
            "results": merged_results,
            "notices": notices,
        }

    @staticmethod
    def build_query_variants(
            query: str,
            *,
            enabled: bool = True,
            variant_count: int = 3,
    ) -> list[str]:
        """生成轻量搜索变体。

        第一版只做确定性规则，不调用 LLM 生成 query：
        1. 原始 query：保持 planner 意图；
        2. 官方/学术 query：提高论文、官方文档、一手资料出现概率；
        3. 风险/局限 query：补充失败案例和限制条件，避免报告只写优点。
        """
        cleaned_query = " ".join(str(query or "").split())
        if not cleaned_query:
            return []

        variants = [cleaned_query]
        if enabled:
            variants.extend(
                [
                    f"{cleaned_query} official documentation academic paper arxiv",
                    f"{cleaned_query} limitations risks evaluation failure cases",
                ]
            )

        safe_count = max(1, min(int(variant_count or 1), len(variants)))
        return variants[:safe_count]

    @staticmethod
    def merge_backend_labels(backends: list[str], fallback: str) -> str:
        """合并多次搜索实际使用的 backend 标签，便于日志和前端展示。"""
        unique_backends = sorted({backend for backend in backends if backend})
        if not unique_backends:
            return fallback
        if len(unique_backends) == 1:
            return unique_backends[0]
        return "+".join(unique_backends)

    def apply_search_quality_retry(
            self,
            *,
            task: TodoItem,
            backend: str,
            mode: str,
            fetch_full_page: bool,
            max_tokens_per_source: int,
            requested_max_results: int,
            source_quality: SourceQualityService,
            first_search_results: dict[str, Any],
            filtered_result: dict[str, Any],
            observation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据首次过滤结果决定是否执行一次补检索。

        这是轻量 Agent 化的一步：系统不是被动接受搜索结果，
        而是会根据来源数量、强来源数量、弱来源比例判断是否需要补查。
        """

        metrics = observation if observation is not None else {}
        # 测试、批处理或未来调用方可能直接调用这个公开方法，没有先经过
        # run_search()；setdefault 保证两种入口得到一致的观测字段。
        observation_defaults = {
            "retry_enabled": bool(
                self.config is not None
                and self.config.enable_search_quality_retry
            ),
            "retry_triggered": False,
            "retry_mode": None,
            "function_calling_attempted": False,
            "tool_call_count": 0,
            "tool_parameter_valid_count": 0,
            "tool_execution_success_count": 0,
            "supplemental_search_success": False,
            "rule_retry_used": False,
            "fallback_used": False,
            "fallback_reason": None,
            "tool_error_codes": [],
            "tool_duration_ms": [],
            "observation_error": None,
        }
        for key, value in observation_defaults.items():
            metrics.setdefault(key, value)

        if self.config is None or not self.config.enable_search_quality_retry:
            metrics["retry_enabled"] = False
            return filtered_result

        decision = self.retry_service.decide(task, filtered_result)
        if not decision.should_retry:
            metrics["retry_triggered"] = False
            return filtered_result

        retry_mode = self._resolved_retry_mode()
        metrics.update({
            "retry_triggered": True,
            "retry_mode": retry_mode,
            "retry_reasons": list(decision.reasons),
        })
        self.logger.info(
            "search quality retry triggered task_id=%s mode=%s reasons=%s retry_queries=%s",
            task.id,
            retry_mode,
            decision.reasons,
            decision.retry_queries,
        )

        retry_results: dict[str, Any] | None = None
        if retry_mode == "function_calling":
            retry_results = self._run_function_calling_retry(
                task=task,
                reasons=decision.reasons,
                filtered_result=filtered_result,
                backend=backend,
                requested_max_results=requested_max_results,
                mode=mode,
                fetch_full_page=fetch_full_page,
                max_tokens_per_source=max_tokens_per_source,
                observation=metrics,
            )

        if retry_results is None:
            # 原规则版既是默认策略，也是 Function Calling 失败后的可靠降级路径。
            metrics["rule_retry_used"] = True
            if retry_mode == "function_calling":
                metrics["fallback_used"] = True
                metrics["fallback_reason"] = (
                    metrics.get("fallback_reason")
                    or "function_calling_no_usable_result"
                )
            retry_results = self.run_query_variants(
                queries=decision.retry_queries,
                backend=backend,
                requested_max_results=requested_max_results,
                mode=mode,
                fetch_full_page=fetch_full_page,
                max_tokens_per_source=max_tokens_per_source,
                original_title=task.title,
            )

        metrics["retry_result_count"] = self._result_count(retry_results)
        metrics["retry_success"] = metrics["retry_result_count"] > 0
        merged_results = self.merge_search_results(
            first_result=first_search_results,
            retry_result=retry_results,
            retry_reasons=decision.reasons,
        )

        return source_quality.process_result(task.query, merged_results)

    def _resolved_retry_mode(self) -> str:
        """解析当前补检索策略；缺少 Agent 时主动退回规则版。"""
        configured = (
            self.config.search_retry_mode
            if self.config is not None
            else "rule"
        )
        if configured == "function_calling" and self.function_calling_agent is not None:
            return "function_calling"
        return "rule"

    def _run_function_calling_retry(
            self,
            *,
            task: TodoItem,
            reasons: list[str],
            filtered_result: dict[str, Any],
            backend: str,
            requested_max_results: int,
            mode: str,
            fetch_full_page: bool,
            max_tokens_per_source: int,
            observation: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """让模型通过 supplemental_search 执行一次语义补检索。

        这里不把 backend、超时、结果数暴露给模型；这些可信运行参数全部由
        SupplementalSearchContext 注入。任何异常或无有效结果都会返回 None，
        外层随后使用确定性 query rewrite 兜底。
        """
        agent = self.function_calling_agent
        if agent is None:
            if observation is not None:
                observation["fallback_reason"] = "function_calling_agent_unavailable"
            return None
        if observation is not None:
            observation["function_calling_attempted"] = True

        prompt = self._build_function_calling_retry_prompt(
            task=task,
            reasons=reasons,
            filtered_result=filtered_result,
        )
        context = SupplementalSearchContext(
            backend=backend,
            requested_max_results=requested_max_results,
            mode=mode,
            fetch_full_page=fetch_full_page,
            max_tokens_per_source=max_tokens_per_source,
            timeout_seconds=(
                self.config.search_timeout_seconds
                if self.config is not None
                else 30
            ),
        )

        try:
            run_result = agent.run(
                prompt,
                context=context,
                forced_tool_name="supplemental_search",
            )
        except Exception:
            if observation is not None:
                observation["fallback_reason"] = "function_calling_exception"
                observation["tool_error_codes"] = ["AGENT_EXCEPTION"]
            self.logger.exception(
                "function calling retry failed task_id=%s; fallback=rule",
                task.id,
            )
            return None

        if observation is not None:
            self._record_function_calling_observation(
                observation,
                run_result,
                task_id=task.id,
            )

        retry_result = self._first_successful_supplemental_search(run_result)
        if retry_result is None:
            if observation is not None:
                observation["fallback_reason"] = "tool_returned_no_usable_result"
            self.logger.warning(
                "function calling retry returned no usable result task_id=%s; fallback=rule",
                task.id,
            )
            return None

        if observation is not None:
            observation["supplemental_search_success"] = True
        self.logger.info(
            "function calling retry done task_id=%s tool_calls=%s result_count=%s",
            task.id,
            len(run_result.executions),
            self._result_count(retry_result),
        )
        return retry_result

    def _record_function_calling_observation(
            self,
            observation: dict[str, Any],
            run_result: FunctionCallingRunResult,
            *,
            task_id: int,
    ) -> None:
        """安全提取工具指标；坏指标只能降级，不能阻塞补检索结果。

        ToolRegistry 当前返回稳定 dict，但未来新增工具或自定义 Registry 后，
        result/meta/error 结构仍可能不完整。这里逐项做类型保护，并保留一个
        非敏感错误码供 SSE/Benchmark 识别观测降级。
        """
        try:
            executions = list(getattr(run_result, "executions", None) or [])
            error_codes: list[str] = []
            parameter_valid_count = 0
            execution_success_count = 0
            duration_samples: list[int] = []

            for execution in executions:
                result = getattr(execution, "result", None)
                if not isinstance(result, dict):
                    error_codes.append("INVALID_TOOL_RESULT")
                    continue

                error = result.get("error")
                error = error if isinstance(error, dict) else {}
                error_code = str(error.get("code") or "")
                if error_code:
                    error_codes.append(error_code)
                if error_code != "INVALID_ARGUMENTS":
                    parameter_valid_count += 1
                if result.get("success") is True:
                    execution_success_count += 1

                meta = result.get("meta")
                meta = meta if isinstance(meta, dict) else {}
                duration = meta.get("duration_ms")
                if isinstance(duration, (int, float)) and not isinstance(
                        duration,
                        bool,
                ):
                    duration_samples.append(max(0, round(duration)))

            observation.update({
                "tool_call_count": len(executions),
                "tool_parameter_valid_count": parameter_valid_count,
                "tool_execution_success_count": execution_success_count,
                "tool_error_codes": error_codes,
                "tool_duration_ms": duration_samples,
            })
        except Exception:
            observation["observation_error"] = (
                "FUNCTION_CALLING_OBSERVATION_FAILED"
            )
            self.logger.exception(
                "function calling observation failed task_id=%s; "
                "continue business flow",
                task_id,
            )

    @staticmethod
    def _first_successful_supplemental_search(
            run_result: FunctionCallingRunResult,
    ) -> dict[str, Any] | None:
        """提取第一次成功补检索；第一版每个任务最多执行一次搜索。"""
        for data in run_result.successful_tool_data("supplemental_search"):
            if isinstance(data, dict):
                return data
        return None

    @staticmethod
    def _build_function_calling_retry_prompt(
            *,
            task: TodoItem,
            reasons: list[str],
            filtered_result: dict[str, Any],
    ) -> str:
        """构造紧凑证据目录，避免把所有来源全文重复发送给决策模型。"""
        source_lines: list[str] = []
        for index, item in enumerate(filtered_result.get("results") or [], start=1):
            if not isinstance(item, dict):
                continue
            source_lines.append(
                f"{index}. title={item.get('title', '')}; "
                f"type={item.get('source_type', 'unknown')}; "
                f"score={item.get('score', 0)}; "
                f"domain={item.get('domain', '')}"
            )
        source_catalog = "\n".join(source_lines) or "暂无有效来源"
        reason_text = "；".join(reasons) or "现有来源覆盖不足"
        return (
            "请针对当前研究任务执行一次补充搜索，不要重复原始 query。\n\n"
            f"任务标题：{task.title}\n"
            f"研究意图：{task.intent}\n"
            f"原始 query：{task.query}\n"
            f"触发原因：{reason_text}\n\n"
            f"已有来源目录：\n{source_catalog}\n\n"
            "请选择最缺失的一个证据方向，调用 supplemental_search。"
        )

    @staticmethod
    def merge_search_results(
            first_result: dict[str, Any],
            retry_result: dict[str, Any],
            retry_reasons: list[str],
    ) -> dict[str, Any]:
        """合并首次搜索和补检索结果，并保留补检索原因。"""
        first_results = first_result.get("results") or []
        retry_results = retry_result.get("results") or []

        notices: list[str] = []
        notices.extend(first_result.get("notices") or [])
        notices.append(SearchQualityRetryService.build_retry_notice(retry_reasons))
        notices.extend(retry_result.get("notices") or [])

        return {
            "backend": SearchService.merge_backend_labels(
                [
                    str(first_result.get("backend") or ""),
                    str(retry_result.get("backend") or ""),
                ],
                fallback=str(first_result.get("backend") or "unknown"),
            ),
            "results": [*first_results, *retry_results],
            "notices": notices,
        }
